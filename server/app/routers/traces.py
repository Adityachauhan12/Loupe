import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_api_key
from app.db import get_db
from app.models import ApiKey, Replay, Span, Trace
from app.routers.replays import _run_branch
from app.schemas import (
    BranchCreated,
    BranchIn,
    TraceCreated,
    TraceDetail,
    TraceIn,
    TraceList,
    TraceListItem,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/traces", tags=["traces"])


@router.post("", response_model=TraceCreated, status_code=status.HTTP_201_CREATED)
async def ingest_trace(
    payload: TraceIn,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> TraceCreated:
    trace_values = {
        "id": payload.id,
        "project_id": api_key.project_id,
        "name": payload.name,
        "status": payload.status,
        "input": payload.input,
        "output": payload.output,
        "error": payload.error,
        "started_at": payload.started_at,
        "ended_at": payload.ended_at,
        "duration_ms": payload.duration_ms,
        "total_tokens": payload.total_tokens,
        "total_cost_usd": payload.total_cost_usd,
        "extra_metadata": payload.metadata,
        "is_replay": payload.is_replay,
        "replay_of_trace_id": payload.replay_of_trace_id,
        "branched_from_trace_id": payload.branched_from_trace_id,
        "branched_from_span_id": payload.branched_from_span_id,
    }

    # Idempotent: re-delivery of the same trace id is a no-op.
    trace_stmt = (
        insert(Trace).values(**trace_values).on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(trace_stmt)

    if payload.spans:
        span_rows = [
            {
                "id": s.id,
                "trace_id": payload.id,
                "parent_span_id": s.parent_span_id,
                "type": s.type,
                "name": s.name,
                "input": s.input,
                "output": s.output,
                "error": s.error,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "duration_ms": s.duration_ms,
                "model": s.model,
                "provider": s.provider,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "total_tokens": s.total_tokens,
                "cost_usd": s.cost_usd,
                "extra_metadata": s.metadata,
            }
            for s in payload.spans
        ]
        span_stmt = insert(Span).values(span_rows).on_conflict_do_nothing(
            index_elements=["id"]
        )
        await db.execute(span_stmt)

    try:
        await db.commit()
    except (IntegrityError, DataError) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid trace data: {exc.__class__.__name__}",
        ) from exc

    return TraceCreated(trace_id=payload.id, span_count=len(payload.spans))


@router.get("", response_model=TraceList)
async def list_traces(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> TraceList:
    stmt = select(Trace).where(Trace.project_id == api_key.project_id)
    if status_filter is not None:
        stmt = stmt.where(Trace.status == status_filter)

    # Fetch one extra row to determine has_more without a separate COUNT query.
    stmt = stmt.order_by(Trace.started_at.desc()).offset(offset).limit(limit + 1)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = [TraceListItem.model_validate(r) for r in rows[:limit]]

    return TraceList(items=items, limit=limit, offset=offset, has_more=has_more)


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> Trace:
    stmt = (
        select(Trace)
        .where(Trace.id == trace_id, Trace.project_id == api_key.project_id)
        .options(selectinload(Trace.spans))
    )
    result = await db.execute(stmt)
    trace = result.scalar_one_or_none()

    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found",
        )

    return trace


@router.post(
    "/{trace_id}/branch",
    response_model=BranchCreated,
    status_code=status.HTTP_201_CREATED,
)
async def branch_trace(
    trace_id: uuid.UUID,
    payload: BranchIn,
    background_tasks: BackgroundTasks,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> BranchCreated:
    """Branch a trace from a chosen span with an edited output.

    Creates a placeholder ('running') trace linked to the original via the
    branch lineage columns, records a Replay row for diff metadata, and kicks
    off the deterministic branch replay as a BackgroundTask. Returns immediately
    so the dashboard can poll GET /v1/traces/{new_trace_id} for completion.
    """
    # 1. Original trace must exist and belong to this project.
    original = (
        await db.execute(
            select(Trace).where(
                Trace.id == trace_id,
                Trace.project_id == api_key.project_id,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")

    # 2. Branch span must belong to that trace.
    branch_span = (
        await db.execute(
            select(Span).where(Span.id == payload.span_id, Span.trace_id == trace_id)
        )
    ).scalar_one_or_none()
    if branch_span is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch span not found in this trace",
        )

    now = datetime.now(timezone.utc)
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    # 3. Placeholder trace — the engine fills it in. Linked via lineage columns.
    db.add(
        Trace(
            id=new_trace_id,
            project_id=api_key.project_id,
            name=f"{original.name or 'trace'} (branch)",
            status="running",
            input=original.input,
            is_replay=True,
            branched_from_trace_id=original.id,
            branched_from_span_id=branch_span.id,
            started_at=now,
        )
    )
    await db.commit()  # commit trace first — FK in replays references it

    # 4. Replay row holds the diff metadata for this branch.
    db.add(
        Replay(
            id=replay_id,
            original_trace_id=original.id,
            new_trace_id=new_trace_id,
            modifications={
                "branch_span_id": str(branch_span.id),
                "new_output": payload.new_output,
            },
        )
    )
    await db.commit()

    logger.info(
        "branch requested",
        replay_id=str(replay_id),
        original_trace_id=str(original.id),
        new_trace_id=str(new_trace_id),
        branch_span_id=str(branch_span.id),
    )

    background_tasks.add_task(
        _run_branch,
        replay_id=replay_id,
        new_trace_id=new_trace_id,
        original_trace_id=original.id,
        branch_span_id=branch_span.id,
        new_output=payload.new_output,
        project_id=api_key.project_id,
    )

    return BranchCreated(replay_id=replay_id, new_trace_id=new_trace_id)

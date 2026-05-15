import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_api_key
from app.db import get_db
from app.models import ApiKey, Span, Trace
from app.schemas import (
    TraceCreated,
    TraceDetail,
    TraceIn,
    TraceList,
    TraceListItem,
)

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

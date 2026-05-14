from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.db import get_db
from app.models import ApiKey, Span, Trace
from app.schemas import TraceCreated, TraceIn

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
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to persist trace: {exc.__class__.__name__}",
        ) from exc

    return TraceCreated(trace_id=payload.id, span_count=len(payload.spans))

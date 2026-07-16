"""Suites & suite runs — v2.2 Prompt CI/CD.

A suite is a named collection of traces (stored by reference, B8.1). Running a suite
against a new prompt:
  1. creates a suite_run row (status='running') and returns its id immediately,
  2. kicks a BackgroundTask that, per trace, REPLAYS it with the new prompt (reusing
     the v2.1 replay engine) and JUDGES the new output vs the original (JudgeService),
  3. accumulates pass/regress/improve counts + per-trace verdicts into the row.

Async by design (A5): a 100-trace run takes minutes and can't fit in one HTTP request,
so the caller polls GET /v1/suite_runs/{id}.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_api_key
from app.db import SessionLocal, get_db
from app.models import ApiKey, Replay, Span, Suite, SuiteRun, SuiteTrace, Trace
from app.routers.replays import _run_replay
from app.schemas import (
    SuiteCreated,
    SuiteIn,
    SuiteOut,
    SuiteRunCreated,
    SuiteRunIn,
    SuiteRunOut,
)
from app.services import judge as judge_service

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/suites", tags=["suites"])
runs_router = APIRouter(prefix="/v1/suite_runs", tags=["suites"])


# ── background task: replay each trace + judge ─────────────────────────────


def _judge_output(spans: list[Span], trace_output: Any) -> Any:
    """Pick the output the judge should compare.

    Server-side replay only re-executes LLM spans, so it can never reproduce a
    trace's *post-LLM* Python (e.g. a `json.loads` in the agent). Comparing
    trace-level outputs would therefore flag a spurious "regression" for any
    agent that post-processes the model's text — even when the prompt is
    unchanged. The apples-to-apples signal the prompt actually controls is the
    final LLM span's output, which both the original and the replay store as
    ``{"content": ...}``. Fall back to the trace output when a trace has no LLM
    span (nothing the prompt could have changed).
    """
    llm_spans = [s for s in spans if s.type == "llm"]
    if not llm_spans:
        return trace_output
    return max(llm_spans, key=lambda s: s.started_at).output


async def _run_suite(
    suite_run_id: uuid.UUID,
    suite_id: uuid.UUID,
    prompt_override: str | None,
    model_override: str | None,
    rubric: str | None,
    judge_backend: str | None,
    project_id: uuid.UUID,
) -> None:
    """BackgroundTask: for each trace in the suite, replay with the new prompt then
    judge new-vs-original. Writes counts + per-trace results back to the suite_run."""
    results: list[dict[str, Any]] = []
    passed = regressed = improved = errored = 0

    async with SessionLocal() as db:
        trace_ids = (
            await db.execute(
                select(SuiteTrace.trace_id).where(SuiteTrace.suite_id == suite_id)
            )
        ).scalars().all()

    for original_trace_id in trace_ids:
        try:
            async with SessionLocal() as db:
                original = (
                    await db.execute(
                        select(Trace)
                        .where(Trace.id == original_trace_id)
                        .options(selectinload(Trace.spans))
                    )
                ).scalar_one_or_none()
                if original is None:
                    raise RuntimeError("trace not found")

                # Placeholder trace + replay row (mirrors create_replay; FK order matters).
                new_trace_id = uuid.uuid4()
                replay_id = uuid.uuid4()
                now = datetime.now(timezone.utc)
                db.add(
                    Trace(
                        id=new_trace_id,
                        project_id=project_id,
                        name=f"{original.name or 'trace'} (suite replay)",
                        status="running",
                        input=original.input,
                        is_replay=True,
                        replay_of_trace_id=original.id,
                        replay_mode="server",
                        started_at=now,
                    )
                )
                await db.commit()
                db.add(
                    Replay(
                        id=replay_id,
                        original_trace_id=original.id,
                        new_trace_id=new_trace_id,
                        modifications={
                            "prompt_override": prompt_override,
                            "model_override": model_override,
                            "suite_run_id": str(suite_run_id),
                        },
                    )
                )
                await db.commit()
                original_input = original.input
                # Compare the LLM output the prompt controls, not the trace-level
                # output (which server replay can't reproduce). See _judge_output.
                original_output = _judge_output(original.spans, original.output)

            # Reuse the v2.1 replay engine (opens its own session, updates the trace).
            await _run_replay(
                replay_id=replay_id,
                new_trace_id=new_trace_id,
                original_trace_id=original_trace_id,
                prompt_override=prompt_override,
                model_override=model_override,
                project_id=project_id,
            )

            async with SessionLocal() as db:
                new_trace = (
                    await db.execute(
                        select(Trace)
                        .where(Trace.id == new_trace_id)
                        .options(selectinload(Trace.spans))
                    )
                ).scalar_one_or_none()
                new_output = (
                    _judge_output(new_trace.spans, new_trace.output)
                    if new_trace
                    else None
                )

            verdict = await judge_service.judge(
                original_input=original_input,
                original_output=original_output,
                new_output=new_output,
                rubric=rubric,
                backend=judge_backend,
            )

            if verdict.label == "regressed":
                regressed += 1
            else:  # 'equivalent' or 'improved' both count as passed
                passed += 1
                if verdict.label == "improved":
                    improved += 1

            results.append(
                {
                    "trace_id": str(original_trace_id),
                    "new_trace_id": str(new_trace_id),
                    "verdict": verdict.label,
                    "score_source": verdict.score_source,
                    "reasoning": verdict.reasoning,
                    "confidence": verdict.confidence,
                }
            )
        except Exception as exc:  # noqa: BLE001 — one bad trace shouldn't kill the run
            errored += 1
            results.append({"trace_id": str(original_trace_id), "error": str(exc)})
            logger.warning(
                "suite trace failed", suite_run_id=str(suite_run_id),
                trace_id=str(original_trace_id), error=str(exc),
            )

    async with SessionLocal() as db:
        run = (
            await db.execute(select(SuiteRun).where(SuiteRun.id == suite_run_id))
        ).scalar_one_or_none()
        if run is not None:
            run.status = "done"
            run.total = len(trace_ids)
            run.passed = passed
            run.regressed = regressed
            run.improved = improved
            run.errored = errored
            run.results = results
            run.ended_at = datetime.now(timezone.utc)
            await db.commit()
    logger.info(
        "suite run complete", suite_run_id=str(suite_run_id),
        total=len(trace_ids), passed=passed, regressed=regressed, errored=errored,
    )


# ── suite CRUD ─────────────────────────────────────────────────────────────


@router.post("", response_model=SuiteCreated, status_code=status.HTTP_201_CREATED)
async def create_suite(
    payload: SuiteIn,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> SuiteCreated:
    # Every trace must exist and belong to this project.
    if payload.trace_ids:
        found = (
            await db.execute(
                select(Trace.id).where(
                    Trace.id.in_(payload.trace_ids),
                    Trace.project_id == api_key.project_id,
                )
            )
        ).scalars().all()
        missing = set(payload.trace_ids) - set(found)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"traces not found in this project: {sorted(str(m) for m in missing)}",
            )

    suite_id = uuid.uuid4()
    db.add(
        Suite(
            id=suite_id,
            project_id=api_key.project_id,
            name=payload.name,
            judge_rubric=payload.judge_rubric,
        )
    )
    await db.commit()
    # De-dup trace_ids so the composite PK never collides.
    for trace_id in dict.fromkeys(payload.trace_ids):
        db.add(SuiteTrace(suite_id=suite_id, trace_id=trace_id))
    await db.commit()
    return SuiteCreated(suite_id=suite_id)


@router.get("", response_model=list[SuiteOut])
async def list_suites(
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[SuiteOut]:
    rows = (
        await db.execute(
            select(
                Suite, func.count(SuiteTrace.trace_id)
            )
            .outerjoin(SuiteTrace, SuiteTrace.suite_id == Suite.id)
            .where(Suite.project_id == api_key.project_id)
            .group_by(Suite.id)
            .order_by(Suite.created_at.desc())
        )
    ).all()
    return [
        SuiteOut(
            id=s.id,
            name=s.name,
            judge_rubric=s.judge_rubric,
            trace_count=count,
            created_at=s.created_at,
        )
        for s, count in rows
    ]


@router.get("/{suite_id}", response_model=SuiteOut)
async def get_suite(
    suite_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> SuiteOut:
    suite = (
        await db.execute(
            select(Suite).where(
                Suite.id == suite_id, Suite.project_id == api_key.project_id
            )
        )
    ).scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    count = (
        await db.execute(
            select(func.count(SuiteTrace.trace_id)).where(SuiteTrace.suite_id == suite_id)
        )
    ).scalar_one()
    return SuiteOut(
        id=suite.id,
        name=suite.name,
        judge_rubric=suite.judge_rubric,
        trace_count=count,
        created_at=suite.created_at,
    )


@router.post(
    "/{suite_id}/run",
    response_model=SuiteRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_suite(
    suite_id: uuid.UUID,
    payload: SuiteRunIn,
    background_tasks: BackgroundTasks,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> SuiteRunCreated:
    suite = (
        await db.execute(
            select(Suite).where(
                Suite.id == suite_id, Suite.project_id == api_key.project_id
            )
        )
    ).scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")

    backend = payload.judge_backend or judge_service.settings.judge_backend
    suite_run_id = uuid.uuid4()
    db.add(
        SuiteRun(
            id=suite_run_id,
            suite_id=suite_id,
            status="running",
            prompt_override=payload.prompt_override,
            model_override=payload.model_override,
            judge_backend=backend,
        )
    )
    await db.commit()

    background_tasks.add_task(
        _run_suite,
        suite_run_id=suite_run_id,
        suite_id=suite_id,
        prompt_override=payload.prompt_override,
        model_override=payload.model_override,
        rubric=suite.judge_rubric,  # None → judge uses the global default (B8.3)
        judge_backend=backend,
        project_id=api_key.project_id,
    )
    return SuiteRunCreated(suite_run_id=suite_run_id)


# ── suite run polling ──────────────────────────────────────────────────────


@runs_router.get("/{suite_run_id}", response_model=SuiteRunOut)
async def get_suite_run(
    suite_run_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> SuiteRun:
    run = (
        await db.execute(
            select(SuiteRun)
            .join(Suite, Suite.id == SuiteRun.suite_id)
            .where(
                SuiteRun.id == suite_run_id,
                Suite.project_id == api_key.project_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Suite run not found")
    return run

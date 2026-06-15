from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth import require_api_key
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import ApiKey, Replay, Span, Trace
from app.schemas import ReplayCreated, ReplayDetail, ReplayIn

from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/replays", tags=["replays"])


# ── Cost table (input, output) per 1M tokens ──────────────────────────────
_COST_PER_M: dict[str, tuple[float, float]] = {
    "gpt-4o":              (2.50,  10.00),
    "gpt-4o-mini":         (0.15,   0.60),
    "gpt-4-turbo":        (10.00,  30.00),
    "gpt-3.5-turbo":       (0.50,   1.50),
    "claude-opus-4":      (15.00,  75.00),
    "claude-sonnet-4":     (3.00,  15.00),
    "claude-haiku-4":      (0.80,   4.00),
    "claude-3-5-sonnet":   (3.00,  15.00),
    "claude-3-5-haiku":    (0.80,   4.00),
    "claude-3-opus":      (15.00,  75.00),
    "claude-3-haiku":      (0.25,   1.25),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    # Sort longest prefix first so "gpt-4o-mini" matches before "gpt-4o".
    for prefix, (in_rate, out_rate) in sorted(_COST_PER_M.items(), key=lambda x: -len(x[0])):
        if model.startswith(prefix):
            val = (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000
            return Decimal(str(round(val, 6)))
    return None


def _apply_prompt_override(messages: list[dict[str, Any]], override: str) -> list[dict[str, Any]]:
    """Replace the first system message, or prepend one if none exists."""
    result = [dict(m) for m in messages]
    for i, m in enumerate(result):
        if m.get("role") == "system":
            result[i] = {**m, "content": override}
            return result
    return [{"role": "system", "content": override}] + result


_GROQ_PREFIXES = ("llama", "gemma", "mixtral", "whisper")

def _detect_provider(model: str, fallback: str | None = None) -> str:
    """Infer the API provider from a model name."""
    if model.startswith("claude"):
        return "anthropic"
    if any(model.startswith(p) for p in _GROQ_PREFIXES):
        return "groq"
    if fallback in ("anthropic", "groq"):
        return fallback
    return "openai"


def _effective_policy(span_type: str, replay_policy: str | None) -> str:
    """Decide how a span *after the branch point* should be handled on replay.

    Returns 'live' (re-execute / use fresh value) or 'dry_run' (don't touch the
    real world — emit a ghost span).

    Rules (from docs/design-replay-side-effects.md):
    - tool  → honour the SDK annotation in `replay_policy`; default 'dry_run'
              because a write re-run would duplicate side effects.
    - llm / retrieval / function → 'live' by nature (stateless call, a read, or
              pure computation — never an unsafe write).

    Note: only `llm` spans are actually re-executed *by the server* (it has the
    provider keys). For non-llm 'live' spans the server can't run user code, so
    the engine falls back to passing through the stored output — but the policy
    itself is still 'live', which is the honest classification.
    """
    if span_type == "tool":
        return replay_policy or "dry_run"
    return "live"


async def _call_openai_compat(
    base_url: str, api_key: str, model: str, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Call any OpenAI-compatible endpoint (OpenAI, Groq, etc.)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages},
        )
        if not resp.is_success:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:300]}")
        return resp.json()


async def _call_openai(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured in server .env")
    return await _call_openai_compat(
        "https://api.openai.com/v1", settings.openai_api_key, model, messages
    )


async def _call_groq(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured in server .env")
    return await _call_openai_compat(
        "https://api.groq.com/openai/v1", settings.groq_api_key, model, messages
    )


async def _call_anthropic(
    model: str, messages: list[dict[str, Any]], system: str | None
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured in server .env")
    # Anthropic's messages API excludes system role from the messages array
    non_system = [m for m in messages if m.get("role") != "system"]
    # Extract system from messages if not provided separately
    if system is None:
        for m in messages:
            if m.get("role") == "system":
                system = str(m.get("content", ""))
                break
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": non_system,
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if not resp.is_success:
            raise RuntimeError(f"Anthropic {resp.status_code}: {resp.text[:300]}")
        return resp.json()


async def _run_replay(
    replay_id: uuid.UUID,
    new_trace_id: uuid.UUID,
    original_trace_id: uuid.UUID,
    prompt_override: str | None,
    model_override: str | None,
    project_id: uuid.UUID,
) -> None:
    """BackgroundTask: re-execute LLM spans, copy the rest, update trace."""
    started_at = datetime.now(timezone.utc)

    async with SessionLocal() as db:
        # Load original trace + spans
        stmt = (
            select(Trace)
            .where(Trace.id == original_trace_id)
            .options(selectinload(Trace.spans))
        )
        result = await db.execute(stmt)
        original = result.scalar_one_or_none()

        if original is None:
            logger.error("original trace not found", replay_id=str(replay_id), original_trace_id=str(original_trace_id))
            return

        new_spans: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = Decimal("0")
        replay_status = "success"
        trace_error: dict[str, Any] | None = None
        final_output: dict[str, Any] | None = None

        # Sort spans by started_at so parent spans are created before children
        sorted_spans = sorted(original.spans, key=lambda s: s.started_at)
        # Map old span IDs → new span IDs (for re-linking parent_span_id)
        id_map: dict[uuid.UUID, uuid.UUID] = {}

        for orig_span in sorted_spans:
            new_span_id = uuid.uuid4()
            id_map[orig_span.id] = new_span_id
            new_parent_id = id_map.get(orig_span.parent_span_id) if orig_span.parent_span_id else None

            span_started = datetime.now(timezone.utc)

            if orig_span.type == "llm" and orig_span.input:
                # Re-execute this LLM span with overrides
                messages: list[dict[str, Any]] = orig_span.input.get("messages", [])
                system_prompt: str | None = orig_span.input.get("system")  # Anthropic field

                if prompt_override:
                    if system_prompt is not None:
                        # Anthropic-style: system is a separate field
                        system_prompt = prompt_override
                    else:
                        messages = _apply_prompt_override(messages, prompt_override)

                model = model_override or orig_span.model or "claude-haiku-4-5-20251001"
                provider = _detect_provider(model, fallback=orig_span.provider)

                try:
                    span_ended = datetime.now(timezone.utc)
                    if provider == "anthropic":
                        raw = await _call_anthropic(model, messages, system_prompt)
                        prompt_tokens = raw.get("usage", {}).get("input_tokens", 0)
                        completion_tokens = raw.get("usage", {}).get("output_tokens", 0)
                        content_blocks = raw.get("content", [])
                        content_text = content_blocks[0].get("text", "") if content_blocks else ""
                        provider = "anthropic"
                    elif provider == "groq":
                        raw = await _call_groq(model, messages)
                        usage = raw.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                        choices = raw.get("choices", [])
                        content_text = choices[0]["message"]["content"] if choices else ""
                        provider = "groq"
                    else:
                        raw = await _call_openai(model, messages)
                        usage = raw.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                        choices = raw.get("choices", [])
                        content_text = choices[0]["message"]["content"] if choices else ""
                        provider = "openai"

                    span_ended = datetime.now(timezone.utc)
                    tok = prompt_tokens + completion_tokens
                    cost = _estimate_cost(model, prompt_tokens, completion_tokens)
                    total_tokens += tok
                    if cost:
                        total_cost += cost

                    new_spans.append({
                        "id": new_span_id,
                        "trace_id": new_trace_id,
                        "parent_span_id": new_parent_id,
                        "type": "llm",
                        "name": orig_span.name,
                        "input": {"messages": messages, **({"system": system_prompt} if system_prompt else {})},
                        "output": {"content": content_text},
                        "error": None,
                        "started_at": span_started,
                        "ended_at": span_ended,
                        "duration_ms": int((span_ended - span_started).total_seconds() * 1000),
                        "model": model,
                        "provider": provider,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": tok,
                        "cost_usd": cost,
                        "extra_metadata": None,
                    })
                    final_output = {"content": content_text}

                except Exception as exc:
                    logger.error("llm call failed", replay_id=str(replay_id), error=str(exc))
                    replay_status = "error"
                    trace_error = {"type": type(exc).__name__, "message": str(exc)}
                    new_spans.append({
                        "id": new_span_id,
                        "trace_id": new_trace_id,
                        "parent_span_id": new_parent_id,
                        "type": "llm",
                        "name": orig_span.name,
                        "input": orig_span.input,
                        "output": None,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "started_at": span_started,
                        "ended_at": datetime.now(timezone.utc),
                        "duration_ms": None,
                        "model": model,
                        "provider": orig_span.provider,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "total_tokens": None,
                        "cost_usd": None,
                        "extra_metadata": None,
                    })

            else:
                # Non-LLM span: copy as-is
                new_spans.append({
                    "id": new_span_id,
                    "trace_id": new_trace_id,
                    "parent_span_id": new_parent_id,
                    "type": orig_span.type,
                    "name": orig_span.name,
                    "input": orig_span.input,
                    "output": orig_span.output,
                    "error": orig_span.error,
                    "started_at": span_started,
                    "ended_at": span_started,  # copied — no real duration
                    "duration_ms": orig_span.duration_ms,
                    "model": orig_span.model,
                    "provider": orig_span.provider,
                    "prompt_tokens": orig_span.prompt_tokens,
                    "completion_tokens": orig_span.completion_tokens,
                    "total_tokens": orig_span.total_tokens,
                    "cost_usd": orig_span.cost_usd,
                    "extra_metadata": orig_span.extra_metadata,
                })

        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        # Insert new spans
        if new_spans:
            for s in new_spans:
                db.add(Span(**s))

        # Update the placeholder trace
        stmt2 = select(Trace).where(Trace.id == new_trace_id)
        result2 = await db.execute(stmt2)
        new_trace = result2.scalar_one_or_none()
        if new_trace:
            new_trace.status = replay_status
            new_trace.output = final_output
            new_trace.error = trace_error
            new_trace.ended_at = ended_at
            new_trace.duration_ms = duration_ms
            new_trace.total_tokens = total_tokens or None
            new_trace.total_cost_usd = total_cost if total_cost else None

        # Update Replay diff_summary
        stmt3 = select(Replay).where(Replay.id == replay_id)
        result3 = await db.execute(stmt3)
        replay_row = result3.scalar_one_or_none()
        if replay_row:
            replay_row.new_trace_id = new_trace_id
            orig_tok = original.total_tokens or 0
            replay_row.diff_summary = {
                "token_delta": total_tokens - orig_tok,
                "latency_delta_ms": duration_ms - (original.duration_ms or 0),
                "status": replay_status,
            }

        await db.commit()
        logger.info("replay complete", replay_id=str(replay_id), status=replay_status)


async def _invoke_llm(
    model: str,
    messages: list[dict[str, Any]],
    system_prompt: str | None,
    fallback_provider: str | None,
) -> tuple[str, int, int, str]:
    """Call the right provider for a model. Returns (content, prompt_tokens,
    completion_tokens, provider). Shared by the branch engine."""
    provider = _detect_provider(model, fallback=fallback_provider)
    if provider == "anthropic":
        raw = await _call_anthropic(model, messages, system_prompt)
        usage = raw.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        blocks = raw.get("content", [])
        content = blocks[0].get("text", "") if blocks else ""
    elif provider == "groq":
        raw = await _call_groq(model, messages)
        usage = raw.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        choices = raw.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
    else:
        raw = await _call_openai(model, messages)
        usage = raw.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        choices = raw.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
    return content, prompt_tokens, completion_tokens, provider


def _copy_span_dict(
    orig: Span,
    new_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
    new_trace_id: uuid.UUID,
    *,
    output: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a span row that copies the original verbatim. Used for frozen
    (before-branch) spans, the branch span (with `output` overridden), and
    live-tool passthrough. Keeps stored tokens/cost so the diff stays honest."""
    started = datetime.now(timezone.utc)
    return {
        "id": new_id,
        "trace_id": new_trace_id,
        "parent_span_id": new_parent_id,
        "type": orig.type,
        "name": orig.name,
        "input": orig.input,
        "output": orig.output if output is None else output,
        "error": orig.error,
        "started_at": started,
        "ended_at": started,
        "duration_ms": orig.duration_ms,
        "model": orig.model,
        "provider": orig.provider,
        "prompt_tokens": orig.prompt_tokens,
        "completion_tokens": orig.completion_tokens,
        "total_tokens": orig.total_tokens,
        "cost_usd": orig.cost_usd,
        "extra_metadata": extra_metadata if extra_metadata is not None else orig.extra_metadata,
    }


async def _run_branch(
    replay_id: uuid.UUID,
    new_trace_id: uuid.UUID,
    original_trace_id: uuid.UUID,
    branch_span_id: uuid.UUID,
    new_output: dict[str, Any],
    project_id: uuid.UUID,
) -> None:
    """BackgroundTask: deterministic branch replay.

    Freeze every span before the branch point (use stored output), apply the
    user's edited output AT the branch point, and re-execute everything after it
    honouring the side-effect policy:
      - llm  → re-run live via the provider
      - write tool (dry_run) → ghost span, no real call
      - live tool/read       → pass through stored output (server can't run
                               user code — see docs/design-replay-side-effects.md)
    """
    started_at = datetime.now(timezone.utc)

    async with SessionLocal() as db:
        stmt = (
            select(Trace)
            .where(Trace.id == original_trace_id)
            .options(selectinload(Trace.spans))
        )
        result = await db.execute(stmt)
        original = result.scalar_one_or_none()
        if original is None:
            logger.error("branch: original trace not found",
                         replay_id=str(replay_id), original_trace_id=str(original_trace_id))
            return

        sorted_spans = sorted(original.spans, key=lambda s: s.started_at)
        branch_index = next(
            (i for i, s in enumerate(sorted_spans) if s.id == branch_span_id), None
        )
        if branch_index is None:
            logger.error("branch: branch span not found",
                         replay_id=str(replay_id), branch_span_id=str(branch_span_id))
            await _finalize_branch_error(
                db, new_trace_id, replay_id, original, started_at,
                {"type": "BranchSpanNotFound", "message": f"span {branch_span_id} not in trace"},
            )
            return

        new_spans: list[dict[str, Any]] = []
        id_map: dict[uuid.UUID, uuid.UUID] = {}
        total_tokens = 0
        total_cost = Decimal("0")
        branch_status = "success"
        trace_error: dict[str, Any] | None = None
        final_output: dict[str, Any] | None = None

        for i, orig in enumerate(sorted_spans):
            new_id = uuid.uuid4()
            id_map[orig.id] = new_id
            new_parent = id_map.get(orig.parent_span_id) if orig.parent_span_id else None

            if i < branch_index:
                # ── Before the branch: frozen (stored output) ──
                d = _copy_span_dict(orig, new_id, new_parent, new_trace_id)

            elif i == branch_index:
                # ── The branch point: use the user's edited output ──
                d = _copy_span_dict(
                    orig, new_id, new_parent, new_trace_id,
                    output=new_output,
                    extra_metadata={**(orig.extra_metadata or {}), "branch_point": True},
                )

            elif orig.type == "llm" and orig.input:
                # ── After the branch, llm: re-execute live ──
                messages = orig.input.get("messages", [])
                system_prompt = orig.input.get("system")
                model = orig.model or "claude-haiku-4-5-20251001"
                span_started = datetime.now(timezone.utc)
                try:
                    content, ptok, ctok, provider = await _invoke_llm(
                        model, messages, system_prompt, orig.provider
                    )
                    span_ended = datetime.now(timezone.utc)
                    tok = ptok + ctok
                    cost = _estimate_cost(model, ptok, ctok)
                    d = {
                        "id": new_id, "trace_id": new_trace_id, "parent_span_id": new_parent,
                        "type": "llm", "name": orig.name,
                        "input": {"messages": messages, **({"system": system_prompt} if system_prompt else {})},
                        "output": {"content": content}, "error": None,
                        "started_at": span_started, "ended_at": span_ended,
                        "duration_ms": int((span_ended - span_started).total_seconds() * 1000),
                        "model": model, "provider": provider,
                        "prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": tok,
                        "cost_usd": cost, "extra_metadata": None,
                    }
                except Exception as exc:
                    logger.error("branch: llm call failed", replay_id=str(replay_id), error=str(exc))
                    branch_status = "error"
                    trace_error = {"type": type(exc).__name__, "message": str(exc)}
                    d = {
                        "id": new_id, "trace_id": new_trace_id, "parent_span_id": new_parent,
                        "type": "llm", "name": orig.name, "input": orig.input, "output": None,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "started_at": span_started, "ended_at": datetime.now(timezone.utc),
                        "duration_ms": None, "model": model, "provider": orig.provider,
                        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                        "cost_usd": None, "extra_metadata": None,
                    }

            else:
                # ── After the branch, non-llm: honour the side-effect policy ──
                policy = _effective_policy(orig.type, orig.replay_policy)
                if policy == "dry_run":
                    # Ghost span — show what WOULD have happened, no real call.
                    started = datetime.now(timezone.utc)
                    d = {
                        "id": new_id, "trace_id": new_trace_id, "parent_span_id": new_parent,
                        "type": orig.type, "name": orig.name, "input": orig.input,
                        "output": {"would_have": orig.input}, "error": None,
                        "started_at": started, "ended_at": started, "duration_ms": 0,
                        "model": orig.model, "provider": orig.provider,
                        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                        "cost_usd": None,
                        "extra_metadata": {**(orig.extra_metadata or {}), "dry_run": True},
                    }
                else:
                    # Live, but the server can't run user code → passthrough (Option A).
                    d = _copy_span_dict(
                        orig, new_id, new_parent, new_trace_id,
                        extra_metadata={**(orig.extra_metadata or {}), "replay": "stored_passthrough"},
                    )

            new_spans.append(d)
            final_output = d["output"]

        # Sum tokens/cost across every span once — frozen, branch, re-run, and
        # passthrough spans all carry their own values; ghosts carry None.
        for d in new_spans:
            if d.get("total_tokens"):
                total_tokens += d["total_tokens"]
            if d.get("cost_usd"):
                total_cost += d["cost_usd"]

        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        for s in new_spans:
            db.add(Span(**s))

        new_trace = (await db.execute(select(Trace).where(Trace.id == new_trace_id))).scalar_one_or_none()
        if new_trace:
            new_trace.status = branch_status
            new_trace.output = final_output
            new_trace.error = trace_error
            new_trace.ended_at = ended_at
            new_trace.duration_ms = duration_ms
            new_trace.total_tokens = total_tokens or None
            new_trace.total_cost_usd = total_cost if total_cost else None

        replay_row = (await db.execute(select(Replay).where(Replay.id == replay_id))).scalar_one_or_none()
        if replay_row:
            replay_row.new_trace_id = new_trace_id
            replay_row.diff_summary = {
                "token_delta": total_tokens - (original.total_tokens or 0),
                "latency_delta_ms": duration_ms - (original.duration_ms or 0),
                "status": branch_status,
                "branch_span_id": str(branch_span_id),
            }

        await db.commit()
        logger.info("branch complete", replay_id=str(replay_id), status=branch_status)


async def _finalize_branch_error(
    db: AsyncSession,
    new_trace_id: uuid.UUID,
    replay_id: uuid.UUID,
    original: Trace,
    started_at: datetime,
    error: dict[str, Any],
) -> None:
    """Mark the placeholder trace + replay row as errored (no spans produced)."""
    new_trace = (await db.execute(select(Trace).where(Trace.id == new_trace_id))).scalar_one_or_none()
    if new_trace:
        new_trace.status = "error"
        new_trace.error = error
        new_trace.ended_at = datetime.now(timezone.utc)
    replay_row = (await db.execute(select(Replay).where(Replay.id == replay_id))).scalar_one_or_none()
    if replay_row:
        replay_row.diff_summary = {"status": "error", "error": error}
    await db.commit()


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("", response_model=ReplayCreated, status_code=status.HTTP_201_CREATED)
async def create_replay(
    payload: ReplayIn,
    background_tasks: BackgroundTasks,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> ReplayCreated:
    # Verify original trace exists and belongs to this project
    stmt = select(Trace).where(
        Trace.id == payload.original_trace_id,
        Trace.project_id == api_key.project_id,
    )
    result = await db.execute(stmt)
    original = result.scalar_one_or_none()
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original trace not found",
        )

    now = datetime.now(timezone.utc)
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    # Create placeholder trace (status=running)
    new_trace = Trace(
        id=new_trace_id,
        project_id=api_key.project_id,
        name=f"{original.name or 'trace'} (replay)",
        status="running",
        input=original.input,
        is_replay=True,
        replay_of_trace_id=original.id,
        started_at=now,
    )
    db.add(new_trace)
    await db.commit()  # commit trace first — FK in replays references it

    # Create Replay record (new_trace_id now exists in DB)
    replay_row = Replay(
        id=replay_id,
        original_trace_id=original.id,
        new_trace_id=new_trace_id,
        modifications={
            "prompt_override": payload.prompt_override,
            "model_override": payload.model_override,
        },
    )
    db.add(replay_row)
    await db.commit()

    background_tasks.add_task(
        _run_replay,
        replay_id=replay_id,
        new_trace_id=new_trace_id,
        original_trace_id=original.id,
        prompt_override=payload.prompt_override,
        model_override=payload.model_override,
        project_id=api_key.project_id,
    )

    return ReplayCreated(replay_id=replay_id, new_trace_id=new_trace_id)


@router.get("/{replay_id}", response_model=ReplayDetail)
async def get_replay(
    replay_id: uuid.UUID,
    api_key: ApiKey = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> Replay:
    stmt = select(Replay).where(Replay.id == replay_id)
    result = await db.execute(stmt)
    replay = result.scalar_one_or_none()
    if replay is None:
        raise HTTPException(status_code=404, detail="Replay not found")
    return replay

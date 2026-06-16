from __future__ import annotations

import functools
import traceback
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

import loupe._replay as _replay
from loupe.client import LoupeClient
from loupe.models import SpanPayload, TracePayload

F = TypeVar("F", bound=Callable[..., Any])

# Module-level state — set by loupe.init()
_client: LoupeClient | None = None

# Per-trace context — stored in a ContextVar so it's async-safe and
# works correctly when traces are nested or run concurrently.
@dataclass
class _TraceContext:
    trace_id: uuid.UUID
    spans: list[SpanPayload] = field(default_factory=list)
    current_span_id: uuid.UUID | None = None  # tracks parent for nested spans

_current_trace: ContextVar[_TraceContext | None] = ContextVar(
    "_current_trace", default=None
)


def init(api_key: str, host: str = "http://localhost:8000") -> None:
    """Call once at startup before using @trace or span()."""
    global _client
    _client = LoupeClient(api_key=api_key, host=host)


def trace(_fn: F | None = None, *, name: str | None = None) -> Any:
    """
    Decorator that records a function call as a Loupe trace.

    Usage:
        @loupe.trace
        def run_agent(query): ...

        @loupe.trace(name="my_agent")
        def run_agent(query): ...
    """
    def decorator(fn: F) -> F:
        trace_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _client is None:
                return fn(*args, **kwargs)

            started_at = datetime.now(timezone.utc)
            ctx = _TraceContext(trace_id=uuid.uuid4())
            token = _current_trace.set(ctx)

            # If this run is a replay, record where the new trace branched from.
            rplan = _replay.get_plan()
            if rplan is not None:
                rplan.new_trace_id = ctx.trace_id

            result = None
            error_info: dict[str, Any] | None = None
            status = "success"

            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                status = "error"
                error_info = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
                raise
            finally:
                _current_trace.reset(token)
                ended_at = datetime.now(timezone.utc)
                duration_ms = int((ended_at - started_at).total_seconds() * 1000)

                payload = TracePayload(
                    id=ctx.trace_id,
                    name=f"{trace_name} (branch)" if rplan is not None else trace_name,
                    status=status,
                    input=_safe_serialize(args, kwargs),
                    output=_safe_serialize(result),
                    error=error_info,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                    is_replay=rplan is not None,
                    branched_from_trace_id=rplan.branched_from_trace_id if rplan else None,
                    branched_from_span_id=rplan.branched_from_span_id if rplan else None,
                    spans=ctx.spans,
                )
                _client.enqueue(payload)

        return wrapper  # type: ignore[return-value]

    if _fn is not None:
        return decorator(_fn)
    return decorator


class _SpanHandle:
    """
    Returned by span(). Supports two usage patterns:

    As a context manager (manual input/output):
        with loupe.span("search", type="tool") as s:
            s.output = {"count": 3}

    As a decorator (auto-captures args and return value):
        @loupe.span(type="tool", name="search")
        def search(query: str) -> list: ...
    """

    def __init__(
        self,
        name: str | None,
        type: str,  # noqa: A002
        input: dict[str, Any] | None,  # noqa: A002
        metadata: dict[str, Any] | None,
    ) -> None:
        self._name = name
        self._type = type
        self._input = input
        self._metadata = metadata
        # state used by the context-manager path
        self._span: SpanPayload | None = None
        self._prev_parent: uuid.UUID | None = None
        self._ctx: _TraceContext | None = None

    # ── decorator protocol ──────────────────────────────────────────────────

    def __call__(self, fn: F) -> F:  # type: ignore[override]
        span_name = self._name or fn.__name__
        span_type = self._type
        span_metadata = self._metadata

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = _current_trace.get()
            if ctx is None or _client is None:
                return fn(*args, **kwargs)

            span_id = uuid.uuid4()
            parent_id = ctx.current_span_id
            started_at = datetime.now(timezone.utc)

            s = SpanPayload(
                id=span_id,
                parent_span_id=parent_id,
                type=span_type,
                name=span_name,
                input=_safe_serialize(args, kwargs),
                metadata=span_metadata,
                started_at=started_at,
            )
            ctx.current_span_id = span_id

            mode, frozen = _replay.begin_span()
            try:
                if mode in (_replay.FREEZE, _replay.EDIT):
                    # Don't execute — replay the stored / edited output. Skipping
                    # the body is what keeps before-branch spans (and writes) safe.
                    s.output = frozen
                    s.metadata = _mark_replay(s.metadata, mode)
                    return _reconstruct_return(frozen)
                result = fn(*args, **kwargs)
                s.output = _safe_serialize(result)
                return result
            except Exception as exc:
                s.error = {"type": exc.__class__.__name__, "message": str(exc)}
                raise
            finally:
                _replay.end_span()
                ctx.current_span_id = parent_id
                s.ended_at = datetime.now(timezone.utc)
                s.duration_ms = int((s.ended_at - started_at).total_seconds() * 1000)
                ctx.spans.append(s)

        return wrapper  # type: ignore[return-value]

    # ── context manager protocol ────────────────────────────────────────────

    def __enter__(self) -> SpanPayload:
        ctx = _current_trace.get()
        if ctx is None or _client is None:
            dummy = SpanPayload(
                id=uuid.uuid4(),
                type=self._type,
                name=self._name or "span",
                started_at=datetime.now(timezone.utc),
            )
            self._span = dummy
            return dummy

        span_id = uuid.uuid4()
        self._prev_parent = ctx.current_span_id
        self._ctx = ctx

        s = SpanPayload(
            id=span_id,
            parent_span_id=ctx.current_span_id,
            type=self._type,
            name=self._name or "span",
            input=self._input,
            metadata=self._metadata,
            started_at=datetime.now(timezone.utc),
        )
        ctx.current_span_id = span_id
        self._span = s
        # Classify this span for replay. The body still runs (a `with` block
        # can't be skipped), but the integration inside it (e.g. the LLM call)
        # reads current_frozen_output() to short-circuit, and __exit__ pins the
        # recorded output to the frozen/edited value.
        self._replay_mode, _ = _replay.begin_span()
        return s

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        s = self._span
        if s is None:
            return
        decision = _replay.end_span()
        if exc_val is not None:
            s.error = {"type": exc_type.__name__, "message": str(exc_val)}
        ctx = self._ctx
        if ctx is not None:
            if decision is not None:
                mode, output = decision
                if mode in (_replay.FREEZE, _replay.EDIT):
                    s.output = output
                    s.metadata = _mark_replay(s.metadata, mode)
            ctx.current_span_id = self._prev_parent
            s.ended_at = datetime.now(timezone.utc)
            s.duration_ms = int((s.ended_at - s.started_at).total_seconds() * 1000)
            ctx.spans.append(s)


def span(
    name: str | None = None,
    *,
    type: str = "function",  # noqa: A002
    input: dict[str, Any] | None = None,  # noqa: A002
    metadata: dict[str, Any] | None = None,
) -> _SpanHandle:
    """
    Records a sub-span within the current trace.

    As a decorator (auto-captures args + return value):
        @loupe.span(type="tool", name="search_movies")
        def search_movies(query: str) -> list: ...

    As a context manager (set output manually):
        with loupe.span("search_movies", type="tool") as s:
            results = db.search(query)
            s.output = {"count": len(results)}
    """
    return _SpanHandle(name=name, type=type, input=input, metadata=metadata)


def replay(
    agent_fn: Callable[..., Any],
    *,
    trace_id: str,
    branch_span_id: str,
    new_output: dict[str, Any],
) -> uuid.UUID:
    """Re-run a traced agent from a branch point with an edited span output.

    Unlike the server-side branch, this runs IN YOUR PROCESS, so your real tool
    functions execute and the edit propagates downstream. Spans before the branch
    are frozen (stored outputs), the branch span uses `new_output`, and everything
    after runs live.

        new_id = loupe.replay(my_agent, trace_id="...", branch_span_id="...",
                              new_output={"content": "..."})

    Returns the id of the new (branched) trace.
    """
    if _client is None:
        raise RuntimeError("call loupe.init() before loupe.replay()")

    original = _client.fetch_trace(trace_id)
    spans = sorted(original.get("spans", []), key=lambda s: s["started_at"])
    branch_index = next(
        (i for i, s in enumerate(spans) if s["id"] == str(branch_span_id)), None
    )
    if branch_index is None:
        raise ValueError(f"span {branch_span_id} not found in trace {trace_id}")

    plan = _replay._ReplayPlan(
        stored_outputs=[s.get("output") for s in spans],
        branch_index=branch_index,
        new_output=new_output,
        branched_from_trace_id=uuid.UUID(str(trace_id)),
        branched_from_span_id=uuid.UUID(str(branch_span_id)),
    )

    inp = original.get("input") or {}
    args = inp.get("args", [])
    kwargs = inp.get("kwargs", {})

    token = _replay.set_plan(plan)
    try:
        agent_fn(*args, **kwargs)
    finally:
        _replay.reset_plan(token)

    return plan.new_trace_id


def _mark_replay(metadata: dict[str, Any] | None, mode: str) -> dict[str, Any]:
    """Tag a replayed span so the dashboard can show branch-point / frozen badges."""
    marker = {"branch_point": True} if mode == _replay.EDIT else {"replay": "frozen"}
    return {**(metadata or {}), **marker}


def _reconstruct_return(frozen: dict[str, Any] | None) -> Any:
    """Best-effort: turn a stored span output back into a function return value.
    A scalar return was serialized as {"value": x}; unwrap it. Otherwise hand
    back the recorded dict as-is."""
    if isinstance(frozen, dict) and set(frozen.keys()) == {"value"}:
        return frozen["value"]
    return frozen


def _safe_serialize(*values: Any) -> dict[str, Any] | None:
    if not values:
        return None
    if len(values) == 1 and isinstance(values[0], dict):
        return values[0]
    if len(values) == 2:
        args, kwargs = values
        result: dict[str, Any] = {}
        if args:
            result["args"] = [_to_jsonable(a) for a in args]
        if kwargs:
            result["kwargs"] = {k: _to_jsonable(v) for k, v in kwargs.items()}
        return result or None
    return {"value": _to_jsonable(values[0])}


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(i) for i in obj]
    return str(obj)

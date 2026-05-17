from __future__ import annotations

import functools
import traceback
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

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
                    name=trace_name,
                    status=status,
                    input=_safe_serialize(args, kwargs),
                    output=_safe_serialize(result),
                    error=error_info,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                    spans=ctx.spans,
                )
                _client.enqueue(payload)

        return wrapper  # type: ignore[return-value]

    if _fn is not None:
        return decorator(_fn)
    return decorator


@contextmanager
def span(
    name: str,
    type: str = "function",  # noqa: A002
    input: dict[str, Any] | None = None,  # noqa: A002
    metadata: dict[str, Any] | None = None,
) -> Generator[SpanPayload, None, None]:
    """
    Context manager that records a sub-span within the current trace.

    Usage:
        with loupe.span("search_movies", type="tool") as s:
            results = db.search(query)
            s.output = {"count": len(results)}
    """
    ctx = _current_trace.get()
    if ctx is None or _client is None:
        # Outside a trace or Loupe not initialised — yield a dummy span.
        dummy = SpanPayload(
            id=uuid.uuid4(),
            type=type,
            name=name,
            started_at=datetime.now(timezone.utc),
        )
        yield dummy
        return

    span_id = uuid.uuid4()
    parent_id = ctx.current_span_id
    started_at = datetime.now(timezone.utc)

    s = SpanPayload(
        id=span_id,
        parent_span_id=parent_id,
        type=type,
        name=name,
        input=input,
        metadata=metadata,
        started_at=started_at,
    )

    # Set this span as the current parent so nested spans link correctly.
    ctx.current_span_id = span_id

    try:
        yield s
    except Exception as exc:
        s.error = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
        raise
    finally:
        ctx.current_span_id = parent_id  # restore previous parent
        s.ended_at = datetime.now(timezone.utc)
        s.duration_ms = int((s.ended_at - started_at).total_seconds() * 1000)
        ctx.spans.append(s)


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

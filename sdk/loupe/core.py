from __future__ import annotations

import functools
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from loupe.client import LoupeClient
from loupe.models import TracePayload

F = TypeVar("F", bound=Callable[..., Any])

# Module-level state — set by loupe.init()
_client: LoupeClient | None = None
_default_name: str | None = None


def init(api_key: str, host: str = "http://localhost:8000", name: str | None = None) -> None:
    """Call once at startup before using @trace."""
    global _client, _default_name
    _client = LoupeClient(api_key=api_key, host=host)
    _default_name = name


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
                # Loupe not initialised — run the function unmodified.
                return fn(*args, **kwargs)

            started_at = datetime.now(timezone.utc)
            trace_id = uuid.uuid4()
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
                ended_at = datetime.now(timezone.utc)
                duration_ms = int((ended_at - started_at).total_seconds() * 1000)

                payload = TracePayload(
                    id=trace_id,
                    name=trace_name,
                    status=status,
                    input=_safe_serialize(args, kwargs),
                    output=_safe_serialize(result),
                    error=error_info,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                )
                _client.flush(payload)

        return wrapper  # type: ignore[return-value]

    # Allow both @loupe.trace and @loupe.trace(name="...")
    if _fn is not None:
        return decorator(_fn)
    return decorator


def _safe_serialize(*values: Any) -> dict[str, Any] | None:
    """Best-effort conversion of arbitrary values to a JSON-safe dict."""
    if not values:
        return None
    if len(values) == 1 and isinstance(values[0], dict):
        return values[0]
    if len(values) == 2:
        # Called as _safe_serialize(args, kwargs)
        args, kwargs = values
        result: dict[str, Any] = {}
        if args:
            result["args"] = [_to_jsonable(a) for a in args]
        if kwargs:
            result["kwargs"] = {k: _to_jsonable(v) for k, v in kwargs.items()}
        return result or None
    return {"value": _to_jsonable(values[0])}


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert common Python types to JSON-safe equivalents."""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(i) for i in obj]
    return str(obj)

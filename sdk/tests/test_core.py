"""
Tests for the @loupe.trace decorator and loupe.span() used as both
a decorator (auto-capture) and a context manager (manual).
"""
from __future__ import annotations

import uuid

import pytest

import loupe
from loupe.core import _TraceContext, _current_trace


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enter_trace() -> tuple[_TraceContext, object]:
    """Push a fresh trace context and return (ctx, reset_token)."""
    loupe.init(api_key="test", host="http://localhost:19999")
    ctx = _TraceContext(trace_id=uuid.uuid4())
    token = _current_trace.set(ctx)
    return ctx, token


def _exit_trace(token: object) -> None:
    _current_trace.reset(token)  # type: ignore[arg-type]


# ── span() as decorator ────────────────────────────────────────────────────────

def test_span_decorator_captures_args():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="tool", name="my_tool")
        def my_tool(x: int, label: str) -> dict:
            return {"x": x}

        my_tool(42, label="hello")
    finally:
        _exit_trace(tok)

    assert len(ctx.spans) == 1
    s = ctx.spans[0]
    assert s.input is not None
    assert s.input["args"] == [42]
    assert s.input["kwargs"] == {"label": "hello"}


def test_span_decorator_captures_return_value():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="tool", name="my_tool")
        def my_tool() -> dict:
            return {"result": "ok"}

        my_tool()
    finally:
        _exit_trace(tok)

    s = ctx.spans[0]
    assert s.output == {"result": "ok"}


def test_span_decorator_captures_exception():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="tool", name="bad_tool")
        def bad_tool():
            raise ValueError("something broke")

        with pytest.raises(ValueError):
            bad_tool()
    finally:
        _exit_trace(tok)

    s = ctx.spans[0]
    assert s.error is not None
    assert s.error["type"] == "ValueError"
    assert "something broke" in s.error["message"]


def test_span_decorator_uses_function_name_when_no_name_given():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="tool")
        def fetch_data():
            return {}

        fetch_data()
    finally:
        _exit_trace(tok)

    assert ctx.spans[0].name == "fetch_data"


def test_span_decorator_sets_type():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="retrieval", name="search")
        def search():
            return []

        search()
    finally:
        _exit_trace(tok)

    assert ctx.spans[0].type == "retrieval"


def test_span_decorator_records_duration():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="tool", name="timed")
        def timed():
            return None

        timed()
    finally:
        _exit_trace(tok)

    assert ctx.spans[0].duration_ms is not None
    assert ctx.spans[0].duration_ms >= 0


# ── span() as context manager ──────────────────────────────────────────────────

def test_span_context_manager_manual_output():
    ctx, tok = _enter_trace()
    try:
        with loupe.span("search", type="tool") as s:
            s.output = {"count": 3}
    finally:
        _exit_trace(tok)

    assert len(ctx.spans) == 1
    assert ctx.spans[0].output == {"count": 3}


def test_span_context_manager_captures_exception():
    ctx, tok = _enter_trace()
    try:
        with pytest.raises(RuntimeError):
            with loupe.span("failing", type="tool"):
                raise RuntimeError("oops")
    finally:
        _exit_trace(tok)

    s = ctx.spans[0]
    assert s.error["type"] == "RuntimeError"


# ── nesting / parent-child ─────────────────────────────────────────────────────

def test_nested_spans_have_correct_parent():
    ctx, tok = _enter_trace()
    try:
        @loupe.span(type="function", name="outer")
        def outer():
            @loupe.span(type="tool", name="inner")
            def inner():
                return "done"
            return inner()

        outer()
    finally:
        _exit_trace(tok)

    assert len(ctx.spans) == 2
    outer_span = next(s for s in ctx.spans if s.name == "outer")
    inner_span = next(s for s in ctx.spans if s.name == "inner")
    assert inner_span.parent_span_id == outer_span.id


# ── outside a trace — no crash ─────────────────────────────────────────────────

def test_span_decorator_outside_trace_is_noop():
    """span() outside @trace should not raise and should return the function result."""
    @loupe.span(type="tool", name="orphan")
    def orphan():
        return 99

    assert orphan() == 99


def test_span_context_manager_outside_trace_is_noop():
    with loupe.span("orphan", type="tool") as s:
        s.output = {"ok": True}
    # no crash, no spans recorded anywhere


# ── @trace on generator functions (e.g. SSE streaming agents) ───────────────────

def _capture_traces(monkeypatch) -> list:
    """Init loupe and capture every enqueued TracePayload into a list."""
    import loupe.core as core

    loupe.init(api_key="test", host="http://localhost:19999")
    captured: list = []
    monkeypatch.setattr(core._client, "enqueue", captured.append)
    return captured


def test_trace_on_generator_keeps_trace_open_for_spans(monkeypatch):
    captured = _capture_traces(monkeypatch)

    @loupe.trace(name="streamer")
    def stream():
        # A span created mid-stream must land under this trace.
        with loupe.span("mid", type="tool") as s:
            s.output = {"ok": True}
        for i in range(3):
            yield i

    result = list(stream())

    assert result == [0, 1, 2]
    assert len(captured) == 1
    payload = captured[0]
    assert payload.name == "streamer"
    assert payload.status == "success"
    # The span created while streaming is captured under the trace.
    assert len(payload.spans) == 1
    assert payload.spans[0].name == "mid"
    # Yielded items are recorded as the trace output.
    assert payload.output is not None


def test_trace_on_generator_records_error(monkeypatch):
    captured = _capture_traces(monkeypatch)

    @loupe.trace(name="boom")
    def stream():
        yield 1
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        list(stream())

    assert len(captured) == 1
    payload = captured[0]
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error["type"] == "ValueError"


def test_trace_rolls_up_span_tokens_and_cost(monkeypatch):
    from decimal import Decimal

    captured = _capture_traces(monkeypatch)

    @loupe.trace(name="agent")
    def run():
        with loupe.span("call1", type="llm") as s:
            s.total_tokens = 789
            s.cost_usd = Decimal("0.001")
        with loupe.span("call2", type="llm") as s:
            s.total_tokens = 1325
            s.cost_usd = Decimal("0.002")
        with loupe.span("tool", type="tool") as s:  # no tokens/cost
            s.output = {"ok": True}

    run()

    payload = captured[0]
    assert payload.total_tokens == 789 + 1325
    assert payload.total_cost_usd == Decimal("0.003")


def test_trace_totals_are_none_when_no_span_reports_them(monkeypatch):
    captured = _capture_traces(monkeypatch)

    @loupe.trace(name="tool_only")
    def run():
        with loupe.span("tool", type="tool") as s:
            s.output = {"ok": True}

    run()

    payload = captured[0]
    assert payload.total_tokens is None
    assert payload.total_cost_usd is None


def test_trace_on_generator_is_lazy_and_noop_without_init(monkeypatch):
    import loupe.core as core

    monkeypatch.setattr(core, "_client", None)

    @loupe.trace
    def stream():
        yield "a"
        yield "b"

    # Without init, it still works as a plain generator.
    assert list(stream()) == ["a", "b"]

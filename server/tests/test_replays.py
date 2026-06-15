"""
Tests for the replay system:
  - POST /v1/replays, GET /v1/replays/{id}   (API layer)
  - _run_replay                               (engine logic)
  - _apply_prompt_override, _detect_provider, _estimate_cost  (pure helpers)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Replay, Span, Trace
from app.routers.replays import (
    _apply_prompt_override,
    _detect_provider,
    _estimate_cost,
    _run_replay,
)
from tests.conftest import make_engine, make_span_payload, make_trace_payload


# ── Pure helper unit tests ─────────────────────────────────────────────────────

class TestApplyPromptOverride:
    def test_replaces_existing_system_message(self):
        messages = [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "hello"},
        ]
        result = _apply_prompt_override(messages, "new system")
        assert result[0] == {"role": "system", "content": "new system"}
        assert result[1] == {"role": "user", "content": "hello"}

    def test_prepends_system_when_none_exists(self):
        messages = [{"role": "user", "content": "hello"}]
        result = _apply_prompt_override(messages, "new system")
        assert result[0] == {"role": "system", "content": "new system"}
        assert result[1] == {"role": "user", "content": "hello"}

    def test_does_not_mutate_original(self):
        messages = [{"role": "system", "content": "original"}]
        _apply_prompt_override(messages, "new")
        assert messages[0]["content"] == "original"

    def test_empty_messages(self):
        result = _apply_prompt_override([], "system prompt")
        assert result == [{"role": "system", "content": "system prompt"}]


class TestDetectProvider:
    def test_claude_is_anthropic(self):
        assert _detect_provider("claude-opus-4") == "anthropic"
        assert _detect_provider("claude-sonnet-4-6") == "anthropic"

    def test_llama_is_groq(self):
        assert _detect_provider("llama-3.3-70b-versatile") == "groq"

    def test_gemma_is_groq(self):
        assert _detect_provider("gemma-7b-it") == "groq"

    def test_unknown_defaults_to_openai(self):
        assert _detect_provider("gpt-4o") == "openai"
        assert _detect_provider("unknown-model-xyz") == "openai"

    def test_fallback_used_for_unknown(self):
        assert _detect_provider("some-model", fallback="groq") == "groq"
        assert _detect_provider("some-model", fallback="anthropic") == "anthropic"


class TestEstimateCost:
    def test_known_model_returns_decimal(self):
        cost = _estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == Decimal("12.500000")  # (2.5 + 10.0) / 1

    def test_unknown_model_returns_none(self):
        assert _estimate_cost("some-future-model", 1000, 1000) is None

    def test_prefix_matching(self):
        # gpt-4o-mini should match "gpt-4o-mini" prefix
        cost = _estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == Decimal("0.750000")  # (0.15 + 0.60) / 1

    def test_zero_tokens(self):
        cost = _estimate_cost("gpt-4o", 0, 0)
        assert cost == Decimal("0.000000")


# ── Provider-call hardening ──────────────────────────────────────────────────────
# Regression tests for two real failures seen in a deployed replay:
#   - a trailing newline in an API key → "Illegal header value"
#   - a span with only a system message → Anthropic "at least one message" 400


class _FakeResp:
    is_success = True
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}


async def test_call_groq_strips_key_newline(monkeypatch):
    from app.routers import replays as R

    captured: dict = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *, headers, json):
            captured["headers"] = headers
            return _FakeResp()

    monkeypatch.setattr(R.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(R.settings, "groq_api_key", "gsk_abc123\n")

    await R._call_groq("llama-3.3-70b-versatile", [{"role": "user", "content": "hi"}])

    auth = captured["headers"]["Authorization"]
    assert auth == "Bearer gsk_abc123"
    assert "\n" not in auth


async def test_call_anthropic_empty_messages_raises(monkeypatch):
    from app.routers import replays as R

    monkeypatch.setattr(R.settings, "anthropic_api_key", "sk-ant-test")

    # Only a system message → nothing left after stripping it.
    with pytest.raises(RuntimeError, match="no .*user/assistant messages"):
        await R._call_anthropic(
            "claude-haiku-4-5-20251001",
            [{"role": "system", "content": "only system"}],
            None,
        )


# ── API tests ──────────────────────────────────────────────────────────────────


async def test_create_replay_success(client):
    """POST /v1/replays returns 201 with replay_id and new_trace_id.

    The background _run_replay is mocked out — its behaviour is covered by the
    dedicated engine tests below. Here we only assert the endpoint's synchronous
    contract (creates rows, returns ids).
    """
    payload = make_trace_payload(spans=[make_span_payload("classify", "llm")])
    await client.post("/v1/traces", json=payload)

    with patch("app.routers.replays._run_replay", new=AsyncMock()):
        resp = await client.post("/v1/replays", json={
            "original_trace_id": payload["id"],
            "prompt_override": "You are a helpful assistant.",
        })
    assert resp.status_code == 201
    body = resp.json()
    assert "replay_id" in body
    assert "new_trace_id" in body
    assert body["new_trace_id"] != payload["id"]



async def test_create_replay_nonexistent_trace(client):
    resp = await client.post("/v1/replays", json={
        "original_trace_id": str(uuid.uuid4()),
    })
    assert resp.status_code == 404



async def test_create_replay_no_auth(unauthed_client):
    resp = await unauthed_client.post("/v1/replays", json={
        "original_trace_id": str(uuid.uuid4()),
    })
    assert resp.status_code == 401



async def test_get_replay_success(client):
    # Create a trace then a replay (background task mocked — see note above).
    payload = make_trace_payload()
    await client.post("/v1/traces", json=payload)

    with patch("app.routers.replays._run_replay", new=AsyncMock()):
        create_resp = await client.post("/v1/replays", json={
            "original_trace_id": payload["id"],
            "model_override": "gpt-4o-mini",
        })
    replay_id = create_resp.json()["replay_id"]

    resp = await client.get(f"/v1/replays/{replay_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["replay_id"] == replay_id
    assert body["original_trace_id"] == payload["id"]
    assert body["modifications"]["model_override"] == "gpt-4o-mini"



async def test_get_replay_not_found(client):
    resp = await client.get(f"/v1/replays/{uuid.uuid4()}")
    assert resp.status_code == 404



async def test_get_replay_no_auth(unauthed_client):
    resp = await unauthed_client.get(f"/v1/replays/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── _run_replay engine tests ───────────────────────────────────────────────────

def _make_db_trace(project_id: uuid.UUID) -> Trace:
    now = datetime.now(timezone.utc)
    return Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        name="triage_agent",
        status="success",
        input={"query": "test"},
        output={"value": [{"issue": 1, "label": "bug"}]},
        started_at=now,
        ended_at=now,
        duration_ms=5000,
        total_tokens=300,
    )


def _make_db_span(name: str, type: str, input: dict | None = None) -> Span:
    now = datetime.now(timezone.utc)
    return Span(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),  # will be reassigned
        type=type,
        name=name,
        input=input or {"arg": "val"},
        output={"result": "original"},
        started_at=now,
        ended_at=now,
        duration_ms=100,
        model="llama-3.3-70b-versatile" if type == "llm" else None,
        provider="groq" if type == "llm" else None,
        prompt_tokens=100 if type == "llm" else None,
        completion_tokens=50 if type == "llm" else None,
        total_tokens=150 if type == "llm" else None,
    )



async def test_run_replay_non_llm_spans_copied(project, db):
    """Tool spans are copied as-is — no LLM calls made."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)

    original = _make_db_trace(project.id)
    tool_span = _make_db_span("list_issues", "tool")
    tool_span.trace_id = original.id
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    async with sf() as s:
        s.add(original)
        await s.flush()               # ensure trace row exists before span + replay
        s.add(tool_span)
        await s.flush()
        s.add(Trace(
            id=new_trace_id, project_id=project.id,
            name="triage_agent (replay)", status="running",
            input=original.input, is_replay=True,
            replay_of_trace_id=original.id,
            started_at=datetime.now(timezone.utc),
        ))
        await s.flush()
        s.add(Replay(id=replay_id, original_trace_id=original.id,
                     new_trace_id=new_trace_id, modifications={}))
        await s.commit()

    with patch("app.routers.replays.SessionLocal", new=sf):
        await _run_replay(
            replay_id=replay_id,
            new_trace_id=new_trace_id,
            original_trace_id=original.id,
            prompt_override=None,
            model_override=None,
            project_id=project.id,
        )

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with sf() as v:
        result = await v.execute(
            select(Trace).where(Trace.id == new_trace_id).options(selectinload(Trace.spans))
        )
        new = result.scalar_one()

    assert new.status == "success"
    assert len(new.spans) == 1
    assert new.spans[0].name == "list_issues"
    assert new.spans[0].type == "tool"
    assert new.spans[0].output == {"result": "original"}



async def test_run_replay_llm_span_re_executed(project, db):
    """LLM spans are re-run — Groq call is mocked."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)

    original = _make_db_trace(project.id)
    llm_span = _make_db_span("classify_issue", "llm", input={"messages": [
        {"role": "system", "content": "You are a triage assistant."},
        {"role": "user", "content": "Title: Add dark mode\nBody: "},
    ]})
    llm_span.trace_id = original.id
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    async with sf() as s:
        s.add(original)
        await s.flush()
        s.add(llm_span)
        await s.flush()
        s.add(Trace(
            id=new_trace_id, project_id=project.id,
            name="triage_agent (replay)", status="running",
            input=original.input, is_replay=True,
            replay_of_trace_id=original.id,
            started_at=datetime.now(timezone.utc),
        ))
        await s.flush()
        s.add(Replay(id=replay_id, original_trace_id=original.id,
                     new_trace_id=new_trace_id, modifications={}))
        await s.commit()

    groq_response = {
        "choices": [{"message": {"content": '{"label": "feature"}'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }

    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays._call_groq", new=AsyncMock(return_value=groq_response)),
    ):
        await _run_replay(
            replay_id=replay_id,
            new_trace_id=new_trace_id,
            original_trace_id=original.id,
            prompt_override=None,
            model_override=None,
            project_id=project.id,
        )

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with sf() as v:
        result = await v.execute(
            select(Trace).where(Trace.id == new_trace_id).options(selectinload(Trace.spans))
        )
        new = result.scalar_one()

    assert new.status == "success"
    assert len(new.spans) == 1
    span = new.spans[0]
    assert span.type == "llm"
    assert span.prompt_tokens == 120
    assert span.completion_tokens == 30
    assert span.total_tokens == 150



async def test_run_replay_prompt_override_applied(project, db):
    """When prompt_override is given, the system message in the LLM call is replaced."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)

    original = _make_db_trace(project.id)
    llm_span = _make_db_span("classify_issue", "llm", input={"messages": [
        {"role": "system", "content": "OLD SYSTEM PROMPT"},
        {"role": "user", "content": "some issue"},
    ]})
    llm_span.trace_id = original.id
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    async with sf() as s:
        s.add(original)
        await s.flush()
        s.add(llm_span)
        await s.flush()
        s.add(Trace(id=new_trace_id, project_id=project.id,
                    name="r", status="running", input={},
                    is_replay=True, replay_of_trace_id=original.id,
                    started_at=datetime.now(timezone.utc)))
        await s.flush()
        s.add(Replay(id=replay_id, original_trace_id=original.id,
                     new_trace_id=new_trace_id, modifications={}))
        await s.commit()

    captured_messages = []

    async def fake_groq(model, messages):
        captured_messages.extend(messages)
        return {"choices": [{"message": {"content": "result"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays._call_groq", new=fake_groq),
    ):
        await _run_replay(
            replay_id=replay_id,
            new_trace_id=new_trace_id,
            original_trace_id=original.id,
            prompt_override="NEW SYSTEM PROMPT",
            model_override=None,
            project_id=project.id,
        )

    system_msgs = [m for m in captured_messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "NEW SYSTEM PROMPT"



async def test_run_replay_llm_failure_marks_error(project, db):
    """If the LLM call fails, the replay trace should be marked error."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)

    original = _make_db_trace(project.id)
    llm_span = _make_db_span("classify", "llm",
                             input={"messages": [{"role": "user", "content": "x"}]})
    llm_span.trace_id = original.id
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()

    async with sf() as s:
        s.add(original)
        await s.flush()
        s.add(llm_span)
        await s.flush()
        s.add(Trace(id=new_trace_id, project_id=project.id,
                    name="r", status="running", input={},
                    is_replay=True, replay_of_trace_id=original.id,
                    started_at=datetime.now(timezone.utc)))
        await s.flush()
        s.add(Replay(id=replay_id, original_trace_id=original.id,
                     new_trace_id=new_trace_id, modifications={}))
        await s.commit()

    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays._call_groq",
              new=AsyncMock(side_effect=RuntimeError("Groq API down"))),
    ):
        await _run_replay(
            replay_id=replay_id,
            new_trace_id=new_trace_id,
            original_trace_id=original.id,
            prompt_override=None,
            model_override=None,
            project_id=project.id,
        )

    from sqlalchemy import select

    async with sf() as v:
        result = await v.execute(select(Trace).where(Trace.id == new_trace_id))
        new = result.scalar_one()

    assert new.status == "error"
    assert new.error is not None
    assert "Groq API down" in new.error["message"]

"""
Tests for the branch replay engine (Phase 4):
  - _effective_policy                  (pure classifier)
  - _run_branch                        (engine logic — added in sub-step 3)

The branch engine implements: freeze before the branch, use the user's edit AT
the branch, re-run after it (llm live, writes dry-run, live tools passthrough).
See docs/design-*.md for the spec.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import Replay, Span, Trace
from app.routers.replays import _effective_policy, _run_branch
from tests.conftest import make_engine, make_span_payload, make_trace_payload


# ── _effective_policy classifier ────────────────────────────────────────────────

class TestEffectivePolicy:
    def test_unannotated_tool_is_dry_run(self):
        # Safe default: a tool with no annotation must never re-run a write.
        assert _effective_policy("tool", "dry_run") == "dry_run"

    def test_tool_annotated_live_is_live(self):
        # SDK opted this tool (e.g. a read) into live execution.
        assert _effective_policy("tool", "live") == "live"

    def test_tool_with_null_policy_defaults_dry_run(self):
        assert _effective_policy("tool", None) == "dry_run"

    def test_llm_is_always_live(self):
        # llm spans re-run regardless of the column — that's the point of replay.
        assert _effective_policy("llm", "dry_run") == "live"
        assert _effective_policy("llm", "live") == "live"

    def test_retrieval_is_live(self):
        assert _effective_policy("retrieval", "dry_run") == "live"

    def test_function_is_live(self):
        assert _effective_policy("function", "dry_run") == "live"


# ── _run_branch engine tests ────────────────────────────────────────────────────

_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _span(
    name: str,
    type: str,
    order: int,
    *,
    input: dict | None = None,
    output: dict | None = None,
    replay_policy: str = "dry_run",
    model: str | None = None,
    provider: str | None = None,
    total_tokens: int | None = None,
) -> Span:
    """Build a Span. `order` controls started_at so the engine's sort is stable."""
    ts = _T0 + timedelta(seconds=order)
    return Span(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),  # reassigned in _seed
        type=type,
        name=name,
        input=input or {"arg": "v"},
        output=output or {"result": "original"},
        started_at=ts,
        ended_at=ts,
        duration_ms=100,
        model=model,
        provider=provider,
        total_tokens=total_tokens,
        replay_policy=replay_policy,
    )


async def _seed(sf, project_id: uuid.UUID, spans: list[Span]):
    """Insert an original trace + spans + a running placeholder + a Replay row.
    Returns (original, new_trace_id, replay_id)."""
    original = Trace(
        id=uuid.uuid4(), project_id=project_id, name="triage", status="success",
        input={"q": "x"}, output={"o": 1},
        started_at=spans[0].started_at, ended_at=spans[-1].started_at,
        duration_ms=5000, total_tokens=300,
    )
    for s in spans:
        s.trace_id = original.id
    new_trace_id = uuid.uuid4()
    replay_id = uuid.uuid4()
    async with sf() as s:
        s.add(original)
        await s.flush()
        for sp in spans:
            s.add(sp)
        await s.flush()
        s.add(Trace(
            id=new_trace_id, project_id=project_id, name="triage (branch)",
            status="running", input=original.input, is_replay=True,
            branched_from_trace_id=original.id,
            started_at=datetime.now(timezone.utc),
        ))
        await s.flush()
        s.add(Replay(id=replay_id, original_trace_id=original.id,
                     new_trace_id=new_trace_id, modifications={}))
        await s.commit()
    return original, new_trace_id, replay_id


async def _load(sf, new_trace_id: uuid.UUID):
    """Load the branched trace and return (trace, {span_name: span})."""
    async with sf() as v:
        r = await v.execute(
            select(Trace).where(Trace.id == new_trace_id).options(selectinload(Trace.spans))
        )
        t = r.scalar_one()
        return t, {s.name: s for s in t.spans}


async def test_branch_freezes_before_overrides_at_ghosts_after(project, db):
    """The full triage scenario: branch at classify_issue.
    - list_issues (before)  → frozen, stored output kept
    - classify_issue (at)   → uses the user's edited output
    - add_label/post_comment (after, writes) → dry-run ghost spans, no real call
    """
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [
        _span("list_issues", "tool", 0, replay_policy="live",
              output={"issues": [1, 2, 3]}),
        _span("classify_issue", "llm", 1, model="llama-3.3-70b-versatile",
              provider="groq", output={"content": "bug"}),
        _span("add_label", "tool", 2, input={"issue": 3, "label": "bug"}),
        _span("post_comment", "tool", 3, input={"issue": 3, "body": "hi"}),
    ]
    branch_span = spans[1]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    with patch("app.routers.replays.SessionLocal", new=sf):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=branch_span.id,
            new_output={"content": "feature"}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    assert trace.status == "success"
    assert len(by_name) == 4
    # before: frozen
    assert by_name["list_issues"].output == {"issues": [1, 2, 3]}
    # at: edited output, marked as the branch point
    assert by_name["classify_issue"].output == {"content": "feature"}
    assert by_name["classify_issue"].extra_metadata["branch_point"] is True
    # after: dry-run ghosts
    add = by_name["add_label"]
    assert add.output == {"would_have": {"issue": 3, "label": "bug"}}
    assert add.extra_metadata["dry_run"] is True
    assert by_name["post_comment"].output == {"would_have": {"issue": 3, "body": "hi"}}


async def test_branch_reexecutes_llm_after_branch(project, db):
    """An llm span AFTER the branch is re-run live (Groq mocked)."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [
        _span("classify_a", "llm", 0, model="llama-3.3-70b-versatile", provider="groq",
              input={"messages": [{"role": "user", "content": "a"}]},
              output={"content": "old-a"}),
        _span("classify_b", "llm", 1, model="llama-3.3-70b-versatile", provider="groq",
              input={"messages": [{"role": "user", "content": "b"}]},
              output={"content": "old-b"}),
    ]
    branch_span = spans[0]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    groq_response = {
        "choices": [{"message": {"content": "fresh-b"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays._call_groq", new=AsyncMock(return_value=groq_response)),
    ):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=branch_span.id,
            new_output={"content": "edited-a"}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    assert trace.status == "success"
    # branch point uses the edit
    assert by_name["classify_a"].output == {"content": "edited-a"}
    # downstream llm re-run with the mocked provider response
    assert by_name["classify_b"].output == {"content": "fresh-b"}
    assert by_name["classify_b"].provider == "groq"
    assert by_name["classify_b"].total_tokens == 15


async def test_branch_llm_passthrough_when_server_replay_disabled(project, db):
    """B7: with allow_server_side_llm_replay off, a post-branch llm is NOT re-run —
    it passes through its stored output and the provider is never called."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [
        _span("classify_a", "llm", 0, model="llama-3.3-70b-versatile", provider="groq",
              input={"messages": [{"role": "user", "content": "a"}]},
              output={"content": "old-a"}),
        _span("classify_b", "llm", 1, model="llama-3.3-70b-versatile", provider="groq",
              input={"messages": [{"role": "user", "content": "b"}]},
              output={"content": "old-b"}),
    ]
    branch_span = spans[0]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    groq_mock = AsyncMock()
    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays.settings.allow_server_side_llm_replay", False),
        patch("app.routers.replays._call_groq", new=groq_mock),
    ):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=branch_span.id,
            new_output={"content": "edited-a"}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    assert trace.status == "success"
    groq_mock.assert_not_called()  # no live call, no key spend
    # downstream llm kept its stored output, marked as a passthrough
    assert by_name["classify_b"].output == {"content": "old-b"}
    assert by_name["classify_b"].extra_metadata["replay"] == "stored_passthrough"


async def test_branch_passthrough_for_live_tool_after_branch(project, db):
    """A tool annotated replay_policy='live' after the branch can't be run by the
    server → its stored output is passed through (Option A)."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [
        _span("classify", "llm", 0, model="llama-3.3-70b-versatile", provider="groq",
              output={"content": "old"}),
        _span("fetch_data", "tool", 1, replay_policy="live",
              output={"rows": [9, 8, 7]}),
    ]
    branch_span = spans[0]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    with patch("app.routers.replays.SessionLocal", new=sf):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=branch_span.id,
            new_output={"content": "new"}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    fetch = by_name["fetch_data"]
    assert fetch.output == {"rows": [9, 8, 7]}            # stored value reused
    assert fetch.extra_metadata["replay"] == "stored_passthrough"


async def test_branch_unknown_span_marks_error(project, db):
    """If branch_span_id is not in the trace, the branch errors cleanly."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [_span("a", "tool", 0), _span("b", "tool", 1)]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    with patch("app.routers.replays.SessionLocal", new=sf):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=uuid.uuid4(),  # not in trace
            new_output={"x": 1}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    assert trace.status == "error"
    assert trace.error["type"] == "BranchSpanNotFound"
    assert len(by_name) == 0  # no spans produced


async def test_branch_llm_failure_after_branch_marks_error(project, db):
    """If a re-executed llm raises, the branch is marked error and the span
    records the failure."""
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    spans = [
        _span("classify_a", "llm", 0, model="llama-3.3-70b-versatile", provider="groq",
              output={"content": "old-a"}),
        _span("classify_b", "llm", 1, model="llama-3.3-70b-versatile", provider="groq",
              input={"messages": [{"role": "user", "content": "b"}]},
              output={"content": "old-b"}),
    ]
    branch_span = spans[0]
    original, new_trace_id, replay_id = await _seed(sf, project.id, spans)

    failing = AsyncMock(side_effect=RuntimeError("groq 500"))
    with (
        patch("app.routers.replays.SessionLocal", new=sf),
        patch("app.routers.replays._call_groq", new=failing),
    ):
        await _run_branch(
            replay_id=replay_id, new_trace_id=new_trace_id,
            original_trace_id=original.id, branch_span_id=branch_span.id,
            new_output={"content": "edited-a"}, project_id=project.id,
        )

    trace, by_name = await _load(sf, new_trace_id)
    assert trace.status == "error"
    assert by_name["classify_b"].error["type"] == "RuntimeError"
    assert by_name["classify_b"].output is None


# ── POST /v1/traces/{id}/branch endpoint tests ──────────────────────────────────
# The BackgroundTask (_run_branch) is mocked — its behaviour is covered by the
# engine tests above. Here we only test the API layer: validation, the
# placeholder trace, the Replay row, and that the task is scheduled.

async def test_branch_endpoint_creates_placeholder_and_replay(client, db):
    span = make_span_payload(name="classify", type="llm")
    trace = make_trace_payload(spans=[span])
    assert (await client.post("/v1/traces", json=trace)).status_code == 201

    with patch("app.routers.traces._run_branch", new=AsyncMock()) as mock_run:
        resp = await client.post(
            f"/v1/traces/{trace['id']}/branch",
            json={"span_id": span["id"], "new_output": {"content": "fixed"}},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["replay_id"] and body["new_trace_id"]
    mock_run.assert_called_once()

    # Placeholder trace is 'running' and linked to the original via lineage cols.
    new_trace = await db.get(Trace, uuid.UUID(body["new_trace_id"]))
    assert new_trace.status == "running"
    assert str(new_trace.branched_from_trace_id) == trace["id"]
    assert str(new_trace.branched_from_span_id) == span["id"]
    assert new_trace.is_replay is True
    assert new_trace.replay_mode == "server"  # B3: dashboard branch is server-side

    # Replay row records the edit.
    replay = await db.get(Replay, uuid.UUID(body["replay_id"]))
    assert replay.modifications["branch_span_id"] == span["id"]
    assert replay.modifications["new_output"] == {"content": "fixed"}


async def test_branch_endpoint_trace_not_found(client):
    resp = await client.post(
        f"/v1/traces/{uuid.uuid4()}/branch",
        json={"span_id": str(uuid.uuid4()), "new_output": {"x": 1}},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Trace not found"


async def test_branch_endpoint_span_not_in_trace(client):
    trace = make_trace_payload(spans=[make_span_payload(name="a", type="tool")])
    assert (await client.post("/v1/traces", json=trace)).status_code == 201

    resp = await client.post(
        f"/v1/traces/{trace['id']}/branch",
        json={"span_id": str(uuid.uuid4()), "new_output": {"x": 1}},  # span not in trace
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Branch span not found in this trace"


async def test_branch_endpoint_requires_auth(unauthed_client):
    resp = await unauthed_client.post(
        f"/v1/traces/{uuid.uuid4()}/branch",
        json={"span_id": str(uuid.uuid4()), "new_output": {"x": 1}},
    )
    assert resp.status_code == 401

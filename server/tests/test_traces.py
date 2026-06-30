"""
Tests for POST /v1/traces, GET /v1/traces, GET /v1/traces/{id}.
Covers: happy paths, auth, idempotency, pagination, project isolation.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Replay
from tests.conftest import make_engine, make_span_payload, make_trace_payload


async def _replays_for(new_trace_id: str) -> list[Replay]:
    """Fresh-session lookup of the replays auto-created for a branch (ingest commits,
    so a new session sees them — avoids any client/session sharing assumptions)."""
    eng = make_engine()
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        rows = (
            await s.execute(
                select(Replay).where(Replay.new_trace_id == uuid.UUID(new_trace_id))
            )
        ).scalars().all()
    await eng.dispose()
    return list(rows)


# ── POST /v1/traces ────────────────────────────────────────────────────────────


async def test_ingest_trace_success(client):
    payload = make_trace_payload(name="my_agent", status="success")
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["trace_id"] == payload["id"]
    assert body["span_count"] == 0



async def test_ingest_trace_with_spans(client):
    spans = [
        make_span_payload("list_issues", "tool"),
        make_span_payload("classify", "llm"),
    ]
    payload = make_trace_payload(spans=spans)
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 201
    assert resp.json()["span_count"] == 2



async def test_ingest_trace_with_nested_spans(client):
    parent = make_span_payload("classify_issue", "function")
    child = make_span_payload("groq.chat", "llm", parent_span_id=parent["id"])
    payload = make_trace_payload(spans=[parent, child])
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 201
    assert resp.json()["span_count"] == 2



async def test_ingest_trace_idempotent(client):
    """Sending the same trace ID twice must not fail — second is a no-op."""
    payload = make_trace_payload()
    resp1 = await client.post("/v1/traces", json=payload)
    resp2 = await client.post("/v1/traces", json=payload)
    assert resp1.status_code == 201
    assert resp2.status_code == 201


# ── B2: ingest auto-creates a replays row for SDK-side branches ────────────────


def _branch_point_span() -> dict:
    span = make_span_payload("classify", "llm")
    span["metadata"] = {"branch_point": True}
    span["output"] = {"content": "edited"}
    return span


async def test_ingest_branch_autocreates_replay_row(client):
    """An SDK-side branch arrives with branched_from set but no replays row; the
    server auto-creates one with the diff metadata computed against the original."""
    orig_span = make_span_payload("classify", "llm")
    original = make_trace_payload(
        name="orig", status="success", total_tokens=100, duration_ms=1000,
        spans=[orig_span],
    )
    await client.post("/v1/traces", json=original)

    bp = _branch_point_span()
    branch = make_trace_payload(
        name="orig (branch)",
        status="success",
        spans=[bp],
        total_tokens=140,
        duration_ms=700,
        is_replay=True,
        replay_mode="sdk",
        branched_from_trace_id=original["id"],
        branched_from_span_id=orig_span["id"],  # FK → an existing original span
    )
    resp = await client.post("/v1/traces", json=branch)
    assert resp.status_code == 201

    rows = await _replays_for(branch["id"])
    assert len(rows) == 1
    row = rows[0]
    assert str(row.original_trace_id) == original["id"]
    assert row.diff_summary["token_delta"] == 40       # 140 - 100
    assert row.diff_summary["latency_delta_ms"] == -300  # 700 - 1000
    assert row.diff_summary["status"] == "success"
    # new_output is recovered from the branch-point span's output
    assert row.modifications["new_output"] == {"content": "edited"}


async def test_ingest_branch_replay_row_idempotent(client):
    """Re-delivering the branch must not create a second replays row."""
    orig_span = make_span_payload("classify", "llm")
    original = make_trace_payload(name="orig", total_tokens=10, spans=[orig_span])
    await client.post("/v1/traces", json=original)
    branch = make_trace_payload(
        name="orig (branch)",
        spans=[_branch_point_span()],
        is_replay=True,
        replay_mode="sdk",
        branched_from_trace_id=original["id"],
        branched_from_span_id=orig_span["id"],
    )
    await client.post("/v1/traces", json=branch)
    await client.post("/v1/traces", json=branch)  # re-delivery
    assert len(await _replays_for(branch["id"])) == 1


async def test_ingest_plain_trace_no_replay_row(client):
    """A normal (non-branch) trace must not create a replays row."""
    payload = make_trace_payload(name="plain")
    await client.post("/v1/traces", json=payload)
    assert await _replays_for(payload["id"]) == []



async def test_ingest_trace_no_auth(unauthed_client):
    resp = await unauthed_client.post("/v1/traces", json=make_trace_payload())
    assert resp.status_code == 401



async def test_ingest_trace_wrong_key(unauthed_client):
    resp = await unauthed_client.post(
        "/v1/traces",
        json=make_trace_payload(),
        headers={"X-API-Key": "lp_wrong_key"},
    )
    assert resp.status_code == 401



async def test_ingest_trace_error_status(client):
    payload = make_trace_payload(
        status="error",
        output=None,
        error={"type": "ValueError", "message": "something broke"},
    )
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 201


# ── GET /v1/traces ─────────────────────────────────────────────────────────────


async def test_list_traces_empty(client):
    resp = await client.get("/v1/traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["has_more"] is False



async def test_list_traces_returns_ingested(client):
    await client.post("/v1/traces", json=make_trace_payload(name="agent_run"))
    resp = await client.get("/v1/traces")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "agent_run"



async def test_list_traces_ordered_newest_first(client):
    from datetime import timedelta

    from tests.conftest import datetime, timezone

    now = datetime.now(timezone.utc)

    old = make_trace_payload(name="old_trace")
    old["started_at"] = (now - timedelta(hours=2)).isoformat()

    new = make_trace_payload(name="new_trace")
    new["started_at"] = now.isoformat()

    await client.post("/v1/traces", json=old)
    await client.post("/v1/traces", json=new)

    resp = await client.get("/v1/traces")
    items = resp.json()["items"]
    assert items[0]["name"] == "new_trace"
    assert items[1]["name"] == "old_trace"



async def test_list_traces_status_filter(client):
    await client.post("/v1/traces", json=make_trace_payload(status="success"))
    await client.post("/v1/traces", json=make_trace_payload(status="error"))

    resp = await client.get("/v1/traces?status=success")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "success"



async def test_list_traces_pagination_has_more(client):
    for i in range(3):
        await client.post("/v1/traces", json=make_trace_payload(name=f"trace_{i}"))

    resp = await client.get("/v1/traces?limit=2")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True
    assert body["limit"] == 2



async def test_list_traces_pagination_no_more(client):
    for i in range(2):
        await client.post("/v1/traces", json=make_trace_payload(name=f"trace_{i}"))

    resp = await client.get("/v1/traces?limit=10")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is False



async def test_list_traces_no_auth(unauthed_client):
    resp = await unauthed_client.get("/v1/traces")
    assert resp.status_code == 401


# ── GET /v1/traces/{id} ────────────────────────────────────────────────────────


async def test_get_trace_with_spans(client):
    spans = [make_span_payload("my_span", "tool")]
    payload = make_trace_payload(name="detail_test", spans=spans)
    await client.post("/v1/traces", json=payload)

    resp = await client.get(f"/v1/traces/{payload['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "detail_test"
    assert len(body["spans"]) == 1
    assert body["spans"][0]["name"] == "my_span"



async def test_get_trace_span_has_input_output(client):
    span = make_span_payload("classify", "llm")
    span["input"] = {"messages": [{"role": "user", "content": "hello"}]}
    span["output"] = {"label": "feature"}
    payload = make_trace_payload(spans=[span])
    await client.post("/v1/traces", json=payload)

    resp = await client.get(f"/v1/traces/{payload['id']}")
    s = resp.json()["spans"][0]
    assert s["input"] == {"messages": [{"role": "user", "content": "hello"}]}
    assert s["output"] == {"label": "feature"}



async def test_get_trace_not_found(client):
    resp = await client.get(f"/v1/traces/{uuid.uuid4()}")
    assert resp.status_code == 404



async def test_get_trace_no_auth(unauthed_client):
    resp = await unauthed_client.get(f"/v1/traces/{uuid.uuid4()}")
    assert resp.status_code == 401



async def test_get_trace_project_isolation(client, db):
    """A trace belonging to a different project must not be visible (404)."""
    from datetime import datetime, timezone

    from app.models import Project, Trace

    # Seed a second project and a trace under it, directly via the test session.
    other_project = Project(id=uuid.uuid4(), name="other-project")
    db.add(other_project)
    await db.flush()

    secret_id = uuid.uuid4()
    db.add(Trace(
        id=secret_id,
        project_id=other_project.id,
        name="secret_trace",
        status="success",
        started_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    # Our client (different project) must not be able to read it.
    resp = await client.get(f"/v1/traces/{secret_id}")
    assert resp.status_code == 404

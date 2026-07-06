"""Tests for v2.2 suites & suite runs.

- Engine test: `_run_suite` drives the per-trace replay+judge loop with the replay
  engine and judge mocked (no network), asserting counts land on the suite_run row.
- Endpoint tests: create/list/get suites, run (202 + row), and the poll endpoint —
  the background task is mocked, mirroring the branch endpoint tests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Suite, SuiteRun, SuiteTrace, Trace
from app.routers.suites import _run_suite
from app.services.judge import Verdict
from tests.conftest import make_engine, make_trace_payload


async def _seed_suite(sf, project_id: uuid.UUID, n_traces: int = 2):
    """Insert n original traces + a suite + membership + a running suite_run.
    Returns (suite_id, suite_run_id, [trace_ids])."""
    suite_id = uuid.uuid4()
    run_id = uuid.uuid4()
    trace_ids = [uuid.uuid4() for _ in range(n_traces)]
    now = datetime.now(timezone.utc)
    async with sf() as s:
        for i, tid in enumerate(trace_ids):
            s.add(
                Trace(
                    id=tid, project_id=project_id, name=f"t{i}", status="success",
                    input={"q": f"q{i}"}, output={"genre": "Sci-Fi"},
                    started_at=now, ended_at=now, duration_ms=100, total_tokens=50,
                )
            )
        s.add(Suite(id=suite_id, project_id=project_id, name="golden"))
        await s.flush()
        for tid in trace_ids:
            s.add(SuiteTrace(suite_id=suite_id, trace_id=tid))
        s.add(SuiteRun(id=run_id, suite_id=suite_id, status="running"))
        await s.commit()
    return suite_id, run_id, trace_ids


# ── engine test ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_suite_accumulates_counts(project, db):
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    suite_id, run_id, _ = await _seed_suite(sf, project.id, n_traces=2)

    # First trace regresses, second is equivalent → total 2, passed 1, regressed 1.
    verdicts = [
        Verdict(label="regressed", reasoning="broke", confidence=0.9),
        Verdict(label="equivalent", reasoning="same", confidence=1.0),
    ]
    with (
        patch("app.routers.suites.SessionLocal", new=sf),
        patch("app.routers.suites._run_replay", new=AsyncMock()),
        patch("app.routers.suites.judge_service.judge", new=AsyncMock(side_effect=verdicts)),
    ):
        await _run_suite(
            suite_run_id=run_id,
            suite_id=suite_id,
            prompt_override="new prompt",
            model_override=None,
            rubric=None,
            judge_backend="groq/llama-3.3-70b-versatile",
            project_id=project.id,
        )

    async with sf() as v:
        run = (
            await v.execute(select(SuiteRun).where(SuiteRun.id == run_id))
        ).scalar_one()
    assert run.status == "done"
    assert run.total == 2
    assert run.passed == 1
    assert run.regressed == 1
    assert run.improved == 0
    assert run.errored == 0
    assert len(run.results) == 2
    assert {r["verdict"] for r in run.results} == {"regressed", "equivalent"}


@pytest.mark.asyncio
async def test_run_suite_isolates_trace_failure(project, db):
    sf = async_sessionmaker(make_engine(), expire_on_commit=False)
    suite_id, run_id, _ = await _seed_suite(sf, project.id, n_traces=2)

    with (
        patch("app.routers.suites.SessionLocal", new=sf),
        patch("app.routers.suites._run_replay", new=AsyncMock()),
        patch("app.routers.suites.judge_service.judge", new=AsyncMock(
            side_effect=[RuntimeError("judge 500"),
                         Verdict(label="improved", reasoning="ok", confidence=0.8)])),
    ):
        await _run_suite(
            suite_run_id=run_id, suite_id=suite_id, prompt_override="p",
            model_override=None, rubric=None, judge_backend="groq/x",
            project_id=project.id,
        )

    async with sf() as v:
        run = (await v.execute(select(SuiteRun).where(SuiteRun.id == run_id))).scalar_one()
    assert run.status == "done"          # one bad trace doesn't kill the run
    assert run.errored == 1
    assert run.improved == 1
    assert run.passed == 1


# ── endpoint tests ─────────────────────────────────────────────────────────


async def _create_trace(client) -> str:
    payload = make_trace_payload()
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status_code == 201
    return payload["id"]


@pytest.mark.asyncio
async def test_create_list_get_suite(client):
    t1, t2 = await _create_trace(client), await _create_trace(client)
    resp = await client.post("/v1/suites", json={"name": "golden", "trace_ids": [t1, t2]})
    assert resp.status_code == 201
    suite_id = resp.json()["suite_id"]

    got = await client.get(f"/v1/suites/{suite_id}")
    assert got.status_code == 200
    assert got.json()["trace_count"] == 2
    assert got.json()["name"] == "golden"

    listed = await client.get("/v1/suites")
    assert any(s["id"] == suite_id for s in listed.json())


@pytest.mark.asyncio
async def test_create_suite_rejects_foreign_trace(client):
    resp = await client.post(
        "/v1/suites",
        json={"name": "bad", "trace_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_run_endpoint_creates_run_row(client):
    t1 = await _create_trace(client)
    suite_id = (
        await client.post("/v1/suites", json={"name": "s", "trace_ids": [t1]})
    ).json()["suite_id"]

    # Mock the background task so the endpoint only creates the row + returns 202.
    with patch("app.routers.suites._run_suite", new=AsyncMock()):
        resp = await client.post(
            f"/v1/suites/{suite_id}/run", json={"prompt_override": "new prompt"}
        )
    assert resp.status_code == 202
    run_id = resp.json()["suite_run_id"]

    got = await client.get(f"/v1/suite_runs/{run_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "running"
    assert body["prompt_override"] == "new prompt"
    assert body["judge_backend"] == "groq/llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_run_missing_suite_404(client):
    resp = await client.post(f"/v1/suites/{uuid.uuid4()}/run", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_suite_run_not_found(client):
    resp = await client.get(f"/v1/suite_runs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suites_require_auth(unauthed_client):
    resp = await unauthed_client.get("/v1/suites")
    assert resp.status_code == 401

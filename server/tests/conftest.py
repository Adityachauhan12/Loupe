"""
Test infrastructure for the Loupe server.

Pattern:
- Tables created ONCE per session via a sync autouse fixture (asyncio.run()).
- Each test gets its OWN engine (NullPool) so no connections cross event loops.
- Each test's DB is wiped via TRUNCATE CASCADE after the test.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://loupe:loupe@localhost:5433/loupe_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db import Base  # noqa: E402
from app.models import ApiKey, Project  # noqa: E402

TEST_DATABASE_URL = "postgresql+asyncpg://loupe:loupe@localhost:5433/loupe_test"


# ── One-time table setup/teardown (sync, no loop issues) ──────────────────────

async def _create_tables() -> None:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        # Drop first so the test DB always matches the current models — otherwise
        # create_all skips an existing table and a newly-added column (e.g.
        # traces.replay_mode) is silently missing, failing the whole suite.
        await conn.run_sync(Base.metadata.drop_all)
        # create_all handles the circular FK via use_alter=True on
        # branched_from_span_id — SQLAlchemy emits ALTER TABLE after both
        # tables exist, so no CircularDependencyError.
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()


async def _truncate_all() -> None:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(
            text("TRUNCATE spans, replays, traces, api_keys, projects CASCADE")
        )
    await eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Run once per session. Sync wrapper so there are no event loop conflicts."""
    asyncio.run(_create_tables())
    yield
    asyncio.run(_truncate_all())


# ── Per-test engine + session ──────────────────────────────────────────────────

def make_engine():
    """Fresh NullPool engine — no shared connections across event loops."""
    return create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


@pytest_asyncio.fixture
async def db(setup_database) -> AsyncIterator[AsyncSession]:
    """
    Per-test DB session on its own NullPool engine.

    Teardown happens inside this fixture's own event loop (the same loop the
    test ran in), so closing connections is loop-safe. We truncate using the
    same session, then close it and dispose the engine — this releases all
    locks and avoids the deadlock that a separate-loop TRUNCATE would hit.
    """
    eng = make_engine()
    session_factory = async_sessionmaker(eng, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.rollback()
        await session.execute(
            text("TRUNCATE spans, replays, traces, api_keys, projects CASCADE")
        )
        await session.commit()
        await session.close()
        await eng.dispose()


# ── Seed data ──────────────────────────────────────────────────────────────────

RAW_API_KEY = "lp_testkey_abc123"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest_asyncio.fixture
async def project(db: AsyncSession) -> Project:
    p = Project(id=uuid.uuid4(), name="test-project")
    db.add(p)
    await db.commit()
    return p


@pytest_asyncio.fixture
async def api_key(db: AsyncSession, project: Project) -> ApiKey:
    k = ApiKey(
        id=uuid.uuid4(),
        project_id=project.id,
        key_hash=_hash(RAW_API_KEY),
        name="test-key",
    )
    db.add(k)
    await db.commit()
    return k


# ── HTTP clients ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db: AsyncSession, api_key: ApiKey):
    from app.db import get_db
    from app.main import app

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.auth._touch_last_used", new=AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-API-Key": RAW_API_KEY},
        ) as c:
            yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthed_client(db: AsyncSession, api_key: ApiKey):
    """No X-API-Key header — for 401 tests. Still seeds DB so auth lookup works."""
    from app.db import get_db
    from app.main import app

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


# ── Trace / span factories ─────────────────────────────────────────────────────

def make_trace_payload(
    name: str = "test_agent",
    status: str = "success",
    spans: list[dict] | None = None,
    **kwargs,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "status": status,
        "input": {"query": "test input"},
        "output": {"result": "test output"},
        "started_at": now,
        "ended_at": now,
        "duration_ms": 500,
        "spans": spans or [],
        **kwargs,
    }


def make_span_payload(
    name: str = "test_span",
    type: str = "tool",
    parent_span_id: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": type,
        "input": {"arg": "value"},
        "output": {"result": "done"},
        "started_at": now,
        "ended_at": now,
        "duration_ms": 100,
        "parent_span_id": parent_span_id,
    }

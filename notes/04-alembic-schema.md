# Item 4 — Alembic migrations + 4-table schema

Split into 5 sub-steps. Each sub-step covers what changed, key learnings, and interview questions tied to those decisions.

---

## Sub-step A — Dependencies + config module

**What changed**

- Added `sqlalchemy[asyncio]==2.0.36`, `asyncpg==0.30.0`, `alembic==1.14.0`, `pydantic-settings==2.7.0`, `python-dotenv==1.0.1` to `server/requirements.txt`.
- Created `server/app/config.py` exposing a `Settings` object loaded from environment (with `.env` support in dev).
- Created `server/.env.example`.

**Learnings**

- **Sync drivers in async apps are a footgun.** `psycopg2` (sync) called from inside `async def` will silently block the event loop. Under load, throughput collapses because every DB call serializes the whole worker. `asyncpg` is the right default; `psycopg3` is fine too but its async story is newer.
- **`pydantic-settings` over raw `os.getenv`** centralizes config, validates types at boot (a malformed env var crashes the app at startup, not at request time), and gives editor autocomplete on `settings.database_url`.
- **Pinned versions in `requirements.txt`.** Without pins, a fresh install in CI three months from now might pull SQLAlchemy 2.1 with breaking changes. Pin everything you depend on directly. Production teams use lockfiles like `pip-tools` or `uv` for transitive deps too.

**Interview questions**

1. Why pick `asyncpg` over `psycopg2` in a FastAPI service? *(async event loop blocking)*
2. What's the difference between dependency pinning in `requirements.txt` vs a lockfile? *(top-level vs transitive; reproducibility)*
3. How would you load secrets in production differently than in dev? *(env vars from a secret manager, not `.env`; the `Settings` class stays the same — just sourced differently)*

---

## Sub-step B — `db.py`: async engine + session factory

**What changed**

- Created `server/app/db.py` with the `Base` declarative class, a singleton async engine, a session factory (`async_sessionmaker`), and a FastAPI dependency `get_db()` that yields an `AsyncSession`.

**Learnings**

- **`pool_pre_ping=True`** sends a cheap `SELECT 1` before handing out a pooled connection. Without it, if the DB restarts (or a connection idles out), the next query hits a "connection closed" error. Worth the small overhead.
- **`expire_on_commit=False`.** By default, SQLAlchemy invalidates loaded objects after commit, so accessing `trace.id` after `await session.commit()` would re-query the DB. In async FastAPI routes this would happen *outside* the session block, raising `MissingGreenlet`. Disabling expiration avoids that footgun.
- **`DeclarativeBase` (SQLAlchemy 2.0 style)** gives typed `Mapped[...]` columns. The old style was `Base = declarative_base()` — still works, but typing is worse.
- **One engine per process, one session per request.** Engines are expensive (they hold the pool). Sessions are cheap and represent a "unit of work" — they hold pending inserts/updates until you commit.

**Interview questions**

1. What's the lifecycle of a SQLAlchemy session? When does it commit vs flush? *(flush = send SQL but stay in transaction; commit = persist + end transaction)*
2. Why use a connection pool at all? *(TCP + auth handshake per query is expensive; Postgres `max_connections` is finite — defaults to 100)*
3. What happens if you `await session.commit()` and then access an attribute on an ORM object — and how do you avoid the trap? *(`expire_on_commit=False`)*

---

## Sub-step C — `models.py`: the 5 ORM models

**What changed**

- Created `server/app/models.py` with `Project`, `ApiKey`, `Trace`, `Span`, `Replay`, mirroring the schema in CLAUDE.md.
- Indexes: `idx_traces_project_started` on `(project_id, started_at DESC)`, `idx_spans_trace` on `trace_id`, `idx_spans_parent` on `parent_span_id`, and an index on `api_keys.key_hash`.

**Learnings**

- **`metadata` is reserved on `Base`.** SQLAlchemy uses `Base.metadata` to hold the table catalog. If you declare a column literally named `metadata`, the ORM silently breaks. Workaround: name the Python attribute `extra_metadata` but keep the DB column name `metadata` via the first positional arg to `mapped_column("metadata", JSONB)`.
- **JSONB vs JSON in Postgres.** `JSONB` stores binary parsed JSON — slightly slower writes, much faster reads, and indexable with GIN. `JSON` is stringified text re-parsed on every access. Always pick JSONB unless you specifically need to preserve key order or whitespace.
- **Client- vs server-generated UUIDs.** `projects`, `api_keys`, `replays` use `server_default=func.gen_random_uuid()` because the server creates them. `traces` and `spans` have *no* default — the SDK generates the IDs client-side so it can build the full span tree locally before flushing in one batch. Idempotent on retry.
- **`ondelete="CASCADE"` on `spans.trace_id`.** Delete a trace → all its spans go too. Without this, orphan spans would point at a non-existent trace. Soft-delete (a `deleted_at` column) is an alternative if you need recovery, but for MVP cascade is simpler.
- **Composite index `(project_id, started_at DESC)`.** The dashboard's "list traces for a project, newest first" is the hottest query. This composite index serves it as a sorted scan with no separate sort step. **Column order matters:** equality filter first (`project_id`), then the range/sort column (`started_at`).
- **`String(16)` for `status` instead of a Postgres enum.** Enums are fast but painful to alter (adding a value needs `ALTER TYPE`). String + app-level validation is more flexible at MVP scale.
- **`from __future__ import annotations`** lets `Trace` reference `Span` in its `relationship` before `Span` is defined. Forward references — cleaner than wrapping types in string literals.

**Interview questions**

1. JSONB vs JSON vs separate columns — when do you pick each? *(JSONB for variable/queryable; separate columns for hot, indexed fields; JSON almost never)*
2. What's the cost of `ON DELETE CASCADE` on a hot table at scale? *(lock duration grows with row count; consider soft-delete or batched cleanup)*
3. Composite index `(a, b)` — when does it help, when does it not? *(helps for filter-on-a, filter-on-a-and-b, sort-on-b-with-a-filter; doesn't help for filter-on-b-alone)*
4. Server-generated vs client-generated UUIDs — when do you pick which? *(client = batch insert without round-trips, idempotency; server = simpler, no client trust required)*
5. Why is `metadata` a reserved name in SQLAlchemy? *(table catalog on the declarative base — name collision)*

---

## Sub-step D — Initialize Alembic (async template)

**What changed**

- Ran `alembic init -t async alembic` inside `server/`.
- Rewrote `alembic/env.py` to: add `server/` to `sys.path`, import `app.config.settings` and `app.models`, inject `settings.database_url` into the alembic config, set `target_metadata = Base.metadata`, and enable `compare_type=True`.
- Blanked out `sqlalchemy.url` in `alembic.ini` (single source of truth = `.env`).

**Learnings**

- **Async alembic template (`-t async`).** Default template is sync. Mixing async SQLAlchemy with a sync alembic env doesn't work cleanly. The async template uses `connection.run_sync(do_run_migrations)` to dispatch the migration ops onto a sync wrapper around the async connection.
- **`config.set_main_option("sqlalchemy.url", ...)`** injects the URL programmatically, so `alembic.ini` and `.env` don't need to be kept in sync. Single source of truth.
- **Importing `app.models` in env.py is mandatory** (even though the name appears unused — annotate `# noqa: F401`). That import is what registers every `Trace`, `Span`, etc. class onto `Base.metadata`. Forget it, and autogenerate produces an empty migration.
- **`compare_type=True`.** Without it, alembic only diffs whether columns exist, not their types. With it, changing `Integer` → `BigInteger` gets detected. Occasionally generates spurious diffs (e.g. `Numeric(10,6)` vs `Numeric`) — worth knowing.

**Interview questions**

1. How does alembic autogenerate work — what does it detect, what does it miss? *(detects: tables, columns, indexes, constraints; misses: column renames (sees drop + add), check-constraint edits, enum value additions, some server-default forms)*
2. You add a NOT NULL column to a 50M-row table. What's your migration plan? *(three migrations: add nullable → backfill in batches → set NOT NULL)*
3. Why `NullPool` in alembic but a regular pool in the app? *(alembic runs short-lived migrations; no pool reuse benefit, and `NullPool` cleans up faster)*

---

## Sub-step E — Generate + apply the first migration

**What changed**

- Ran `alembic revision --autogenerate -m "initial schema"` → produced `alembic/versions/b6bf6f6b52ed_initial_schema.py`.
- Ran `alembic upgrade head` → applied the migration.
- Verified in Postgres: 5 application tables + `alembic_version`, JSONB columns intact, composite DESC index intact, FK with CASCADE intact.

**Learnings**

- **`alembic_version` table.** Alembic creates this automatically. It holds one row with the current revision hash. `upgrade` won't re-run a migration whose hash is already there — that's the safety net.
- **Always review autogenerated migrations before applying.** Alembic is good but not perfect. The line "please adjust!" in the file isn't a joke. It sometimes generates redundant `op.alter_column` calls, occasionally misses subtle FK options across versions, and sees renames as drop + add.
- **Transactional DDL in Postgres.** Postgres lets you wrap DDL in a transaction, so if a migration fails midway it rolls back atomically. MySQL famously does *not* — half-applied migrations there leave you in a hand-cleanup mess.

**Interview questions**

1. What does the `alembic_version` table do? What happens if you drop it? *(loses migration history; recover with `alembic stamp head` to re-mark the current state)*
2. Postgres has transactional DDL — what's the operational implication vs MySQL? *(safer rollback; can wrap migration + data backfill in one transaction)*
3. You're handed an unfamiliar repo — what's the first command you run to understand its schema state? *(`alembic current` to see applied revision, `alembic history` to see the full chain)*

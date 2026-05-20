# CLAUDE.md — Loupe

> This file is read by Claude Code at the start of every session. Keep it updated as the project evolves.

---

## What is Loupe?

Loupe is an open-source observability + replay tool for LLM agents.

**One-line description:** Instrument your agent with 3 lines of Python, see every trace in a dashboard, then replay any trace with a different prompt or model and compare outputs side-by-side.

**The killer demo (North Star — every decision serves this):**
A buggy agent fails on a query → open Loupe dashboard → see the trace → spot the wrong tool call → hit "Replay" with a tweaked prompt → side-by-side diff shows original (failed) vs new (working) run.

If a feature doesn't make this demo better or cleaner, it's out of scope for now.

---

## Current Build Status

Update this checklist as you go:

- [x] Repo initialized, monorepo structure set up
- [x] docker-compose.yml with Postgres running
- [x] FastAPI app with /health endpoint
- [x] Alembic migrations, 4-table schema applied
- [x] POST /v1/traces ingestion endpoint
- [x] GET /v1/traces list endpoint
- [x] GET /v1/traces/{id} detail endpoint
- [x] API key auth on all endpoints
- [x] SDK: @loupe.trace decorator working
- [x] SDK: loupe.span() context manager working
- [x] SDK: OpenAI auto-instrumentation
- [x] SDK: Anthropic auto-instrumentation
- [x] SDK: Groq auto-instrumentation
- [x] SDK: batched async flush with retry
- [x] Dashboard: traces list page
- [x] Dashboard: trace detail with span tree
- [x] Dashboard: replay UI (modify prompt/model, re-run)
- [x] Dashboard: side-by-side diff view
- [ ] Sentry + structlog integrated
- [ ] Deployed: Vercel (dashboard) + Render (server) + Neon (Postgres)
- [ ] Demo data seeded on live instance
- [ ] README complete with screenshots and architecture diagram
- [ ] examples/cinerater agent instrumented with Loupe

---

## Monorepo Structure

```
loupe/
├── sdk/                          # Python SDK — published to PyPI as 'loupe-sdk'
│   ├── loupe/
│   │   ├── __init__.py           # exports: trace, span, init
│   │   ├── core.py               # @trace decorator, span() context manager
│   │   ├── client.py             # HTTP client: batches + flushes to server
│   │   ├── models.py             # Pydantic schemas for trace/span wire format
│   │   └── integrations/
│   │       ├── openai.py         # wraps openai.ChatCompletion / client.chat.completions
│   │       ├── anthropic.py      # wraps anthropic.Anthropic.messages.create
│   │       └── groq.py           # wraps groq.Groq.chat.completions.create
│   ├── tests/
│   └── pyproject.toml
├── server/                       # FastAPI backend
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── traces.py         # CRUD for traces
│   │   │   ├── spans.py          # read spans by trace
│   │   │   └── replays.py        # create replay, get replay result
│   │   ├── models.py             # SQLAlchemy ORM models
│   │   ├── schemas.py            # Pydantic request/response schemas
│   │   ├── db.py                 # async engine, session factory
│   │   └── auth.py               # API key verification
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── dashboard/                    # Next.js 14 frontend
│   ├── app/
│   │   ├── page.tsx              # traces list
│   │   ├── traces/[id]/page.tsx  # trace detail + span tree
│   │   └── replays/[id]/page.tsx # side-by-side replay diff
│   ├── components/
│   │   ├── SpanTree.tsx          # recursive span tree component
│   │   └── ReplayDiff.tsx        # side-by-side diff component
│   └── ...
├── examples/
│   └── cinerater/                # stripped-down CineRater agent instrumented with Loupe
├── docker-compose.yml            # Postgres + server (dashboard runs separately in dev)
├── CLAUDE.md                     # this file
└── README.md
```

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| SDK | Pure Python, httpx, pydantic | Minimal deps, async-safe, no heavy dependencies for users |
| Backend | FastAPI + SQLAlchemy 2.0 async | Developer knows it well, production-proven pattern |
| Migrations | Alembic | Use from day 1, never skip. Migration history matters. |
| Database | PostgreSQL with JSONB columns | Variable span structure handled cleanly, free on Neon |
| Frontend | Next.js 14 (App Router) + Tailwind + shadcn/ui | Developer knows React/Next, App Router is current standard |
| Span tree viz | Custom recursive React component | react-flow is overkill, custom gives full control |
| Auth | API key via X-API-Key header, hashed in DB | Single-user MVP, no login flow needed |
| Deployment | Vercel (frontend) + Render (backend) + Neon (Postgres) | All free-tier, total ~₹0-400/month |
| Error tracking | Sentry free tier | Real error data = real resume metrics |
| Logging | structlog (structured JSON logs) | Queryable logs, not plain text |
| CI/CD | GitHub Actions | Free for public repos |

---

## Database Schema

```sql
-- Namespace for multi-app setups
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- SDK authentication
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    key_hash TEXT NOT NULL,           -- hash the raw key, never store it
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- One row per end-to-end agent run
CREATE TABLE traces (
    id UUID PRIMARY KEY,              -- generated by SDK, not server
    project_id UUID REFERENCES projects(id),
    name TEXT,                        -- e.g. "movie_search_agent"
    status TEXT,                      -- 'success' | 'error' | 'running'
    input JSONB,
    output JSONB,
    error JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER,
    total_tokens INTEGER,
    total_cost_usd NUMERIC(10, 6),
    metadata JSONB,                   -- user-defined tags, arbitrary key-value
    is_replay BOOLEAN DEFAULT FALSE,
    replay_of_trace_id UUID REFERENCES traces(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_traces_project_started ON traces(project_id, started_at DESC);

-- Individual operations within a trace (LLM calls, tool calls, functions)
CREATE TABLE spans (
    id UUID PRIMARY KEY,              -- generated by SDK
    trace_id UUID REFERENCES traces(id) ON DELETE CASCADE,
    parent_span_id UUID REFERENCES spans(id),  -- null = root span
    type TEXT NOT NULL,               -- 'llm' | 'tool' | 'function' | 'retrieval'
    name TEXT NOT NULL,               -- e.g. 'openai.chat' or 'search_movies'
    input JSONB,
    output JSONB,
    error JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER,
    -- LLM-specific (null for non-LLM spans)
    model TEXT,
    provider TEXT,                    -- 'openai' | 'anthropic' | 'groq' | 'gemini'
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd NUMERIC(10, 6),
    metadata JSONB
);
CREATE INDEX idx_spans_trace ON spans(trace_id);
CREATE INDEX idx_spans_parent ON spans(parent_span_id);

-- Diff metadata for a replay comparison
CREATE TABLE replays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_trace_id UUID REFERENCES traces(id),
    new_trace_id UUID REFERENCES traces(id),  -- the replayed run (also in traces table)
    modifications JSONB,              -- {prompt_override: "...", model_override: "groq/llama3"}
    diff_summary JSONB,               -- {token_delta, latency_delta, output_similarity_score}
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## MVP Scope

### IN scope
- Python SDK: `@loupe.trace` decorator and `loupe.span()` context manager
- SDK auto-instrumentation for OpenAI, Anthropic, Groq (wrapping their client methods)
- SDK batches spans and flushes async on trace end + on process exit
- FastAPI server: ingest traces/spans, query endpoints, replay trigger
- Postgres storage (JSONB for span payloads)
- Simple API key auth
- Dashboard: paginated traces list with status + duration + token count
- Dashboard: trace detail page showing span tree (type, name, latency, tokens, input/output)
- Dashboard: replay UI — pick a trace, override prompt or model, trigger re-run
- Dashboard: side-by-side diff (original output vs replay output, token delta, latency delta)
- Docker Compose for self-hosted local setup
- GitHub Actions CI (lint, test, build)

### BRUTALLY OUT — do not implement, do not suggest
- Multi-user, teams, organisations, RBAC
- SSO, login/signup flow, email verification
- Slack, Discord, email, webhook alerts
- JavaScript, Go, or any non-Python SDK
- WebSocket realtime streaming (polling every 2s is fine)
- Custom dashboards, saved views, filters
- Eval dataset management UI
- ClickHouse, Redis, or any additional data stores
- Hosted/cloud version — self-hosted only for now
- Billing, usage limits, subscription tiers
- Beautiful design — clean and functional is the target

---

## Key Design Decisions and Tradeoffs

These come up in interviews. Know the reasoning.

**Postgres over ClickHouse:**
ClickHouse is the production-correct answer for trace data at scale (columnar, optimised for time-series writes and aggregations). Postgres is simpler to operate for a single developer and handles millions of rows with proper indexes. Migration path is clean. Mention both in interviews.

**Flat LLM fields on spans table (not a separate llm_spans table):**
Polymorphic tables (single-table inheritance) mean NULL columns for non-LLM spans. Separate tables mean joins on every trace read. For 4 span types at MVP scale, flat + NULL is the right tradeoff. Revisit if span types grow past ~10.

**SDK generates trace and span IDs (not server):**
Client-generated UUIDs allow the SDK to build the full span tree locally and send it in one batch, instead of requiring round-trips to get server-assigned IDs for each span. Idempotent on re-delivery.

**Replayed runs live in traces table:**
A replay is structurally identical to a regular trace — same schema, same query patterns. Treating them uniformly means the trace detail page works for replays for free. The `replays` table holds only the diff metadata.

**BackgroundTasks over Celery/Redis for replay jobs:**
FastAPI BackgroundTasks is sufficient for MVP. Adding a message broker adds operational complexity that isn't justified until there's real concurrency. Mention you'd migrate to Celery + Redis at scale.

---

## v2 Roadmap: From Observability to Replay-Driven Prompt Testing

> **Strict order:** finish MVP (items 16–22) first. v2 depends on the trace detail UI, replay infrastructure, and diff view being solid.

The MVP proves end-to-end shipping. v2 is what makes Loupe a different category from LangFuse / LangSmith / Helicone — not "another observability tool" but **"replay-driven prompt testing for LLM agents."**

### v2.1 — Time-Travel Debug

**Pitch:** Pause a trace at any span, override that span's output, resume from there. See the counterfactual run side-by-side with the original.

**User flow:**
1. Open a failed trace in the dashboard
2. Click any span → "Branch from here"
3. Edit the span's output (textarea for LLM responses, JSON editor for tool results)
4. Hit Continue → server re-executes downstream spans with the override
5. New trace appears, linked to original via `branched_from_span_id`

**Tech sketch:**
- DB: `branched_from_span_id UUID REFERENCES spans(id)` on `traces`
- Server: `POST /v1/traces/{trace_id}/branch` taking `{span_id, new_output}`, kicked off via BackgroundTask
- SDK: "deterministic replay" mode — for spans before the branch point, replay stored outputs from the original trace; for spans at/after the branch point, execute live with the new value
- Dashboard: per-span "Branch from here" button on trace detail; diff route comparing branched vs original from the branch point onward

**Killer demo:** Agent failed because it called `search_actors` instead of `search_movies`. Click the bad span → paste correct `search_movies` output → Continue. New trace succeeds. Side-by-side shows what *should* have happened.

**Why no incumbent ships this well:** It requires deterministic replay from day 1 — i.e. capturing exact tool call inputs. That's an architectural commitment most observability tools didn't make. Loupe captures it from the start.

### v2.2 — Prompt CI/CD

**Pitch:** Prompts are code. PRs that touch a prompt run a regression suite against saved production traces. PR comment with pass/fail. Block merge on regression.

**User flow:**
1. Curate a "golden suite" — collection of traces (manually marked or auto-sampled)
2. Install `loupe-action` (GitHub Action) in the consuming repo
3. PR touches a prompt file → action triggers
4. Action calls `POST /v1/suites/{id}/run` with the new prompt
5. Loupe replays each trace in the suite against the new prompt; judge LLM scores each as `equivalent` / `regressed` / `improved`
6. Action posts a PR comment: **"✓ 95/100 passed. 5 regressions. [View diffs]"**
7. PR status check: green/red, configurable to block merge

**Tech sketch:**
- DB: `suites` (collection of trace IDs); `suite_runs` (one row per execution with pass/fail counts + per-trace results JSONB)
- Server: `POST /v1/suites`, `POST /v1/suites/{id}/run`, `GET /v1/suite_runs/{id}`
- `JudgeService`: takes (original_output, new_output, original_input) → Claude/GPT-4 prompt → classification + reasoning
- GitHub Action: small TS action, reads PR diff, finds changed `.txt`/`.md`/`.prompt` files, calls Loupe API, posts PR comment via the GitHub API
- Dashboard: `/suites` list, `/suites/{id}` detail with run history, `/suite_runs/{id}` view with per-trace pass/fail rows linking to existing diff view

**Killer demo:** Live GitHub PR → action runs in 30 seconds → comment shows 5 regressions → click "View diffs" → land in Loupe dashboard with the 5 failed traces side-by-side.

**Why this is portfolio-strong:** It's an end-to-end loop (production trace → saved as test → run on every PR → block bad merges). That's systems thinking, not "I built a dashboard."

### v2.3 — Regression Suite CLI (foundation under v2.2)

Same suite infrastructure as v2.2, exposed via Python CLI for non-GitHub workflows:

```
loupe suite create --from last:100              # snapshot last 100 prod traces
loupe suite run <suite_id> --prompt new.txt     # replay with new prompt
loupe suite diff <run_id_a> <run_id_b>          # compare two runs
```

Most teams will use this directly. v2.2 is the GitHub wrapper on top of the same primitives.

### v2 Build Checklist

- [ ] DB migration: `branched_from_span_id` on traces; `suites` and `suite_runs` tables
- [ ] Server: deterministic replay engine (replay stored span outputs up to a branch point)
- [ ] Server: `POST /v1/traces/{id}/branch` endpoint
- [ ] Server: `JudgeService` with Claude/GPT-4 backend
- [ ] Server: suite + suite_run CRUD endpoints
- [ ] Dashboard: per-span "Branch from here" on trace detail
- [ ] Dashboard: `/suites` and `/suite_runs/{id}` pages
- [ ] CLI: `loupe suite create/run/diff` commands
- [ ] GitHub Action: `loupe-action` repo, PR comment poster, status check
- [ ] Demo repo: a sample agent with a "golden suite" wired up, showing the full PR-blocking flow

### Still Out of Scope (even for v2)

- Multi-tenant SaaS / billing
- Auto-fix suggestions (interesting, separate concern)
- Native eval dataset management UI (suites replace this)
- Realtime streaming / WebSockets (polling is still fine)

---

## Code Conventions

- Python: type hints on all function signatures, Pydantic models for all request/response schemas
- Async throughout the server (async def routes, async SQLAlchemy sessions)
- FastAPI routers split by domain: one file per resource (traces, spans, replays)
- No premature abstraction — write the obvious thing first, refactor when the pattern is clear
- SQLAlchemy models in `models.py`, Pydantic schemas in `schemas.py` — keep these separate
- Alembic for all schema changes — never alter tables manually in production
- Structured logging with structlog, not print statements
- Secrets via environment variables, never hardcoded — use a `.env` file locally, load with `python-dotenv`

---

## Environment Variables

```
# server/.env
DATABASE_URL=postgresql+asyncpg://loupe:loupe@localhost:5433/loupe
SECRET_KEY=your-secret-key-here
SENTRY_DSN=                     # add after Sentry project created
ENVIRONMENT=development

# sdk (set by user in their project)
LOUPE_API_KEY=lp_...
LOUPE_HOST=http://localhost:8000
```

---

## Context: Why This Project Was Built

Built by Aditya Chauhan as a portfolio project during a job search sprint (May 2026). The goal is to demonstrate production backend thinking, LLM systems understanding, and open-source dev tools work to hiring teams at well-funded Indian startups (Razorpay, CRED, Postman, Zerodha, Sarvam) and big tech India.

The project is intentionally scoped to show:
- Backend systems depth (async FastAPI, proper schema design, indexing decisions)
- LLM infrastructure understanding (instrumentation, token tracking, cost, replay)
- Dev tools instincts (good SDK ergonomics, easy self-host, clear README)
- Production habits (Sentry, structured logging, CI/CD, real metrics)

---

## Sprint Tracker

For high-level decisions, resume work, architecture reviews, and mock interview prep:
Use the claude.ai chat interface (not Claude Code).

Bring the sprint_tracker.md to those sessions for specifics.
Claude Code (this environment) is for file-level work: writing code, debugging, running tests, editing files.
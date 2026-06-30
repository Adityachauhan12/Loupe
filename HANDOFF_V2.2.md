# Loupe v2 — Session Handoff for v2.2 (Prompt CI/CD: suites + judge + GitHub Action)

> Paste this file's path into the new chat and say:
> "Read HANDOFF_V2.2.md and continue. We're starting v2.2 — Prompt CI/CD. Teach as
> you build, one sub-step at a time, test rigorously, Hinglish."
> Written 2026-06-30. Repo is on `main`, fully pushed (head `8a8f667`).

---

## 1. What Loupe is (30-second version)

Loupe = observability + **replay/branch debugger** for LLM agents. MVP is live
(SDK on PyPI, dashboard on Vercel, server on Render, Postgres on Neon).

**v2 framing:** a *debugger for non-deterministic agents* — open a failed trace →
click the span that went wrong → edit it → branch → re-run from there →
**side-by-side diff** of original vs counterfactual.

Full spec: [CLAUDE.md](CLAUDE.md). Every architectural decision (with rationale +
tradeoffs) is in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) — **read it,
it's the single source of truth for the "why".** Demo runbook: [DEMO.md](DEMO.md).

---

## 2. How the user likes to work (IMPORTANT — match this)

- **Teach as you build:** narrate steps in plain language, drop learnings, surface
  interview Q&A. This is a **portfolio/learning** sprint.
- The user writes in **Hinglish** ("samjhaao", "simple words mein"). Answer in the
  same simple style, with small analogies.
- **One sub-step at a time. Test rigorously as you go** (write tests *with* the code).
  Confirm before moving on.
- Be **direct and honest** — if something is wrong or limited, say so plainly. (The
  best features in this project came from admitting a limitation out loud.)
- After meaningful work: write a **`notes/NN-*.md`** file (plain language + interview
  Q&A), update `notes/README.md` index, then **commit**.
- Use a **TodoWrite** list to track sub-steps.
- Commit footer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- We commit straight to **`main`** (the user's established pattern). Push only when
  the user asks.
- For architectural decisions: lay out *tension → options → tradeoffs → recommendation
  → "Decision needed"*, get the user's pick, record it in
  [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md), then build.

---

## 3. Where we are — v2 progress

| Piece | Status |
|-------|--------|
| **v2.1 — Time-Travel Debug (branch + diff)** | ✅ **DONE & pushed** |
| ↳ branch lineage migration, server `_run_branch`, SDK `loupe.replay` + CLI | ✅ |
| ↳ `POST /v1/traces/{id}/branch`, per-span "Branch from here" UI | ✅ |
| ↳ **Phase 7 branch-vs-original diff view** (status banner, deltas, per-span pairs) | ✅ |
| ↳ explicit `replay_mode` column + `replays`-row consistency + B7 key guard | ✅ |
| **Track D — demo polish** | ⬜ video pending; screenshots ✅; URLs ✅ |
| **v2.2 — Prompt CI/CD (suites + judge + GitHub Action)** | ⬅️ **NEXT** |

**Tests all green:** server **65**, SDK **30**, dashboard `tsc` + `npm run build` ✅.

### This session's commits (newest → oldest)
- `8a8f667` refresh screenshots (new UI + 3-shot branch-diff spotlight)
- `7a0df95` remove stale handoff docs + V2_CHECKLIST (superseded)
- `078e162` add DEMO.md runbook
- `a0d87e7` sync CLAUDE.md v2 checklist with reality
- `5a83597` mark build backlog implemented
- `d08e89b` label server-side branch as "LLM-only preview" + replay-guarantee docs
- `28dd046` dashboard: branch kind from stored `replay_mode` + cost caveat
- `adc7c5c` tag branch `replay_mode` + B7 guard for server-side LLM replay
- `c13ccb4` `replay_mode` column + auto-create `replays` row on branch ingest
- `3adb3c2` resolve architecture blockers B2–B7 + B10 + build backlog
- `21335c1` Phase 7 notes (notes/26, incl. the stale-server debugging story)
- `f4b6394` ARCHITECTURE_DECISIONS log + B1 decision (control/execution plane)

---

## 4. Architecture decisions already locked (read the doc for full reasoning)

All in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md). The load-bearing ones:

- **B1 — two kinds of replay.** SDK-side `loupe.replay` is the **canonical product**
  (runs in the user's process, real tools re-run, edit propagates). Server-side branch
  (dashboard button) is an honestly-labeled **"LLM-only preview"** (server can't run
  user tool code — control plane vs execution plane). **B10** records the future
  "embedded outbound worker" path (like a self-hosted CI runner) as *planned, deferred*.
- **B2 — `branched_from_*` columns are the lineage source of truth.** Every branch
  (server + SDK) gets a `replays` row; the **server auto-creates it at ingest** when a
  trace arrives with `branched_from` set and no row exists.
- **B3 — explicit `traces.replay_mode`** (`'server' | 'sdk' | null`), set at branch
  creation. The diff reads it; marker-inference is only a fallback for old rows.
- **B5** — blended branch token/cost totals are kept honest with a caveat note.
- **B6** — replay is faithful only for *captured* state (seed/temperature/span I/O);
  un-instrumented external state (time, RNG, live reads) is best-effort. Documented.
- **B7** — `ALLOW_SERVER_SIDE_LLM_REPLAY` flag; off ⇒ post-branch LLM spans pass through
  stored output (no operator key spend on shared deployments).

---

## 5. v2.2 — what to build (the spec)

From [CLAUDE.md](CLAUDE.md) → "v2.2 Prompt CI/CD". **Pitch:** prompts are code; a PR that
changes a prompt runs a regression suite against saved production traces; a judge LLM
scores each replay vs original; PR comment + status check block bad merges.

It builds on primitives that **already exist**: the replay engine (re-run a trace with a
new prompt) and the diff view. v2.2 = "replay *many* traces + auto-judge + wrap in GitHub".

### Build checklist (CLAUDE.md v2.2)
- [ ] DB: `suites` (collection of trace IDs) + `suite_runs` (one row per run: pass/fail
      counts + per-trace results JSONB)
- [ ] Server: **`JudgeService`** (Claude backend) — scores `equivalent | improved | regressed`
- [ ] Server: `POST /v1/suites`, `POST /v1/suites/{id}/run`, `GET /v1/suite_runs/{id}`
- [ ] Dashboard: `/suites` list, `/suite_runs/{id}` detail (per-trace rows → existing diff view)
- [ ] CLI: `loupe suite create --from last:100`, `loupe suite run <id> --prompt new.txt`,
      `loupe suite diff <a> <b>`
- [ ] GitHub Action: `loupe-action` (TS) — reads PR diff, finds changed prompt files,
      calls the API, posts a PR comment + status check
- [ ] Demo repo: a sample agent with a "golden suite" wired up, PR-blocking flow

**Recommended order:** DB + JudgeService + suite endpoints + CLI first (the engine),
then the GitHub Action (a thin wrapper on top). Discuss with the user before starting —
they like designing the sub-step.

### Open architecture questions for v2.2 (raise these as B-items before coding)
- Suite storage shape: store trace **IDs** (snapshot by reference) vs copy trace data?
- `suite_runs.results` JSONB shape (per-trace: verdict, reasoning, confidence, new_trace_id)?
- How a PR maps to a "prompt change" (which files count; how the new prompt is passed)?
- Judge rubric: global vs per-suite?

---

## 6. The scoring design (already discussed in depth — carry this in)

We worked through **how the JudgeService should score** original-vs-new output. The
spectrum, cheap → smart:

1. **Exact match** — useless for free-text (LLM non-determinism breaks it).
2. **Regex / assertions** — perfect for **structured/tool** outputs (e.g. cinerater's
   parse-LLM emits `{"genre": "Sci-Fi"}` → assert `genre == expected`). Deterministic,
   free. Can't judge *meaning* of free-text.
3. **Embedding similarity** — gives "how similar", not "better vs worse" direction.
4. **LLM-as-judge (Claude)** — the real answer: a second Claude call scores the semantic
   verdict + reasoning. This is `JudgeService`.

**Decision direction (confirm with user, then record as a B-item):** use a **hybrid** —
cheap deterministic checks on structured/tool spans first, **Claude judge only for the
free-text final answer**, driven by an explicit **rubric** (gradeable criteria, not "vibes").

### Claude judge — concrete shape (server is Python/FastAPI → `anthropic` SDK)
- Model: **`claude-opus-4-8`** (the project default; per the claude-api skill).
- **Structured output** so the verdict is guaranteed-valid JSON — Python:
  `client.messages.parse(..., output_format=Verdict)` with a Pydantic model
  `Verdict{label: Literal["equivalent","improved","regressed"], reasoning: str, confidence: float}`.
- `thinking={"type": "adaptive"}` (let it reason before the verdict).
- **Cost levers for a 100-trace suite:** the **Batch API**
  (`client.messages.batches.create`, ~50% cheaper, results in ~1h — fine for suite runs)
  and **prompt caching** on the shared rubric/system prompt (`cache_control: ephemeral`,
  ~90% cheaper per judgment).
- ⚠️ When writing any Claude/Anthropic code, **invoke the `claude-api` skill first** —
  the API drifted (adaptive thinking, `output_config.format`, removed `budget_tokens`);
  don't write from memory.

**Interview line:** *exact-match breaks on non-determinism; embeddings give similarity
not direction; LLM-as-judge with a rubric + structured output gives a semantic,
directional verdict, and Batch + prompt-caching keep cost sane.*

---

## 7. Environment & gotchas (saves the new chat real time)

- **Python: use `python3.11`** for everything (pip, pytest, alembic, uvicorn). Bare
  `python3` is 3.13 and lacks deps. `alembic` isn't on PATH → `python3.11 -m alembic`.
- **Local Postgres:** `docker compose up -d db` (service `db`, container `loupe-db`,
  port **5433**). Two DBs: `loupe` (dev) and `loupe_test` (tests).
- **Run server:** from `server/`,
  `SENTRY_DSN="" ENVIRONMENT=development python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **Run server tests:** from `server/`, `SENTRY_DSN="" python3.11 -m pytest tests/ --timeout=30 -q`
  → **65 passing**. (conftest now `drop_all`+`create_all`, so a new column no longer
  silently breaks the suite.)
- **Run SDK tests:** from `sdk/`, `python3.11 -m pytest tests/ -q` → **30 passing**.
- **Dashboard:** from `dashboard/`, `npm run dev` (port **3000**). Verify with
  `npx --no-install tsc --noEmit` and `npm run build` (Next 16 + Turbopack, React 19,
  App Router, server components/actions; plain Tailwind, dark theme).
- **Dashboard env:** `dashboard/.env.local` has `LOUPE_API_URL=http://localhost:8000` and
  a `LOUPE_API_KEY` (this key's project has the branchable test data).
- **⚠️ Stale-server trap (cost us an hour last session):** a long-lived `uvicorn` keeps
  serving **old code**. When behaviour contradicts the source, **restart the server before
  deep-diving.** Binary-search the pipeline (SDK → wire → server → DB); prove each hop.
- **Timestamps** in the dashboard are forced to IST (`Asia/Kolkata`).
- **Render free tier sleeps** (~15 min) — wake with `curl <render-url>/health`.

### Make a fresh SDK-side branch (for testing replay/diff)
```bash
cd /Users/adityachauhan/Desktop/Loupe_Project
LKEY=$(grep LOUPE_API_KEY dashboard/.env.local | cut -d= -f2 | tr -d '"' | tr -d ' ')
GKEY=$(grep '^GROQ_API_KEY' server/.env | cut -d= -f2 | tr -d '"' | tr -d ' ')
LOUPE_HOST=http://localhost:8000 LOUPE_API_KEY="$LKEY" GROQ_API_KEY="$GKEY" \
  python3.11 -m examples.cinerater.agent "recommend a sci-fi movie"
# get TID + first llm SID from GET /v1/traces, then:
GROQ_API_KEY="$GKEY" python3.11 -m loupe.cli replay \
  --agent examples.cinerater.agent:recommend --trace <TID> --span <SID> \
  --output '{"content": "{\"genre\": \"Comedy\"}"}' \
  --api-key "$LKEY" --host http://localhost:8000
```
(`loupe` isn't a global command; use `python3.11 -m loupe.cli`. The editable install runs
local `sdk/loupe/...`.)

---

## 8. Quick file map

- `server/app/models.py` — SQLAlchemy ORM (Trace has `replay_mode`, `branched_from_*`);
  add `Suite` / `SuiteRun` here for v2.2.
- `server/app/schemas.py` — Pydantic request/response.
- `server/app/routers/traces.py` — ingest (auto-creates `replays` row), branch endpoint.
- `server/app/routers/replays.py` — `_run_branch` engine, `_invoke_llm`, cost table, B7 gate.
- `server/app/config.py` — settings (`allow_server_side_llm_replay`, provider keys).
- `server/alembic/versions/` — migrations (latest `d4a1c2e3f5b6` = `replay_mode`).
- `sdk/loupe/core.py` (`replay()`), `_replay.py`, `cli.py`, `models.py`, `integrations/`.
- `dashboard/lib/diff.ts` — `alignFromBranch()` pure helper (+ `resolveKind`).
- `dashboard/components/BranchDiff.tsx`, `app/traces/[id]/diff/page.tsx` — the diff view.
- `dashboard/lib/api.ts` — typed API client (`TraceDetail` has `replay_mode`).
- `notes/` — one file per build item + interview Q&A (latest `26-branch-diff-view.md`).
- `examples/cinerater/` — the instrumented demo agent (25 hardcoded movies in `data.py`).

---

## 9. First message to send in the new chat

> "Read HANDOFF_V2.2.md and continue. We're starting v2.2 — Prompt CI/CD (suites +
> JudgeService + GitHub Action). Before coding, walk me through the v2.2 design
> decisions (suite storage, suite_run shape, judge rubric, hybrid scoring) as B-items
> so we lock them in ARCHITECTURE_DECISIONS.md first. Teach as you build, one sub-step
> at a time, test rigorously, Hinglish."

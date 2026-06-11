# Loupe v2 — Session Handoff (for a fresh chat)

> Paste this file's path into the new chat and say "read HANDOFF.md and continue."
> Written 2026-06-11. Covers everything needed to pick up Phase 4 (the replay engine).

---

## 1. What Loupe is (30-second version)

Loupe = observability + replay for LLM agents. MVP is 100% done and live
(SDK on PyPI, dashboard on Vercel, server on Render, Postgres on Neon).

**We are now building v2 — reframed as "a debugger for non-deterministic agents"**
(think `rr` / time-travel debugging, but for LLM agents). The killer feature:
open a failed trace → click the span that went wrong → edit it → "Branch from
here" → replay re-executes downstream from that point → side-by-side diff shows
the counterfactual run. No competitor (Langfuse, LangSmith, Helicone, Braintrust)
does mid-trace branching replay — that's the wedge.

Full project context is in [CLAUDE.md](CLAUDE.md). The v2 plan is in
[V2_CHECKLIST.md](V2_CHECKLIST.md).

---

## 2. Why we're building it (the user's goals — keep these in mind)

- **Primary:** solve a *real* problem (agent failures are impossible to reproduce
  because runs are non-deterministic + the world moved on). Money is secondary.
- Build with **production rigor**: solid infra, CI/CD, system design, real tests.
- **Learn deeply** along the way — the user wants to understand systems, not just
  ship. They keep interview-prep notes in `notes/` (one file per checklist item)
  and want concepts explained simply with examples.
- Be **direct and honest** with them. If their input is wrong, say so. They
  explicitly asked for this.

This is a portfolio project for a job search (well-funded Indian startups + big
tech India). User is Aditya Chauhan.

---

## 3. How we work together (process the user likes)

- **Teach as you build:** narrate steps, drop learnings, surface interview Qs.
- Go **one sub-step at a time**, confirm before moving on.
- After meaningful work: **write a notes/ file** in plain language with examples
  + interview Q&A, update notes/README.md index, commit + push.
- Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  (or the Sonnet line when on Sonnet — match the model in use).
- The user often works in Hindi/Hinglish ("samjhaao", "kya karna hai") — answer
  in the same simple style when they do.

---

## 4. Where we are — progress through V2_CHECKLIST.md

| Phase | Status | What was done |
|-------|--------|---------------|
| **0 — Validation** | ✅ DONE | Built `examples/github-triage/` agent. Ran it, hit the "I can't reproduce this failure" wall firsthand. Problem confirmed real. (Skipped the "talk to 5 builders" step — user's goal is learning/portfolio, being own user was enough.) |
| **1 — Capture audit** | ✅ DONE | Found + fixed 2 capture gaps. SDK now v0.2.0 on PyPI. |
| **2 — Design docs** | ✅ DONE | 3 design docs in `docs/`. |
| **3 — DB migrations** | ✅ DONE | Added branch lineage + replay_policy columns. Applied to local + Neon. |
| **Server test suite** | ✅ DONE | 44 tests (was zero). Found 2 real bugs. CI runs them now. |
| **4 — Replay engine** | ⬅️ **NEXT** | The heart of v2. Not started. |
| 5 — Branch API endpoint | ⬜ | `POST /v1/traces/{id}/branch` |
| 6 — Dashboard "Branch from here" UI | ⬜ | |
| 7 — Branched-vs-original diff view | ⬜ | |

---

## 5. Key technical decisions already made (from docs/)

Read these three before coding Phase 4. They ARE the spec.

- **[docs/design-replay-side-effects.md](docs/design-replay-side-effects.md)** —
  During replay, every span is one of: *before branch* → use stored output;
  *at branch* → use user's edited output; *after branch* → re-execute BUT writes
  are **dry-run by default** (show "would post comment…", don't actually hit
  GitHub). Tools opt into live execution via `replay="live"`. Heuristic fallback:
  `llm`→live, `tool`→dry_run, `retrieval`/`function`→live. Unannotated agents are
  safe by default.

- **[docs/design-deterministic-replay.md](docs/design-deterministic-replay.md)** —
  "Deterministic" ≠ "LLM returns same output." It means **isolate the change**:
  freeze everything before the branch (use stored outputs), only re-run the branch
  span + downstream. That way any output change is provably caused by the edit
  (controlled experiment). Residual LLM variance after branch is best-effort
  (mitigated with captured seed + temperature=0).

- **[docs/design-branch-tree.md](docs/design-branch-tree.md)** — A branch is just a
  normal trace with two extra columns. Lineage = adjacency list. Branching a branch
  needs no special handling. Reuses the existing `replays` table for diff metadata.

Plain-language version of all three + interview Q&A:
**[notes/22-v2-replay-engine-design.md](notes/22-v2-replay-engine-design.md)**.

**One-liner that captures the whole engine:**
*"Freeze before the branch, re-run at and after it, dry-run the writes."*

---

## 6. The validation agent: examples/github-triage/

A GitHub issue-triage agent — our realistic test subject (CineRater was too clean).
- For each open issue: `classify_issue` (Groq LLM) → `add_label` → `post_comment`.
- `tools.py` has the 3 tools; `add_label`/`post_comment` are real GitHub **writes**
  (the side effects that motivate dry-run replay).
- Target repo: `Adityachauhan12/github-triage-test` (3 dummy issues: a bug, a
  feature, a question).
- `agent.py` calls `loupe.instrument_groq(client)` so the LLM call is captured.
- `.env` is filled (gitignored). To re-run: remove labels from the 3 issues on
  GitHub first (else it skips them), then `python3 agent.py`.

**The demo target for v2:** agent misclassifies an issue → branch at
`classify_issue` → fix prompt → replay → downstream re-runs, writes are dry-run →
diff shows the correct classification.

---

## 7. Current state of the replay code (IMPORTANT — there's already a v1 replay)

`server/app/routers/replays.py` ALREADY has a working **whole-trace** replay
(the MVP version): `POST /v1/replays` re-runs ALL llm spans with a prompt/model
override, copies non-llm spans as-is, writes a new trace. This is NOT the v2
branch replay.

**Phase 4 is different:** it adds **branch-point** replay — freeze before a chosen
span, re-run from that span onward, honor `replay_policy` (dry-run writes). The new
endpoint will be `POST /v1/traces/{trace_id}/branch` taking `{span_id, new_output}`.

Decision for the new chat: build the branch engine as a NEW path (new endpoint +
new engine function) that uses the `branched_from_trace_id` / `branched_from_span_id`
columns, rather than overloading the existing `/v1/replays`. Keep the v1 replay
working (it has tests). Reuse helpers (`_call_groq`, `_estimate_cost`, etc.).

---

## 8. DB schema additions already applied (Phase 3)

Migration `c3f8a21d9b04` (applied locally + on Neon):
- `traces.branched_from_trace_id` UUID FK → traces.id
- `traces.branched_from_span_id` UUID FK → spans.id (uses `use_alter` — circular FK)
- `spans.replay_policy` TEXT default `'dry_run'`  ('live' | 'dry_run')
- index `idx_traces_branched_from`

ORM models in `server/app/models.py` updated to match. **Note:** because of the
second FK between traces↔spans, `Trace.spans` and `Span.trace` relationships have
explicit `foreign_keys="[Span.trace_id]"` — don't remove that or loading traces
breaks.

---

## 9. Environment & gotchas (will save the new chat a lot of time)

- **Python:** use **`python3.11`** for everything (pip, pytest, alembic). The
  machine's bare `python3` is 3.13 and does NOT have the deps. `alembic` CLI isn't
  on PATH — use `python3.11 -m alembic`.
- **Local Postgres:** `docker compose up -d db` (service is named `db`, port 5433).
  Test DB is `loupe_test` (create with
  `docker exec loupe-db psql -U loupe -c "CREATE DATABASE loupe_test;"`).
- **Run server tests:** from `server/`,
  `SENTRY_DSN="" python3.11 -m pytest tests/ --timeout=30 -q`
  (Sentry's flush makes the process hang ~2s at exit; the `SENTRY_DSN=""` avoids it).
- **Neon (prod) DB URL** is in the user's Render env. To migrate prod:
  `DATABASE_URL=<neon-url> python3.11 -m alembic upgrade head` from `server/`.
- **Render free tier sleeps** after ~15 min. Wake it before using the live API:
  `curl https://loupe-server.onrender.com/health`.
- **Bash tool auto-backgrounds** long/ hanging commands — keep test runs fast and
  avoid trailing Sentry waits.
- Dashboard timestamps are forced to IST (`Asia/Kolkata`) because Vercel servers
  render in UTC.

---

## 10. Async testing lessons (so we don't re-fight them in Phase 4 tests)

Full story: **[notes/23-server-test-suite.md](notes/23-server-test-suite.md)**.
The short version:
- An **asyncpg connection is bound to the event loop that created it.** Fixture
  loop scope and test loop scope MUST match (we keep both function-scoped — do NOT
  set `asyncio_default_fixture_loop_scope`).
- Each test uses a **fresh NullPool engine**; cleanup `TRUNCATE … CASCADE` runs
  **inside the fixture's own loop**, then closes the session (release locks → no
  deadlock).
- **API tests that trigger a BackgroundTask must mock it** (`patch(
  "app.routers.replays._run_replay", AsyncMock())`) — otherwise the real task
  leaks a pooled connection into the next test's loop. Test the background job
  separately with `_call_groq` mocked.
- Test fixtures/factories live in `server/tests/conftest.py` (`client`,
  `unauthed_client`, `db`, `project`, `api_key`, `make_trace_payload`,
  `make_span_payload`, `make_engine`). Reuse these for Phase 4 tests.

---

## 11. Phase 4 plan (what to actually build next)

From V2_CHECKLIST.md, Phase 4 = the replay executor. Suggested order:
1. **Design the branch engine function** `_run_branch(...)` (new, alongside
   `_run_replay`): given (original_trace, branch_span_id, new_output):
   - sort spans by `started_at`;
   - spans before branch → copy stored output;
   - branch span → use `new_output`;
   - spans after branch → re-execute (llm live; tool/write → honor `replay_policy`,
     default dry-run = synthetic ghost span, no real call);
   - write a new trace linked via `branched_from_trace_id` + `branched_from_span_id`;
   - record a `replays` row for diff metadata.
2. **Write tests alongside** (TDD-ish), reusing conftest. Mock `_call_groq`.
   Cover: freeze-before, override-at-branch, dry-run write produces ghost span,
   live write path, failure marks error.
3. THEN Phase 5 (the `POST /v1/traces/{id}/branch` endpoint), 6 (UI), 7 (diff).

Remember the rule the user values: **don't build the engine before the design is
clear, and write tests with the code, not after.**

---

## 12. Quick file map

- `CLAUDE.md` — full project spec + v2 roadmap
- `V2_CHECKLIST.md` — the master checklist (Tracks A–D)
- `docs/design-*.md` — the 3 Phase-2 design docs (the spec for Phase 4)
- `server/app/routers/replays.py` — existing v1 whole-trace replay + reusable helpers
- `server/app/models.py` — ORM (has the new branch columns + explicit foreign_keys)
- `server/app/routers/traces.py` — ingest/list/get endpoints
- `server/tests/conftest.py` — test fixtures to reuse
- `examples/github-triage/` — the validation agent + demo target
- `notes/22-*.md`, `notes/23-*.md` — the v2 design + testing learning notes
- `sdk/loupe/core.py` — `@trace` + `span()` (now dual decorator/context-manager)

---

## 13. First message to send in the new chat

> "Read HANDOFF.md. We finished Phases 0–3 of V2_CHECKLIST plus the server test
> suite. Start Phase 4 — the branch replay engine. Teach as you build, one
> sub-step at a time, and we test rigorously as we go."

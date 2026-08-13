# Loupe — Session Handoff

> Written **2026-08-07**. Supersedes the 2026-07-08 handoff entirely.
> Paste this file's path into the new chat and say the message in §9.

---

## 1. What Loupe is (30 seconds)

Observability + **replay/branch debugger + prompt regression testing** for LLM agents.
Three layers, all shipped:

- **Observe** (MVP) — instrument an agent, see every trace/span.
- **Replay/branch** (v2.1) — open a failed trace → edit a span → re-run from there → diff.
- **Prompt CI/CD** (v2.2) — golden suites → replay against a new prompt → LLM judge → a
  GitHub Action that blocks PRs on regressions.

Spec: [claude.md](claude.md). Decisions + rationale: [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
Plain-language explainer: [docs/concepts-explained.md](docs/concepts-explained.md).

---

## 2. How the user likes to work (match this)

- **Teach as you build** — narrate in plain language, drop learnings, surface interview Q&A.
  This is a portfolio/learning sprint. User writes Hinglish; answer in simple English with
  small analogies.
- **One sub-step at a time. Test rigorously *with* the code.** Confirm before moving on.
  Use TodoWrite.
- **Be direct and honest** — flag limitations out loud. The best features came from that.
- Architecture decisions: *tension → options → tradeoffs → recommendation → "decision
  needed"* → get the pick → record in ARCHITECTURE_DECISIONS.md → build.
- Commit straight to `main`. **Push only when asked** (they have declined a push mid-session
  before). Footer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Zero-cost by default** — small API credit. Judge defaults to free Groq/Llama; Claude opt-in.

---

## 3. State of the repo

- Branch `main`, **ahead of origin by 1 commit**: `3e27508` (dashboard suites pages) — unpushed.
- Last pushed: `9cede77`.
- SDK: repo says **0.3.2**, PyPI serves **0.3.1**. 0.3.2 is unreleased and carries the
  U+2028 credential hardening.
- Tests green: **server 106**, **SDK 45**, ruff clean, dashboard lint+build clean.

### ⚠️ Uncommitted working tree — resolve before committing anything

```
 D docs/branch-diff-1.png … trace-detail.png, traces-list.png   (5 README screenshots DELETED)
D  docs/design-branch-tree.md                                    (staged delete, intentional)
?? docs/Loupe_Test_Tracker.xlsx                                  (the test tracker — keep!)
?? "Screenshot 2026-07-01 at ….png" x2                           (root, not gitignored)
```

**The 5 PNG deletions are unexplained** and [README.md](README.md) references them — committing
as-is gives broken images on GitHub. Either `git checkout -- docs/` to restore, or replace them
as part of Track D. **Ask the user which.**

---

## 4. What shipped this session

| Commit | What |
|---|---|
| `f93f68a` | loupe-action pin → `loupe-sdk>=0.3.1,<0.4` (0.3.0 lacked the newline fix) |
| `dd6686e` | CLI rejects invisible chars (U+2028) in LOUPE_HOST/API_KEY; bumped to 0.3.2 |
| `9cede77` | **`GET /v1/suites/{id}/runs`** — run history (SuiteRunSummary omits results/prompt) |
| `3e27508` | **Dashboard `/suites`, `/suites/[id]`, `/suite_runs/[id]`** — unpushed |

Also: **published SDK 0.3.1 to PyPI.** The pre-built `dist/` artifacts were *stale* — labelled
0.3.1 but containing pre-fix code. Rebuilt from clean source and verified the published wheel
byte-for-byte against repo source. **Lesson: always `rm -rf dist/` and verify the artifact,
not the source, before publishing.**

---

## 5. 🔴 The testing sweep — this is the live thread

A full-system test sweep was run. **Everything lives in
[docs/Loupe_Test_Tracker.xlsx](docs/Loupe_Test_Tracker.xlsx)** (4 sheets, 202 cases):

1. **Issues Found** — 10 confirmed bugs (L-001…L-010)
2. **Backend Tests (done)** — 65 tests I ran: **57 PASS / 7 FAIL / 1 INFO**
3. **Your Tests (to do)** — 137 manual/UI/functional/replay tests, **owner: Aditya**
4. **How to run** — env commands, both API keys, seeded traps

### Confirmed issues, worst first

| ID | Sev | Summary |
|----|-----|---------|
| **L-001** | 🔴 Critical | **`@loupe.trace` silently broken for `async` functions.** `core.py:85` only special-cases generators; `async def` hits the sync wrapper → output = coroutine repr, duration 0ms, **spans lost**, and **a raised exception is recorded as `status=success`**. Also hits async generators. **Live in published 0.3.1.** |
| **L-002** | 🟠 High | NUL byte (`\x00`) → 500 (`UntranslatableCharacterError`). Being 5xx, the SDK retries 3× (~3s) then drops. Should be 400 + SDK-side sanitize. |
| **L-003** | 🟠 High | Orphan `parent_span_id` → 500 (FK violation escapes). Should be 400. |
| L-004 | 🟡 Low | No request-size limit (1MB payload stored verbatim). |
| L-005 | 🟡 Low | Negative `duration_ms` / `ended_at` < `started_at` accepted. |
| L-006 | 🟡 Low | `status` is free text — `"banana"` accepted, invisible in every dashboard filter. |
| L-007 | 🟡 Low | **Empty suite runs green** — 0/0 passed, CLI exits 0, GitHub check green having tested nothing. |
| L-008 | 🔵 Info | The "free" `deterministic_check` almost never fires (needs byte-identical output, but replay re-runs the LLM). `shape_guard` *does* fire and works. B8.4's cost model is optimistic. |
| L-009 | 🟡 Low | Dashboard returns 200 for unknown IDs (streaming flushes headers before `notFound()`). Pre-existing, app-wide. |
| L-010 | 🔵 Info | Published 0.3.1 lacks the U+2028 hardening; fold into the L-001 release. |

### What was verified working ✅
Generator traces capture mid-stream spans · nested span trees correct · errors captured with
traceback · all 3 provider integrations map tokens+cost · `provider="groq"` override ·
tool_calls · atexit flush · **project isolation holds under direct attack** · idempotent
re-delivery · 100-level nesting · unicode/emoji/HTML/SQL safe · branch lineage +
`replay_mode` correct · **live Groq judge caught JSON→prose as 2/2 regressed via free
`shape_guard`, and passed an unchanged prompt 2/2** · no secrets in logs.

### Where the user is
Mid-way through **Sheet 3** (their own manual testing). Agreed sequence: `DR-03` fresh-eyes
test first → traces list/detail → branch+diff → replay depth → suites → cross-cutting →
CLI/data → SDK resilience → isolation → CineRater → Prompt CI → **error states last**
(E-01 kills the backend).

**Nothing is fixed yet — by explicit instruction.** They want the final combined list
(my 10 + their findings) before any fixing starts.

---

## 6. Test environment (still running / how to restart)

```bash
docker compose up -d db                                   # Postgres :5433
cd server && DATABASE_URL="postgresql+asyncpg://loupe:loupe@localhost:5433/loupe" \
  SENTRY_DSN="" ENVIRONMENT=development \
  python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
cd dashboard && LOUPE_API_URL="http://127.0.0.1:8010" \
  LOUPE_API_KEY="lp_PxRgfuqfhgzivyZwsHw9YuGQmcLJzVzOR8iWrSUKskY" npm run dev -- --port 3010
```

- **Port 8010, not 8000** — an unrelated "IndiGo Marketing Platform API" occupies :8000 on
  this machine. Using 8000 sends traces to the wrong service.
- Keys: `qa-alpha` = `lp_PxRgfuqfhgzivyZwsHw9YuGQmcLJzVzOR8iWrSUKskY` (owns all seeded data);
  `qa-beta` = `lp_-ZgnzZ4jd4i6oGH94glmStQCph03V4mmZcPOqZNkQY0` (isolation test).
- Seeded traps: `probe_deep` (100 nested spans) · `probe_large` (1MB blob) · a trace with
  `status='banana'` · `probe_empty_suite` (0 traces) · `qa_a5_error` (the only error trace —
  save it for the branch-a-failure demo).

---

## 7. Backlog after the list is finalised

1. **L-001** — add `iscoroutinefunction` + `isasyncgenfunction` branches mirroring
   `gen_wrapper` in `core.py`, with tests for output/duration/span-capture/error on each.
2. **L-002 + L-003** — both are "internal error leaks as 500"; fix together.
3. **L-004…L-007** — validation + empty-suite guard.
4. **Publish 0.3.2** carrying L-001, L-002 and the U+2028 hardening as one release.
   (`rm -rf dist && python3.11 -m build`, verify artifact, then user runs twine — their token.
   Paste-into-prompt corrupts tokens; use the clipboard-sanitising approach.)
5. **Docs refresh** — `claude.md`'s v2.2 checklist still says ⬜ NOT STARTED for everything
   that shipped; add ADR **B12** for the `/runs` endpoint decision (list vs embed).
6. **Track D** — killer-demo recording; the 5 README screenshots (see §3).
7. Older, still open: **B11 PII/secret redaction** (designed, zero code).

---

## 8. Gotchas

- **Bash CWD persists** between tool calls — `cd` to repo root before `git`.
- **Stale uvicorn serves old code** — restart before deep-diving contradictory behaviour.
- `python3.11` for everything; `alembic` isn't on PATH → `python3.11 -m alembic`.
- Fast DB peek: `docker exec loupe-db psql -U loupe -d loupe -c "\dt"`.
- Render free tier sleeps (~15 min) — wake with `curl <url>/health`.
- **Invoke the `claude-api` skill before writing any Claude/Anthropic code** — the API drifted.
- Deployed: dashboard `loupe-kappa.vercel.app`, server `loupe-server.onrender.com`.
  **The suites UI is NOT deployed** (commit `3e27508` unpushed).

---

## 9. First message for the new chat

> "Read HANDOFF_NEXT.md and continue. We ran a full test sweep — everything is in
> docs/Loupe_Test_Tracker.xlsx. I'm still working through Sheet 3 (my manual/UI tests).
> Don't fix anything yet — I'll give you my findings, we'll merge them with your L-001→L-010
> into one final list, then we fix in order starting with L-001 (async trace bug).
> Teach as you build, one sub-step at a time, test rigorously, Hinglish, keep it zero-cost."
>
> *(If they'd rather start fixing immediately: begin with **L-001**, it's critical and live
> on PyPI.)*

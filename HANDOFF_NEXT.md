# Loupe — Session Handoff

> Written **2026-08-17**. Supersedes the 2026-08-07 handoff entirely.
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

## 2. 🔴 READ THIS FIRST — how the user needs you to work

**This changed materially this session. It is now the most important section here.**

Aditya said, in his own words, that **things are going over his head and the fun has
gone out of the project.** That is the single most important fact in this handoff. A
working feature he cannot explain is worth nothing — this is a portfolio project, and
the deliverable is *his ability to defend it in an interview*, not the code.

Two things now enforce this, both created 2026-08-17:

- **[claude.md](claude.md) → "How we work together"** — always on, read every session.
- **`/checkpoint` skill** ([.claude/skills/checkpoint/SKILL.md](.claude/skills/checkpoint/SKILL.md))
  — he invokes it to force a pause, an explanation, or a quiz.

The rules, short version:

- **Before every sub-step**, pitch it in ≤5 sentences (what / why / how / cost /
  the alternative not taken), then **ask "do you agree with this approach?"** and wait.
- **After every sub-step**, quiz him — 3–5 multiple-choice questions via
  `AskUserQuestion`, mixing recall, "why this choice", a judgment call, and one trap.
  Say why each answer was right or wrong. The explanation is the point, not the score.
- **Analogy first, then the technical name.** One new concept at a time. Name the
  jargon out loud. Always use this project's own examples, never `foo`/`bar`.
- **Each checkpoint, include exactly one of**: "here's the cool part" / "here's what
  this gets you in an interview" / "here's what nearly went wrong".
- He can say **"I don't get it"** any number of times at no cost. Tell him so.
- **If he says stop, stop.** Do the work; note that the explanation is owed.

Unchanged standing preferences: **Hinglish** (simple English, short sentences). One
sub-step at a time, **tested with the code**. Be direct about limitations — the best
features here came from that. Architecture decisions: *tension → options → tradeoffs →
recommendation → "decision needed"* → get the pick → record in ARCHITECTURE_DECISIONS.md
→ build. Commit straight to `main`; **push only when asked**. **Zero-cost by default.**

---

## 3. State of the repo

- Branch `main`, **4 commits ahead of origin — nothing pushed yet** (`1d4db2e`, `30ef5fd`,
  `c755fc1`, plus this one) and the **`v0.3.2` tag is local too**. Push when asked:
  `git push origin main --follow-tags`.
- SDK: **0.3.2 published to PyPI 2026-08-20** and verified by installing from PyPI into a
  clean venv. Repo and PyPI now agree.
- Tests green: **server 127** (106 + 21 redaction), **SDK 56**, ruff clean,
  dashboard lint + build clean.

### Uncommitted working tree

```
?? Screenshot …png x2     ← stray, in repo root, not gitignored
```

claude.md and `.claude/` were committed in `3f9227a`. The two screenshots are junk —
delete or gitignore them.

---

## 4. What shipped this session (2026-08-17)

| Commit | What |
|---|---|
| `3e27508`+`6fcf84c` | **Dashboard `/suites` pages pushed and deployed** — closed the last v2.2 gap |
| `0407166` | **CI: pinned ruff to 0.15.16.** It was unpinned; ruff 0.16.2 flagged 48 pre-existing findings and turned `main` red with no code change. CI had been failing since `9cede77`. |
| `89f12c1` | **Redaction primitives** — `server/app/services/redact.py`, 13 credential patterns, 21 tests, mutation-checked |
| `1182047` | **Redaction wired into `POST /v1/traces`** — scrubs input/output/error/metadata on trace *and* spans |

Also, not in git: **production database backfilled** — 13 rows (4 traces + 9 spans)
scrubbed in place.

---

## 5. 🔴 L-013 — the secret leak (found and closed this session)

**What happened.** A trailing newline in CineRater's `GROQ_API_KEY` made `httpx` raise
`LocalProtocolError` carrying the entire `Authorization` header. `@loupe.trace` captured
that exception into `trace.error`, the SDK shipped it to the server, and the public
Vercel dashboard rendered **a live Groq API key** — from June until 2026-08-17. Found by
accident, reading error traces while looking for DR-04 demo material.

**Closed:**

1. Key **revoked** (Groq now returns 403). Both `.env` files updated.
2. Scanned for anything else: **86 public trace pages + the whole local DB**, against 14
   generic credential patterns and 12 real values pulled from the user's `.env` files.
   **Only that one key ever leaked.** Git history of both repos was always clean.
3. **Ingest-time redaction shipped** (see §4).
4. **Production backfilled** — 13 rows scrubbed, verified 0 secrets in the DB and 0
   across all 86 public pages. Traces survived intact; only the key was replaced.

**Design decisions, for the interview answer:**

- **Fail open.** Redact and store, never reject. Rejecting drops the trace — and drops
  it precisely on the unattended production runs nobody is watching, breaking the one
  promise an observability tool makes.
- **Server-side first**, SDK-side later. The server boundary protects *every* SDK
  version, including the 0.3.1 already installed in the wild, which we cannot upgrade.
- **Walk the structure, not `json.dumps()` output.** Preserves shape, leaves dict keys
  alone, avoids escape-sequence corruption.
- **Best effort, not a guarantee.** A house-format token (`tok_x9f…`) still sails
  through. The README needs to say so — it does not yet.

**Still open from L-013:** dashboard badge for `_loupe_redacted`; SDK-side redaction
(ship with L-001 in 0.3.2); the README caveat.

**Cleanup owed:** `~/.loupe_prod_backup_l013.json` (mode 600) holds the pre-scrub rows,
i.e. the dead key. Delete once satisfied. `~/.loupe_prod_db` holds the Neon DSN.

---

## 6. The combined findings list — this is the live thread

From the test sweep ([docs/Loupe_Test_Tracker.xlsx](docs/Loupe_Test_Tracker.xlsx), 4
sheets, 202 cases). `L-*` = found by Claude, `U-*` = found by Aditya.

### Closed

| ID | What | How |
|----|------|-----|
| **L-001** | 🔴 `@loupe.trace` (and `@loupe.span`) silently broken for `async` | `1d4db2e`, shipped in 0.3.2 |
| L-010 | 0.3.1 lacked the U+2028 CLI hardening | shipped in 0.3.2 |
| L-011 | CI lint tool unpinned | `0407166` |
| L-013 | 🔴 Live API key leaked on the public dashboard | revoked + code + prod backfill |
| U-003 | `/suites` 404 in production | pushed `3e27508` |

### Open, worst first

| ID | Sev | Summary |
|----|-----|---------|
| **U-001** | 🟠 High | **No home/landing page** — the app opens straight onto the traces dashboard. Also the #1 perf fix: Render's free tier sleeps ~15 min, so a backend-free static landing page makes first paint instant at ₹0 instead of paying for a non-sleeping tier. Measured: backend warm 0.4–1.1s, Vercel `/` warm 1.25–1.55s. |
| **U-005** | 🟠 High | Deployed traces list page 1 is a wall of near-identical `genre_extract (suite replay)` rows. The interesting traces are buried on later pages. |
| L-002 | 🟠 High | NUL byte (`\x00`) → 500. Being 5xx, the SDK retries 3× (~3s) then drops. Should be 400 + SDK-side sanitize. |
| L-003 | 🟠 High | Orphan `parent_span_id` → 500 (FK violation escapes). Should be 400. |
| U-002 | 🟡 Med | UI is plain — he wants motion / imagery / 3D. **Recommended instead:** proper landing page + an auto-playing demo GIF of the killer flow + light polish. Showing the product beats decoration. His call. |
| L-004 | 🟡 Low | No request-size limit (1MB payload stored verbatim). |
| L-005 | 🟡 Low | Negative `duration_ms` / `ended_at` < `started_at` accepted. |
| L-006 | 🟡 Low | `status` is free text — `"banana"` accepted, invisible in every dashboard filter. |
| L-007 | 🟡 Low | **Empty suite runs green** — 0/0 passed, CLI exits 0, GitHub check green having tested nothing. |
| L-009 | 🟡 Low | Dashboard returns 200 for unknown IDs (streaming flushes headers before `notFound()`). Pre-existing, app-wide. |
| L-012 | 🟡 Low | ruff 0.16.x upgrade + clear the 48 findings (25 are B008 on FastAPI's `Depends()` idiom — needs a per-file ignore). Deliberately deferred. |
| U-004 | 🟡 Low | `/suites` leads with "✗ 0/15 passed", which reads as *broken tool* rather than *caught 15 regressions*. The `/suite_runs/[id]` page already has the right framing — "this run would block the PR" — lift it up to the list. |
| L-008 | 🔵 Info | The "free" `deterministic_check` almost never fires. `shape_guard` *does* fire and works. |
| L-014 | 🔵 Info | `@loupe.span` **decorator** does not support async *generator* tools — the replay freeze/edit path has no sensible meaning for a stream. Documented in the docstring; the context manager works. Deliberate, not a defect. |

### Verified working ✅
Generator traces capture mid-stream spans · nested span trees · errors with traceback ·
all 3 provider integrations map tokens+cost · `provider="groq"` override · tool_calls ·
atexit flush · **project isolation holds** (confirmed again: two same-named
`genre-golden` suites in prod belong to different projects and the dashboard correctly
shows only one) · idempotent re-delivery · 100-level nesting · unicode/emoji/HTML/SQL
safe · branch lineage + `replay_mode` · live Groq judge caught JSON→prose 2/2 via free
`shape_guard` · no secrets in logs.

---

## 7. Where the manual testing stands

**Sheet 3 (137 manual/UI tests) — the file is still blank.** Findings come **verbally**;
record them into the sheet as they arrive.

- **Done: DR-03** (fresh-eyes recruiter test) → produced U-001, U-002, U-004, U-005.
- **Next: DR-01** (DevTools console errors on every page), then DR-04 (killer flow),
  DR-02 (polling), DR-05 (screenshots).
- **Decision made: test on the deployed instance only** —
  [loupe-kappa.vercel.app](https://loupe-kappa.vercel.app).

**⚠️ Deployed-only has a real gap.** None of the five seeded traps exist in production:

| Trap | Local | Prod |
|---|---|---|
| `probe_deep` (100 nested spans) | ✅ | max **13** |
| `probe_large` (1MB payload) | ✅ | max **882 bytes** |
| `status='banana'` | ✅ | only success/error |
| `probe_empty_suite` (0 traces) | ✅ | ❌ |
| `qa_a5_error` (agent-reasoning failure) | ✅ | 5 errors, all **auth** failures |

So ~37 of the 137 tests (CLI, data-correctness edges, ISO, error states, self-host)
cannot run on deployed. **Do not seed the traps into production** — `probe_large` and
`probe_deep` would pollute the public demo, which already suffers from U-005. Agreed
plan: do the ~100 UI/demo/flow tests on deployed, batch the ~37 into one local session.

---

## 8. Environments

**Deployed:** dashboard [loupe-kappa.vercel.app](https://loupe-kappa.vercel.app),
server `loupe-server.onrender.com`. Render free tier sleeps ~15 min — wake with
`curl <url>/health`.

**Local:**

```bash
docker compose up -d db                                   # Postgres :5433
cd server && DATABASE_URL="postgresql+asyncpg://loupe:loupe@localhost:5433/loupe" \
  SENTRY_DSN="" ENVIRONMENT=development \
  python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
cd dashboard && LOUPE_API_URL="http://127.0.0.1:8010" \
  LOUPE_API_KEY="lp_PxRgfuqfhgzivyZwsHw9YuGQmcLJzVzOR8iWrSUKskY" npm run dev -- --port 3010
```

Server tests: `DATABASE_URL=…/loupe_test SECRET_KEY=x ENVIRONMENT=test SENTRY_DSN="" python3.11 -m pytest tests/ -q`

- **Port 8010, not 8000** — an unrelated service occupies :8000 on this machine.
- Keys: `qa-alpha` = `lp_PxRgfuqfhgzivyZwsHw9YuGQmcLJzVzOR8iWrSUKskY` (owns all seeded
  data); `qa-beta` = `lp_-ZgnzZ4jd4i6oGH94glmStQCph03V4mmZcPOqZNkQY0` (isolation test).
- CineRater's `LOUPE_API_KEY` returns **401 against the deployed server** — there is
  currently no known-valid production Loupe API key on this machine.

---

## 9. Backlog, in order

1. ~~**L-001**~~ + ~~**publish 0.3.2**~~ — **DONE 2026-08-20.** All four function kinds
   branch at decoration time; `@span` fixed too. 11 tests, 5/5 mutations caught,
   `sdk/CHANGELOG.md` added, `v0.3.2` tagged. Verified by installing **from PyPI** into a
   clean venv, not just from the local wheel.
2. **SDK-side redaction** — same patterns, applied before the payload leaves the user's
   machine. Deliberately **not** bundled into 0.3.2: the server already scrubs every
   trace regardless of SDK version, so this is defense-in-depth, not urgent. Ship as
   0.3.3.
3. **U-001 landing page** — biggest demo win, and it fixes the cold-start first paint
   for ₹0.
4. **L-002 + L-003** — both are "internal error leaks as 500"; fix together.
5. **L-004…L-007** — validation + empty-suite guard.
6. **Dashboard badge** for `_loupe_redacted`; **README** best-effort redaction caveat.
7. **Docs** — `claude.md`'s v2.2 checklist still says ⬜ NOT STARTED for shipped work;
   add ADR **B12** (the `/runs` endpoint) and **B11** (redaction, now built).
8. **Track D** — killer-demo recording; real README screenshots.

---

## 10. Gotchas

- **Bash CWD persists** between tool calls — `cd` to repo root before `git`.
- **Stale uvicorn serves old code** — restart before deep-diving contradictory behaviour.
- `python3.11` for everything; `alembic` isn't on PATH → `python3.11 -m alembic`.
- Fast local DB peek: `docker exec loupe-db psql -U loupe -d loupe -c "\dt"`.
  Note the ORM's `extra_metadata` is the column **`metadata`** in SQL.
- **The traces list API returns `{"items": […]}`,** not `{"traces": […]}`.
- **Reaching the production DB:** this machine's network blocks outbound **5432**, so
  asyncpg to Neon times out. Use Neon's **SQL-over-HTTPS**: POST `https://<host>/sql`
  with header `Neon-Connection-String`. The stored DSN uses `postgresql+asyncpg://`,
  which that endpoint rejects with "incorrect scheme" — rewrite to `postgresql://` and
  append `sslmode=require`. Working script: scratchpad `purge_prod.py`.
- **Invoke the `claude-api` skill before writing any Claude/Anthropic code.**
- A test suite that passes on the first try deserves a **mutation check** — break the
  code deliberately and confirm the tests scream. Both redaction mutations were caught.

---

## 11. First message for the new chat

> "Read HANDOFF_NEXT.md and continue. Start with §2 — I told Claude last session that
> this project is going over my head and stopped being fun, so we built a working
> agreement and a /checkpoint skill. Follow it: pitch each sub-step and ask if I agree
> before building, and quiz me after. Next up is L-001, the async trace bug. Teach as
> you build, Hinglish, keep it zero-cost."

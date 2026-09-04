# Loupe — Session Handoff

> Written **2026-09-01**. Supersedes the 2026-08-17 handoff entirely.
> Paste this file's path into the new chat and say the message in §10.

---

## 1. What Loupe is (30 seconds)

Observability + **replay/branch debugger + prompt regression testing** for LLM agents.
Three layers, all shipped:

- **Observe** (MVP) — instrument an agent, see every trace/span.
- **Replay/branch** (v2.1) — open a failed trace → edit a span → re-run from there → diff.
- **Prompt CI/CD** (v2.2) — golden suites → replay against a new prompt → LLM judge → a
  GitHub Action that blocks PRs on regressions.

Spec: [claude.md](claude.md). Decisions: [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
Plain-language explainer: [docs/concepts-explained.md](docs/concepts-explained.md).

---

## 2. 🔴 READ THIS FIRST — how the user needs you to work

**This is the most important section here. It is not optional.**

Aditya said, in his own words, that **things were going over his head and the fun had
gone out of the project.** A working feature he cannot explain is worth nothing — this
is a portfolio project, and the deliverable is *his ability to defend it in an
interview*, not the code.

Enforced by [claude.md](claude.md) → "How we work together" (always on) and the
**`/checkpoint` skill** ([.claude/skills/checkpoint/SKILL.md](.claude/skills/checkpoint/SKILL.md)).

The rules:

- **Before every sub-step**, pitch it in ≤5 sentences (what / why / how / cost / the
  alternative not taken), then **ask "do you agree with this approach?"** and wait.
- **After every sub-step**, quiz him — 3–4 multiple-choice questions via
  `AskUserQuestion` (the tool caps at 4), mixing recall, "why this choice", a judgment
  call, and one trap. Say why each answer was right or wrong. The explanation is the
  point, not the score.
- **Each checkpoint, include exactly one of**: "here's the cool part" / "here's what
  this gets you in an interview" / "here's what nearly went wrong".
- He can say **"I don't get it"** any number of times at no cost. Tell him so.
- **If he says stop, stop.** Do the work; note that the explanation is owed.

### ⚠️ Hinglish — corrected this session, get this right

He pushed back with **"bhai itni hindi bhi nahi"**. Hinglish here means **simple English
sentences with Hindi connective tissue** — `to`, `matlab`, `abhi`, `wahi`, `chalo`,
`theek hai`. It does **NOT** mean translating technical terms into Hindi. Inventing Hindi
words for technical concepts (*mohar* for a code flag, *parchi* for a coroutine, *jhanda*
for a ContextVar) makes it **harder**, because he has to translate twice. Keep
`coroutine`, `flag`, `ContextVar`, `prefetch` in English. **Also keep replies shorter** —
long walls of text are part of the same complaint.

Analogies are still good — just keep them in plain English ("it's an order slip, not the
food"). One new concept at a time. Use this project's own examples, never `foo`/`bar`.

Other standing preferences: one sub-step at a time, **tested with the code**. Be direct
about limitations. Architecture decisions: *tension → options → tradeoffs →
recommendation → "decision needed"* → get the pick → record in ARCHITECTURE_DECISIONS.md
→ build. Commit straight to `main`; **push only when asked**. **Zero-cost by default.**

---

## 3. State of the repo

- Branch `main`, **in sync with origin**, pushed 2026-09-01. Tag `v0.3.2` pushed.
- SDK: **0.3.2 live on PyPI**, verified by installing from PyPI into a clean venv.
- Tests green: **server 132**, **SDK 56**, ruff clean, dashboard lint + build clean.
- Deployed and verified: Vercel dashboard + Render server both carry this session's work.

### Uncommitted working tree

Two stray `Screenshot ….png` files in the repo root — junk, delete or gitignore.

---

## 4. What shipped this session (2026-08-19 → 09-01)

| Commit | What |
|---|---|
| `1d4db2e` | **L-001 — `@loupe.trace` / `@loupe.span` fixed for async.** Decoration-time branch on all four function kinds. 11 tests, 5/5 mutations caught. |
| `c755fc1` | `sdk/CHANGELOG.md` added, 0.1.0 → 0.3.2 |
| `5918e34` | **U-001 — static landing page at `/`**, traces list moved to `/traces` |
| `645df42` | **U-005 — `is_replay` filter**, list hides suite replays by default |
| — | **loupe-sdk 0.3.2 published to PyPI** (2026-08-20) |
| — | **`docs/Loupe_Test_Tracker.xlsx` updated** — Sheet 1 now has 16 issues incl. U-*, Sheet 3 has DR-01 + DR-03 |

### The measured wins

- **Landing page:** production `/` was **47.2s** on a cold Render backend. Now **0.22s**,
  served from Vercel's CDN (`x-vercel-cache: HIT`). The page makes **zero API calls** by
  design — a comment in `dashboard/app/page.tsx` says not to add a live stat, because one
  fetch turns `/` dynamic again and gives the cold start back.
- **Replay filter:** production `/traces` went from **80 "(suite replay)" rows to 0**.

---

## 5. Findings — the Excel is now the source of truth

**[docs/Loupe_Test_Tracker.xlsx](docs/Loupe_Test_Tracker.xlsx)** — Sheet 1 "Issues Found"
has all 16 with full fix notes. Sheet 3 has 137 manual tests, 2 filled. Keep recording
there, not only in chat. Summary:

**Closed:** L-001 (async, shipped 0.3.2) · L-010 (U+2028, shipped 0.3.2) · L-011 (ruff
pin) · L-013 (🔴 the leaked Groq key — revoked, redaction shipped, prod backfilled) ·
U-001 (landing page) · U-003 (`/suites` 404). **L-014** = documented by-design limit
(`@loupe.span` decorator does not support async *generator* tools).

**Open, worst first:**

| ID | Sev | Summary |
|----|-----|---------|
| **U-005** | 🟠 | **Partially fixed.** Replay noise gone, but page 1 is still 15× `genre_extract` + 5× `triage_repo` **originals** — and all 9 `cinerater` traces (the actual demo agent) sit on **page 2**. Needs a name filter, or reseed so the good traces are newest. **This is the next real demo blocker.** |
| L-002 | 🟠 | NUL byte (`\x00`) → 500. SDK retries 3× then drops. Should be 400 + SDK sanitize. |
| L-003 | 🟠 | Orphan `parent_span_id` → 500 (FK violation escapes). Should be 400. |
| U-002 | 🟡 | UI plain. Landing page helped; a demo GIF is the remaining piece (Track D). |
| U-004 | 🟡 | `/suites` leads with "✗ 0/15 passed", reads as *broken tool* not *caught 15 regressions*. `/suite_runs/[id]` already frames it right — lift that up. |
| L-004…L-007 | 🟡 | request-size limit · negative duration · `status` free text · empty suite runs green |
| L-008 | 🔵 | `deterministic_check` rarely fires; `shape_guard` does and works. |
| L-009 | 🔵 | Unknown IDs return 200 not 404. **Re-confirmed on production 2026-09-01.** |
| L-012 | 🟡 | ruff 0.16.x upgrade + clear 48 findings (25 are B008 on `Depends()` — needs per-file ignore). |

---

## 6. Testing status

- **DR-03** (recruiter fresh-eyes) — DONE, produced U-001/002/004/005.
- **DR-01** (console errors) — **DONE 2026-09-01, PASS.** Automated with headless Chrome.
  10 pages + a 6-step client-side journey (load `/` → click to `/traces` → toggle replays
  → open a trace → Back → reload). **0 console errors, 0 uncaught exceptions, 0 4xx/5xx,
  0 broken assets.** The only network events were 81 `net::ERR_ABORTED` on Next.js
  `?_rsc=` prefetches, all to our own host — these also fire while the page merely idles,
  so they are normal App Router behaviour, not a defect.
- **Next: DR-04** (killer flow: failed trace → branch → diff), then DR-02 (polling),
  DR-05 (screenshots).

**The headless-browser harness is reusable** — see §9.

**⚠️ ~37 of the 137 tests cannot run on deployed** (CLI, data-correctness edges, error
states, self-host): production lacks the five seeded traps (`probe_deep`, `probe_large`,
`status='banana'`, `probe_empty_suite`, `qa_a5_error`). **Do not seed them into
production** — they would pollute the public demo. Batch those into one local session.

---

## 7. Environments — verified working 2026-09-01

**Deployed:** [loupe-kappa.vercel.app](https://loupe-kappa.vercel.app) ·
`loupe-server.onrender.com`. Render sleeps ~15 min; wake with `curl <url>/health`.
The landing page at `/` does **not** need the backend.

**Local — three terminals:**

```bash
open -a Docker                                   # daemon is usually NOT running
cd ~/Desktop/Loupe_Project && docker compose up -d db     # Postgres on :5433

cd ~/Desktop/Loupe_Project/server                # server/.env auto-loads, no inline vars
python3.11 -m uvicorn app.main:app --reload --port 8000

cd ~/Desktop/Loupe_Project/dashboard             # .env.local points at :8000
npm run dev                                      # http://localhost:3000
```

Server tests:
```bash
cd server && DATABASE_URL="postgresql+asyncpg://loupe:loupe@localhost:5433/loupe_test" \
  SECRET_KEY=x ENVIRONMENT=test SENTRY_DSN="" python3.11 -m pytest tests/ -q
```

- **Port 8000, not 8010.** The old handoff said 8010 because something occupied 8000 then;
  it is free now, and `dashboard/.env.local` expects 8000.
- **`server/.env` already holds everything** (DATABASE_URL, Groq key). Don't pass inline
  env vars. Pydantic reads `.env` relative to CWD, so run from `server/`.
- Keys: `qa-alpha` = `lp_PxRgfuqfhgzivyZwsHw9YuGQmcLJzVzOR8iWrSUKskY`;
  `qa-beta` = `lp_-ZgnzZ4jd4i6oGH94glmStQCph03V4mmZcPOqZNkQY0` (isolation test).

---

## 8. Backlog, in order

1. **U-005 part two** — get `cinerater` traces onto page 1. Options: a name/search filter,
   or reseed so the interesting traces are newest. **Decide with him first.**
2. **DR-04** — walk the killer flow on deployed (failed trace → branch → diff).
3. **L-002 + L-003** — both "internal error leaks as 500"; fix together.
4. **SDK-side redaction → 0.3.3.** Deliberately not in 0.3.2: the server already scrubs
   every trace regardless of SDK version, so this is defense-in-depth, not urgent.
5. **U-004** — lift the `/suite_runs` framing up to the `/suites` list.
6. **L-004…L-007** — validation + empty-suite guard.
7. **Dashboard badge** for `_loupe_redacted`; **README** best-effort redaction caveat.
8. **Docs** — claude.md's v2.2 checklist still says ⬜ NOT STARTED for shipped work; add
   ADR **B11** (redaction) and **B12** (the `/runs` endpoint).
9. **Track D** — killer-demo recording (the landing page has a slot waiting for it, at
   `DemoFrame` in `dashboard/app/page.tsx`); real README screenshots.

---

## 9. Gotchas

- **`gh` CLI is NOT installed.** Check CI at github.com/Adityachauhan12/Loupe/actions.
- **Docker daemon is usually down** — `open -a Docker` and wait before `docker compose`.
- **The dashboard's `.env.local` key is NOT qa-alpha.** Different project, different data
  (22 originals vs 32). This caused a false "pagination is broken" alarm this session.
  When two numbers disagree, first ask *"did both sides ask the same question?"*
- **Headless browser testing works** and is set up in the scratchpad:
  `dr01/dr01b.mjs` uses `puppeteer-core` (no browser download) against the installed
  Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`. Reuse it for
  DR-02/DR-04. Note: the **Claude Chrome extension does not give this session a browser
  tool** — they are separate; drive Chrome yourself.
- **`lucide-react` has no brand icons** (`Github` does not exist). Inline the SVG.
- **PyPI's JSON API is CDN-cached** and lags after an upload; `/simple/<pkg>/` is
  authoritative for what `pip` will see.
- **Bash CWD resets between tool calls** — use absolute paths.
- `python3.11` for everything; `alembic` isn't on PATH → `python3.11 -m alembic`.
- Fast DB peek: `docker exec loupe-db psql -U loupe -d loupe -c "\dt"`. The ORM's
  `extra_metadata` is the SQL column **`metadata`**.
- **The traces list API returns `{"items": […]}`,** not `{"traces": […]}`.
- **Production DB access:** this machine blocks outbound 5432, so asyncpg to Neon times
  out. Use Neon's SQL-over-HTTPS: POST `https://<host>/sql` with a `Neon-Connection-String`
  header, rewriting the DSN to `postgresql://…?sslmode=require`.
- **Invoke the `claude-api` skill before writing any Claude/Anthropic code.**
- **A suite that passes first try deserves a mutation check** — break the code
  deliberately and confirm the tests scream. Every mutation this session was caught.
- **"Build passed" ≠ "it works."** The build compiles types and imports; it does not
  check that an `href` string points at a real route. Curl the routes.

---

## 10. First message for the new chat

> "Read HANDOFF_NEXT.md and continue. Start with §2 — especially the Hinglish note: plain
> English sentences with Hindi connectors, technical terms stay in English, and keep
> replies short. Follow the working agreement: pitch each sub-step and ask if I agree
> before building, then quiz me after. Next up is U-005 part two — the traces list still
> buries the cinerater traces on page 2. Zero-cost."

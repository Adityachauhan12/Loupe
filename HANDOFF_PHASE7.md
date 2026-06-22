# Loupe v2 — Session Handoff for Phase 7 (Branched-vs-Original Diff View)

> Paste this file's path into the new chat and say:
> "Read HANDOFF_PHASE7.md and continue. Start Phase 7 — the branched-vs-original
> diff view. Teach as you build, one sub-step at a time, test rigorously."
> Written 2026-06-16.

---

## 1. What Loupe is (30-second version)

Loupe = observability + **replay/branch debugger** for LLM agents. MVP is live
(SDK on PyPI, dashboard on Vercel, server on Render, Postgres on Neon).

**v2 framing:** a *debugger for non-deterministic agents* (like `rr`/time-travel
debugging, but for LLM agents). Killer flow: open a failed trace → click the span
that went wrong → edit it → branch → re-run from there → **side-by-side diff** of
original vs counterfactual. Full project spec: [CLAUDE.md](CLAUDE.md). v2 plan:
[V2_CHECKLIST.md](V2_CHECKLIST.md). The original v2 handoff (Phases 0–3) is
[HANDOFF.md](HANDOFF.md) — still useful for backstory.

---

## 2. How the user likes to work (IMPORTANT — match this)

- **Teach as you build:** narrate steps in plain language, drop learnings,
  surface interview Q&A. The user is doing this as a **portfolio/learning** sprint.
- The user often writes in **Hinglish** ("samjhaao", "simple words mein"). Answer
  in the same simple style. Explain concepts with small analogies.
- **One sub-step at a time. Test rigorously as you go** (write tests with the
  code, not after). Confirm before moving on.
- Be **direct and honest** — if something is wrong or limited, say so plainly.
  The user explicitly values this. (We hit a real limitation mid-build and saying
  so led to the best feature — see §5.)
- After meaningful work: write a **`notes/NN-*.md`** file (plain language +
  interview Q&A), update `notes/README.md` index, then **commit + push**.
- Commit message footer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  (match the model actually in use).
- Use a **TodoWrite** list to track sub-steps.

---

## 3. Where we are — v2 progress

| Piece | Status | Commit |
|-------|--------|--------|
| Phase 4 — server branch replay engine (`_run_branch`) | ✅ | f54ee6f |
| Phase 5 — `POST /v1/traces/{id}/branch` endpoint | ✅ | 4600c35 |
| Phase 6 — dashboard "⑂ Branch from here" UI | ✅ | 9ebf372 |
| Dashboard span-tree markers fix (branch_point/ghost) | ✅ | 7e2f6d4 |
| Provider-call hardening (key newline + empty anthropic msgs) | ✅ | 1a9a07b |
| **SDK-side replay** (`loupe.replay`) — edit propagates | ✅ | 69faf0e |
| **`loupe replay` CLI** | ✅ | 15031bc |
| **Phase 7 — branched-vs-original diff view** | ⬅️ **NEXT** | — |
| Track D — killer demo recording + README | ⬜ | — |

All tests green: **server 61**, **SDK 30**. Branch is on `main`; we commit
straight to `main` (that's the user's established pattern — every recent commit is
on main).

---

## 4. The two kinds of replay (know the difference — it shapes Phase 7)

There are **two** replay paths, and the diff view should ideally handle both:

1. **Server-side branch** (Phase 4/5/6). Triggered from the dashboard button.
   Runs on the server via BackgroundTask. It can re-run LLM calls but **cannot run
   the user's tool functions** (they live in the user's process). So downstream
   tools become **dry-run ghost spans** and the edit does **not** propagate. Good
   for a safe "preview + skip writes".

2. **SDK-side replay** (`loupe.replay` / `loupe replay` CLI). Runs **in the user's
   process**, so real tools re-execute and the **edit propagates** all the way to
   the final answer. This is the "true counterfactual".

**Both produce a normal trace** with `branched_from_trace_id` +
`branched_from_span_id` set, plus a `replays` row (server-side path only) for diff
metadata. Span `metadata` carries markers: `{"branch_point": true}`,
`{"dry_run": true}` (server ghost), `{"replay": "frozen"}` (SDK frozen),
`{"replay": "stored_passthrough"}` (server live-tool passthrough).

> Phase 7 reads `traces.branched_from_*` (already exposed on `TraceDetail`), so it
> works for **both** paths. The server-side `replays` row diff_summary is a bonus.

---

## 5. Phase 7 — what to build (the spec)

From [V2_CHECKLIST.md](V2_CHECKLIST.md), Phase 7:

- **7.1** Side-by-side diff comparing branched vs original **from the branch point
  onward** (not the whole trace — the spans before the branch are identical/frozen).
- **7.2** Surface deltas: output difference, token Δ, latency Δ, **status change**.
- **7.3** Make it one coherent flow: trace detail → branch → diff.

### What already exists to reuse (don't rebuild)

- **`dashboard/components/ReplayDiff.tsx`** — a working side-by-side diff for the
  **v1 whole-trace replay**. It renders two `TraceCard`s, a `DeltaRow`
  (token/cost/latency deltas with %), and pairs up **LLM** spans for output
  comparison. **Phase 7 should adapt/generalize this** for branches:
  - It currently only pairs `llm` spans. For a branch you likely want to compare
    **all spans from the branch point onward**, and visually flag ghosts /
    branch-point / status change.
  - The current `modifications` banner assumes `{prompt_override, model_override}`
    (v1 shape). A **branch's** `replays.modifications` is
    `{branch_span_id, new_output}` — handle that shape (or read lineage from the
    trace instead).
- **`dashboard/app/replays/[id]/page.tsx`** — the v1 diff page: fetches the
  `replay` row + both traces, shows a `WaitingPage` (with `AutoRefresh`) while the
  new trace is `running`, else renders `<ReplayDiff>`. **A branch diff page can
  follow this exact pattern.**
- **`dashboard/components/AutoRefresh.tsx`** — poll-by-refresh while running.
- **`dashboard/components/SpanTree.tsx`** — already renders marker badges
  (branch point / dry-run / passthrough) and dims ghost rows. The trace-detail
  page already shows a "⑂ Branched run · View original trace →" lineage banner.

### Suggested approach (discuss with user first — they like designing the sub-step)

A branch is identified by `trace.branched_from_trace_id` + `branched_from_span_id`.
Two routes are possible — **let the user pick**:

- **Option A — diff via the existing `replays` row** (server-side branches):
  reuse `/replays/[id]` flow; the `replays.new_trace_id` is the branch. Pro: zero
  new routing. Con: SDK-side replays **don't create a `replays` row**, so this
  misses them.
- **Option B — a branch diff keyed by trace id** (recommended, covers both paths):
  new route e.g. `dashboard/app/traces/[id]/diff/page.tsx` (or `/branches/[id]`)
  that, given the **branched trace id**, reads `branched_from_trace_id`, fetches
  both traces, finds the branch point (`branched_from_span_id`), and diffs from
  there. Add a "View diff" link in the lineage banner on the branched trace's
  detail page ([dashboard/app/traces/[id]/page.tsx](dashboard/app/traces/[id]/page.tsx)).

Either way: align spans by **execution order from the branch point onward**, show
per-span original-vs-new output, mark the branch point, ghosts, and status change,
and reuse `DeltaRow` for the trace-level deltas.

### Server support you may (or may not) need

- `TraceDetail` already includes `branched_from_trace_id` / `branched_from_span_id`
  (server `schemas.py`, dashboard `lib/api.ts`). Lineage diffing needs **no new
  server endpoint** — you can fetch both traces with the existing
  `GET /v1/traces/{id}`.
- If you want "list branches of a trace" (nice for trace detail), that'd be a new
  `GET` (the `idx_traces_branched_from` index already exists for it) — **optional**,
  only if the user wants it.

---

## 6. Environment & gotchas (saves the new chat a lot of time)

- **Python: use `python3.11`** for everything (pip, pytest, alembic, uvicorn). The
  bare `python3` is 3.13 and lacks deps. `alembic` isn't on PATH → `python3.11 -m alembic`.
- **Local Postgres:** `docker compose up -d db` (service `db`, container `loupe-db`,
  port **5433**). It's usually already running. Test DB `loupe_test` exists.
- **Run server:** from `server/`,
  `SENTRY_DSN="" ENVIRONMENT=development python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **Run server tests:** from `server/`,
  `SENTRY_DSN="" python3.11 -m pytest tests/ --timeout=30 -q` (the `SENTRY_DSN=""`
  avoids a ~2s exit hang). Currently **61 passing**.
- **Run SDK tests:** from `sdk/`, `python3.11 -m pytest tests/ -q`. **30 passing.**
- **Dashboard:** from `dashboard/`, `npm run dev` (port **3000**). Verify with
  `npx --no-install tsc --noEmit` and `npm run build` (Next 16 + Turbopack, React 19,
  App Router, server components + server actions; **no shadcn** — plain Tailwind,
  dark theme, gray-800 borders, mono fonts).
- **Dashboard env:** `dashboard/.env.local` has `LOUPE_API_URL=http://localhost:8000`
  and a `LOUPE_API_KEY` (this key's project is the one with branchable test data).
- **Two projects in the local DB** — the dashboard key's project is the one to use.
  The `cinerater` *trace* in the DB belongs to a *different* project; the
  `examples/cinerater` agent is a self-contained toy (25 hardcoded movies in
  `data.py`). To create branchable cinerater traces in the right project, run the
  agent with the dashboard's key + local host (see §7).
- **Timestamps** in the dashboard are forced to IST (`Asia/Kolkata`).
- **Render free tier sleeps** (~15 min) — wake with `curl <render-url>/health`.
- **Deployed env fix already applied by the user:** the prod `GROQ_API_KEY` had a
  trailing newline (caused "Illegal header value"); code now `.strip()`s keys too.

---

## 7. Live test data + how to make more (for verifying the diff)

In the dashboard key's project (local DB), these branched traces already exist
from this session (server up at :8000, dashboard at :3000 during the session —
they may be stopped now; restart per §6):

- SDK-replay cinerater branch (edit propagated, Sci-Fi): trace
  `2be624f4-5f49-4e16-a5be-3864c5893990`, branched from
  `279a4907-3850-4cb6-9bd8-c1f6ab759491`.
- Another SDK-replay (Romance): `0fd7c560-c7f2-4a59-9dda-371f0348a289`.
- Server-side branch (triage-shaped, with ghosts): seeded `triage_demo`
  `4dd58a5f-...` → branch `6ba01ec7-...`.

**Make a fresh SDK-side branch (propagating) via the CLI:**
```bash
cd /Users/adityachauhan/Desktop/Loupe_Project
LKEY=$(grep LOUPE_API_KEY dashboard/.env.local | cut -d= -f2)
GKEY=$(grep '^GROQ_API_KEY' server/.env | cut -d= -f2)
# run the agent once to get a fresh trace in the right project:
LOUPE_HOST=http://localhost:8000 LOUPE_API_KEY="$LKEY" GROQ_API_KEY="$GKEY" \
  python3.11 -m examples.cinerater.agent "best crime thriller"
# then branch its first llm span:
GROQ_API_KEY="$GKEY" python3.11 -m loupe.cli replay \
  --agent examples.cinerater.agent:recommend \
  --trace <trace_id> --span <first_llm_span_id> \
  --output '{"content": "{\"genre\": \"Sci-Fi\", \"year\": 2022}"}' \
  --api-key "$LKEY" --host http://localhost:8000
```
(`loupe` isn't a global command yet — SDK 0.3.0 is not published; use
`python3.11 -m loupe.cli`. Local source is what runs: `loupe.__file__` →
`sdk/loupe/...`.)

---

## 8. Quick file map (Phase 7 relevant)

- `dashboard/components/ReplayDiff.tsx` — existing side-by-side diff to adapt
- `dashboard/app/replays/[id]/page.tsx` — v1 diff page (pattern to follow)
- `dashboard/app/traces/[id]/page.tsx` — trace detail; has the lineage banner to
  add a "View diff" link to
- `dashboard/components/SpanTree.tsx` — marker badges + ghost dimming (reference)
- `dashboard/components/AutoRefresh.tsx` — polling
- `dashboard/lib/api.ts` — `getTrace`, `getReplay`, `TraceDetail` (has
  `branched_from_*`), `ReplayDetail` (diff_summary, modifications)
- `server/app/routers/replays.py` — `_run_branch` engine + `replays` diff_summary
  (`{token_delta, latency_delta_ms, status, branch_span_id}`)
- `server/app/routers/traces.py` — branch endpoint, ingest (persists branched_from)
- `server/app/schemas.py` — `TraceDetail` (branched_from_*), `BranchIn/BranchCreated`
- `sdk/loupe/_replay.py`, `sdk/loupe/core.py` (`replay()`), `sdk/loupe/cli.py`
- `notes/24-branch-replay-engine.md`, `notes/25-sdk-side-replay.md` — the design +
  interview Q&A for everything built so far. **Read these.**

---

## 9. Honest limitation to keep in mind (and likely surface in the diff)

Server-side branches don't propagate edits (ghosts show the *old* inputs).
SDK-side replays do. So when diffing a **server-side** branch, the downstream
"new" outputs will look unchanged except where an LLM directly re-ran — that's
expected, not a bug. The diff for an **SDK-side** branch is the compelling one
(downstream genuinely changes). Consider labeling which kind of branch it is
(server vs SDK) — though note the DB doesn't currently store that flag explicitly;
you can infer "server-side" if a `replays` row exists for the branch, "SDK-side"
if not. (Discuss with the user whether to add an explicit marker.)

---

## 10. First message to send in the new chat

> "Read HANDOFF_PHASE7.md and continue. Start Phase 7 — the branched-vs-original
> diff view. Teach as you build, one sub-step at a time, and we test rigorously as
> we go. Work in simple Hinglish."

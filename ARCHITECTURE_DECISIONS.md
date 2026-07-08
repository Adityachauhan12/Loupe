# Loupe — Architecture Decisions & Open Roadblocks

> **Purpose.** A single place that records (a) the architectural decisions we have
> already locked and *why*, and (b) the conceptual roadblocks still open — each
> laid out as *tension → options → tradeoffs → recommendation → decision needed*.
>
> **How we use it.** We go through **Part B** one item at a time. When we settle
> one, we flip its status to `RESOLVED` and write the chosen answer + a one-line
> rationale inline. Nothing in Part B is decided until we say so together. This
> doc is the agenda; building resumes once the blocking items are `RESOLVED`.
>
> Status legend: 🔒 LOCKED · 🟡 OPEN (needs decision) · 🔵 FUTURE (not blocking now)
>
> Last updated: 2026-06-30 · Phase: v2, between Phase 7 (branch diff) and Track D.
> **All open blockers B1–B7 are RESOLVED** (B8/B9/B10 are FUTURE). The decisions produced
> a concrete build backlog — see "Consolidated build backlog" at the end. Building resumes
> from there.

---

## Part 0 — Decision status board

| ID | Topic | Status |
|----|-------|--------|
| A1 | Postgres over ClickHouse | 🔒 |
| A2 | Flat LLM fields on `spans` (no separate llm table) | 🔒 |
| A3 | SDK generates trace/span IDs | 🔒 |
| A4 | Replays live in the `traces` table | 🔒 |
| A5 | `BackgroundTasks` over Celery/Redis | 🔒 |
| A6 | API-key auth, single project | 🔒 |
| A7 | Polling over WebSockets | 🔒 |
| A8 | Deterministic replay = freeze-before / live-after | 🔒 (see design doc) |
| A9 | Side-effect policy = dry-run writes by default | 🔒 (see design doc) |
| **B1** | **Two kinds of replay (server-side vs SDK-side) — which is the product?** | ✅ RESOLVED → (1) |
| **B2** | **`replays` table vs `branched_from` columns — source of truth** | ✅ RESOLVED → (A) + SDK writes a row |
| **B3** | **Branch "kind" is inferred, not stored** | ✅ RESOLVED → (A) explicit `replay_mode` |
| **B4** | **Provider-call logic duplicated (server engine vs SDK integrations)** | 🟡 |
| **B5** | **Cost/token honesty inside a branched trace** | ✅ RESOLVED → (A) blended + note |
| **B6** | **Replay boundary — what is actually replayable (external state)** | ✅ RESOLVED → (A) document boundary |
| **B7** | **Authz & cost of server-side branch (whose API keys?)** | ✅ RESOLVED → (A)+(B) document + guard |
| **B8** | **Judge / suite infra (v2.2)** — expanded into B8.1–B8.4 | ✅ RESOLVED (see below) |
| B9 | Replay-plan concurrency (ContextVar / async / threads) | 🔵 |
| B10 | Embedded outbound worker (server-side branch runs real tools) — B1 option (3) | 🔵 PLANNED (future) |
| **B11** | **PII / secret redaction — before capture and before the judge** | 🟡 OPEN (needs decision) |

---

## Part A — Locked decisions (reference)

These are settled. Listed so the base is explicit; tradeoffs are interview-ready.
Full reasoning for most lives in [CLAUDE.md](CLAUDE.md) → "Key Design Decisions".

- **A1 — Postgres over ClickHouse.** ClickHouse is the "correct at scale" answer for
  trace/time-series data. Postgres + JSONB + good indexes is far simpler to operate
  for one developer and handles millions of rows. Clean migration path later.
- **A2 — Flat LLM fields on `spans`.** LLM-specific columns (model, tokens, cost) sit
  NULL on non-LLM spans rather than living in a separate joined table. At ~4 span
  types, flat + NULL beats joins on every read. Revisit past ~10 types.
- **A3 — SDK-generated UUIDs.** The SDK mints trace/span IDs so it can build the whole
  span tree locally and ship it in one idempotent batch — no per-span server round-trips.
- **A4 — Replays live in `traces`.** A replay/branch is structurally a normal trace, so
  it reuses the same schema, queries, and detail page for free.
- **A5 — `BackgroundTasks` over Celery/Redis.** Enough for MVP concurrency; a broker is
  operational weight we don't need yet. Migrate at real concurrency.
- **A6 — API-key auth, single project.** Hashed key in `X-API-Key`. No login/teams (out
  of scope). See **B7** for the replay-cost wrinkle this leaves open.
- **A7 — Polling over WebSockets.** A running trace/branch is polled by full refresh
  (`AutoRefresh`, 2.5–3s). Simpler than a socket layer; fine at this scale.
- **A8 — Deterministic replay.** Freeze every span *before* the branch point (stored
  output), re-run the branch point and everything after. "Deterministic" = isolate the
  one variable that changed, not "the LLM is repeatable." Full design + example:
  [docs/design-deterministic-replay.md](docs/design-deterministic-replay.md).
- **A9 — Side-effect policy.** After the branch point: LLM/read/pure → live; write tool →
  dry-run (ghost span) by default; opt a tool into live with `replay="live"`. Full design:
  [docs/design-replay-side-effects.md](docs/design-replay-side-effects.md).

---

## Part B — Open roadblocks (the agenda)

Each item: the **tension**, the **options**, **tradeoffs**, **my recommendation**, and
the exact **decision needed**. We resolve these one by one.

---

### B1 — Two kinds of replay: which one is the product? ✅ RESOLVED → (1)

> **Decision (2026-06-26): Option (1).** SDK-side replay is the canonical product — the
> "true branch" where edits propagate and real tools re-execute. Server-side branch is
> kept as an honestly-labeled **"preview (LLM-only, tools not re-run)"**. Both stay; the
> hierarchy is made explicit everywhere (dashboard button + diff caveat).
> **Rationale:** preserves both the one-click dashboard demo and the deep CLI demo, and
> converts the server-side limitation from a confusing inconsistency into a labeled
> feature. **Follow-ons unlocked:** B4 → accept the bounded duplication (option A);
> B3 → add an explicit `replay_mode` column. Option (3) (unify via a worker) is the
> documented control-plane/execution-plane path, **deferred** — see the B1 explainer.

**The tension.** We have built *two* engines that both "branch a trace," with different
capabilities — and we have never formally decided how they relate.

| | Server-side branch | SDK-side replay |
|---|---|---|
| Where it runs | Server `BackgroundTask` ([replays.py](server/app/routers/replays.py) `_run_branch`) | User's own process ([core.py](sdk/loupe/core.py) `replay()`) |
| Trigger | Dashboard "⑂ Branch from here" button | `loupe.replay()` / `loupe replay` CLI |
| Can run user tool functions? | **No** — they live in the user's process → ghosts / passthrough | **Yes** — real tools re-execute |
| Does the edit propagate downstream? | **No** (downstream sees old inputs) | **Yes** (true counterfactual) |
| Re-runs LLM calls | Yes (server has provider keys) | Yes (in-process) |
| Creates a `replays` row | Yes | No |

This split is the root cause of several downstream items (B2, B3, B4). It bit us in
Phase 7: the diff has to *infer* which kind it's looking at and caveat the result.

**Why it exists.** The dashboard button is appealing (one click, no code), but the
server fundamentally cannot execute the user's Python tool bodies. So the server path
is honest-but-limited (good for "preview the LLM change, skip real writes"), while the
SDK path is the real time-travel debugger but requires running code locally.

**Options.**
- **(1) SDK-side is the product; server-side is a "preview" feature.** Position the
  dashboard button explicitly as "Quick preview (LLM-only, writes skipped)" and make
  `loupe.replay`/CLI the headline "true branch." Keep both, label them clearly.
- **(2) Drop server-side branching.** Make branching SDK-only. Dashboard button becomes
  "copy the `loupe replay` command for this span." Removes the limited path entirely.
- **(3) Keep both as co-equal**, invest to shrink the gap (e.g. server calls back into a
  user-registered worker to run tools). Most work, blurs the simple story.

**Tradeoffs.** (1) keeps the slick demo *and* the real one, at the cost of explaining
two modes. (2) is the cleanest mental model and least code to maintain, but loses the
zero-setup dashboard demo that's great for a portfolio screenshot. (3) is real product
work with little portfolio payoff right now.

**My recommendation: (1).** Keep both, but make the hierarchy explicit everywhere —
SDK-side = "true branch (edit propagates)", server-side = "preview (LLM-only)". This
preserves the one-click demo and the compelling deep demo, and it turns the limitation
into an honestly-labeled feature instead of a confusing inconsistency. It also makes
B3 (store the kind) the natural follow-up.

**Decision needed.** Is SDK-side the canonical product with server-side as a labeled
preview (1), do we drop server-side (2), or invest to unify (3)?

---

### B1 explainer — control plane vs execution plane (the trust boundary)

> This subsection is the *mental model* behind B1. It explains **why** the server can
> never run user tools, what "deploy a worker" actually means, and how to do it without
> asking users to deploy their app twice. It's the most interview-valuable idea in the
> project, so it's written out in full.

**The one rule everything follows.** To re-run a tool like `search_movies()` with *new*
arguments, **some process must already have the user's Python code loaded.** Code that
doesn't exist on a box can't run on that box. The Loupe server (Render) is *Loupe's*
generic code — it never contains any user's tool bodies — so it physically cannot execute
them. That single fact, not a missing feature, is the root of B1.

**"Server vs SDK" is not "cloud vs laptop."** Two independent axes get conflated:
- **Axis 1 — location:** laptop or cloud.
- **Axis 2 — ownership/role:** *whose* code is it, and *what job* does it do.

"Server" and "SDK" are answers to **Axis 2**. A *deployed SDK is still the SDK.*

- **Loupe server** = Loupe's code; generic; multi-tenant-shaped. **Control plane** —
  stores traces, serves the dashboard, holds the job queue. Owns no user code or secrets.
- **Loupe SDK** = a library that runs *inside the user's app*, mixed with the user's code.
  **Execution plane** — runs real tools, holds the user's DB creds and provider keys.
  Runs wherever the user's app runs (laptop *or* a deployed service).

**There are really three processes, not two:**

| Process | Whose code | Where | Role |
|---|---|---|---|
| Loupe server | Loupe's | Render | Control plane: store, queue, route |
| Loupe dashboard | Loupe's | Vercel | UI |
| User's agent app (imports Loupe SDK) | **User's** | laptop **or** a service the user runs | Execution plane: runs real tools |

**Why they can never merge into one wing.** The boundary is **trust, not distance.**
Merging the worker into the Loupe server would mean uploading the user's proprietary
source *and* their production secrets (DB creds, paid-API keys) onto Loupe's box. Same
split as **GitHub (control plane) vs a self-hosted Actions runner (your machine, your
code)**, or **Temporal server vs Temporal workers**. The runner is "deployed" but it's
still *yours*, not GitHub's.

**Mental model:** *Server = the post office (routes messages, owns no packages).
SDK/worker = your house (has your stuff, does the work). Deploying your house to the
cloud doesn't make it the post office.*

**"But nobody deploys their app twice just to use us."** Correct — and the worker
pattern does **not** require a second deployment. It's an **embedded listener** inside
the app the user *already* runs:

```python
loupe.init(api_key=..., worker=True)   # background thread dials OUT to Loupe, waits for jobs
```

Same process, same deploy, one flag. This is exactly how **Sentry / Datadog /
OpenTelemetry** agents work — in-process, not a separate box. The connection is
**outbound** (websocket/long-poll), so there are no inbound ports and no firewall/NAT
changes; and because it's the user's own process, the code, DB creds, and keys are
already loaded — nothing ships to Loupe.

**The real risk this surfaces is safety, not deployment.** A worker embedded in
*production* means clicking "⑂ Branch" re-runs *real* tools in prod. `search_movies()`
(read-only) is fine; `charge_card()` would charge again. Mitigations (consistent with
**A9**):
- Run the worker in **staging**, not prod (same code, safe data).
- **Replay-safe flags** — `@loupe.tool(replay_safe=False)` returns the stored ghost
  output on replay instead of firing. Read-only tools re-run live; dangerous ones mock.

**Where this nets out for Loupe.** For the **North Star demo (a developer debugging a
failed trace)**, *none* of this infra is needed — the developer already has the code on
their laptop, so `loupe replay` locally is the natural zero-setup path. The deployed
worker only matters for a narrower future case: a non-developer clicking "branch"
against a live system. So:
- **Today / for the demo:** nothing to build — local `loupe replay`.
- **For a hosted product later:** embedded worker (one flag, outbound) + replay-safe
  flags. This is B1 option (3) — **committed as a future direction, tracked in B10** (not
  built now, but the design stays coherent toward it).

**Interview line:** *"Server-side branch is LLM-only by design because the server is the
control plane and can't execute user tool code — that's a trust boundary, not a missing
feature. True counterfactuals run in the execution plane (the SDK), locally for
debugging or as an embedded outbound worker for hosted use, like a self-hosted CI
runner. I scoped the worker and deferred it because the debugging demo doesn't need it."*

---

### B2 — `replays` table vs `branched_from` columns: source of truth ✅ RESOLVED → (A) + SDK writes a row

> **Decision (2026-06-30): Option (A) + SDK-side branches also get a `replays` row.**
> `branched_from_trace_id` / `branched_from_span_id` on the child trace stay the **source
> of truth for lineage** (the diff already reads them; always present on every branch).
> *Additionally*, **every** branch — server *and* SDK — gets a `replays` row so the table
> is uniform and "list all replays/branches" is one query. **Rationale:** data
> consistency — both representations exist for both paths; no path is half-recorded.
>
> **Chosen implementation: the server auto-creates the `replays` row at ingest.** When a
> trace is ingested with `branched_from_*` set and no `replays` row yet exists for it, the
> ingest endpoint creates one — `original_trace_id` / `new_trace_id` from the lineage,
> `modifications = {branch_span_id, new_output?}`, and `diff_summary` (token/latency/status
> deltas) computed against the original, which is already in the DB. *Why server-side, not
> SDK-side:* keeps the SDK unchanged (it already sets `branched_from`), avoids a second
> round-trip, and centralises row-creation so server-side and SDK branches go through the
> exact same code. **Idempotent:** skip if a row already exists (server-side branches make
> theirs explicitly in the branch endpoint).
> **Build task** (when we resume): add the auto-create-on-ingest logic in
> [server/app/routers/traces.py](server/app/routers/traces.py) `ingest_trace`; guard on
> "has `branched_from` and no existing `replays` row."

**The tension.** The parent→child link of a branch is currently expressed *two* ways:
- `traces.branched_from_trace_id` + `traces.branched_from_span_id` (on the child trace)
- a row in the `replays` table (`original_trace_id`, `new_trace_id`, `modifications`,
  `diff_summary`)

Server-side branches write **both**. SDK-side replays write **only** `branched_from`
(no `replays` row). So the two representations disagree about what exists, and the diff
view had to choose one. Phase 7 chose `branched_from` (covers both) — which means the
`replays` row is now *optional metadata*, not the source of truth.

**Options.**
- **(A) `branched_from` is the source of truth; `replays` becomes a derived cache.**
  Diff lineage always reads `branched_from`. Keep `replays` only for the v1 whole-trace
  replay flow and as an optional precomputed `diff_summary`. Optionally also write a
  `replays` row from the SDK path for consistency.
- **(B) Make `replays` authoritative; backfill it from every branch path.** SDK-side
  replay would POST a `replays` row too. More moving parts, but one table to query for
  "all replays/branches."
- **(C) Collapse them.** Drop the `replays` table; move `modifications`/`diff_summary`
  onto the trace (or compute diff on the fly). Fewer concepts; loses the precomputed
  server `diff_summary` and the v1 replay flow's home.

**Tradeoffs.** (A) matches what we already shipped in Phase 7 and needs the least
change; the cost is "two tables, clear roles" which must be documented. (B) gives one
query surface but adds an SDK→server write and FK ordering concerns. (C) is the
simplest model long-term but is the most invasive refactor and removes a working table.

**My recommendation: (A).** Declare `branched_from_*` the source of truth for *lineage*;
treat `replays.diff_summary` as an optional precomputed convenience. Document the roles.
Decide separately (small) whether the SDK path should also drop a `replays` row purely
so "list all replays" is uniform — I lean yes, low cost.

**Decision needed.** Confirm `branched_from` as lineage source of truth (A) vs making
`replays` authoritative (B) vs collapsing the table (C). And: should SDK-side replay
also write a `replays` row?

---

### B3 — Branch "kind" is inferred, not stored ✅ RESOLVED → (A) explicit `replay_mode`

> **Decision (2026-06-30): Option (A).** Add an explicit nullable column
> `traces.replay_mode` (`'server' | 'sdk' | null`), set when a branch is created. The diff
> view reads it directly; the marker-based inference (`lib/diff.ts` `inferKind`) is kept
> only as a fallback for pre-existing rows. **Rationale:** the server-vs-SDK distinction is
> user-facing (B1: "preview" vs "true branch"), so it should be stored, not guessed — a
> first-span branch currently shows a vague "unknown". Cost is tiny and we're already
> touching branch-creation for B2.
>
> **Build tasks** (when we resume):
> - Alembic migration: add `replay_mode TEXT NULL` to `traces`.
> - Set `'server'` in the branch endpoint ([replays.py](server/app/routers/replays.py),
>   `create`/`_run_branch` placeholder trace); set `'sdk'` in the SDK trace payload when a
>   replay plan is active ([sdk/loupe/core.py](sdk/loupe/core.py), where `is_replay` is
>   set) → carried through `TraceIn` → persisted in `ingest_trace`.
> - Expose on `TraceDetail` (server `schemas.py` + dashboard `lib/api.ts`); make
>   `BranchDiff` prefer `trace.replay_mode`, fall back to `inferKind`.

**The tension.** Nothing on a branched trace says "I was made by the server engine" vs
"by the SDK." The Phase 7 diff *guesses* from span markers: sees `dry_run`/
`stored_passthrough` → "server"; sees `replay:"frozen"` → "sdk"; else "unknown". When a
user branches at the very first span there are no markers, so the label is "unknown" —
correct but vague. (Verified live: this is why a first-span branch shows "Branch" not
"SDK-side replay".)

**Options.**
- **(A) Store it explicitly.** Add `traces.replay_mode` (`'server' | 'sdk' | null`) set
  at creation. Diff/label reads it directly; inference becomes a fallback for old rows.
- **(B) Leave inference as-is.** Accept "unknown" for marker-less branches; it's only a
  label.
- **(C) Derive from B2's decision** — e.g. "has a `replays` row ⇒ server-side." Couples
  this to the table semantics.

**Tradeoffs.** (A) is a tiny migration + a field set in two code paths, and makes the
diff label always correct and honest — directly improves the headline view. (B) is zero
work but leaves a vague label on a flagship screen. (C) avoids a new column but entangles
two concerns and breaks if B2 goes toward collapsing `replays`.

**My recommendation: (A).** One nullable column, set where each branch is created. Small,
removes a user-facing vagueness on the diff view, and survives whatever we pick in B2.

**Decision needed.** Add an explicit `replay_mode` column (A), or keep inference (B)?

---

### B4 — Provider-call logic is duplicated 🟡

**The tension.** Provider quirks are implemented **twice**:
- SDK integrations wrap OpenAI/Anthropic/Groq client calls ([sdk/loupe/integrations/](sdk/loupe/integrations/)).
- The server replay engine re-implements raw HTTP calls to the same providers
  (`_call_openai`, `_call_anthropic`, `_call_groq`, `_invoke_llm` in
  [replays.py](server/app/routers/replays.py)) — including subtleties like Anthropic's
  separate `system` field, the empty-messages guard, and `.strip()`-ing keys.

Two places to fix every provider change. This duplication only exists *because* of the
server-side branch path (B1) — the SDK path reuses the SDK integrations.

**Options.**
- **(A) Resolve B1 toward SDK-first, then let the server path wither.** If server-side
  becomes a labeled "LLM-only preview," its provider code is small and stable; accept the
  duplication as the price of the one-click demo.
- **(B) Extract a tiny shared "provider call" core** importable by both SDK and server.
  Removes duplication but couples the two deployables (server would import SDK internals
  or a shared package).
- **(C) Drop server-side LLM re-execution** (ties to B1 option 2) — duplication disappears
  with the path.

**Tradeoffs.** (A) least effort, duplication remains but bounded. (B) DRY, but creates a
shared dependency between server and SDK that must be versioned. (C) cleanest, but only if
B1 goes that way.

**My recommendation: defer to B1.** This is a *consequence*, not an independent decision.
If B1 = "SDK-first, server is preview," pick (A) and move on. Revisit only if provider
churn becomes painful.

**Decision needed.** None standalone — fold into B1. (Noted here so it isn't forgotten.)

---

### B5 — Cost/token honesty inside a branched trace ✅ RESOLVED → (A) blended + note

> **Decision (2026-06-30): Option (A).** Keep blended trace totals (frozen spans reuse the
> original's tokens/cost, re-run spans carry new real numbers, ghosts carry none) and make
> them honest with a one-line caveat on the diff rather than new schema. **Rationale:** the
> numbers are already correct; they only *read* oddly (a small edit can show ~0 token delta
> because most spans were frozen copies — which is the truth). A label fixes the perception
> for free; splitting new-vs-reused cost (B) is real schema + UI for marginal demo value.
> **Build task** (when we resume): extend the existing "frozen" note in
> [BranchDiff.tsx](dashboard/components/BranchDiff.tsx) to add: *"Frozen spans reuse the
> original's tokens/cost; deltas reflect only re-run spans."* Revisit (B) only if we build
> real cost analytics.

**The tension.** A branched trace mixes spans of different provenance: frozen spans keep
the *original's* tokens/cost, re-run spans carry *new* real numbers, ghost spans carry
`None`. The trace-level `total_tokens`/`total_cost` is therefore a blend of "newly spent"
and "copied from the original." The diff's `Δ tokens` / `Δ cost` compares these blended
totals — which can read oddly (e.g. a tiny edit shows ~0 token delta because most spans
were frozen copies, which is *correct* but unintuitive).

**Options.**
- **(A) Keep blended totals, explain in the diff.** Add a small note: "frozen spans reuse
  the original's tokens; deltas reflect only re-run spans." Honest, zero schema change.
- **(B) Track "new vs reused" separately.** Sum only re-executed spans into a
  `replay_cost`, show both. More precise, more fields, more UI.
- **(C) Ignore — totals are close enough at demo scale.**

**Tradeoffs.** (A) is cheap and makes the existing numbers trustworthy by labeling them.
(B) is the "correct" analytics answer but adds schema + UI for marginal demo value. (C)
risks a confusing delta on a flagship view.

**My recommendation: (A) now, (B) only if we productionize cost analytics.** A one-line
caveat on the diff (we already render a "frozen" note — extend it) makes the deltas honest
without new plumbing.

**Decision needed.** Accept blended totals + a clarifying note (A), or split new-vs-reused
cost (B)?

---

### B6 — Replay boundary: what is actually replayable? ✅ RESOLVED → (A) document boundary

> **Decision (2026-06-30): Option (A).** Make the boundary explicit instead of widening
> capture: replay is faithful only for spans whose inputs were captured; un-instrumented
> external state (wall-clock time, RNG, live DB/API reads, env, files) is best-effort and
> can cause edit-unrelated divergence. **Rationale:** this is a fundamental property of
> non-deterministic agents, not an engine bug — consistent with A8's honesty. We already
> capture seed/temperature. Broadening to time/RNG (B) is real, never-total work; full
> record-replay (C) is a research project. **Build tasks** (when we resume): add a "What
> replay guarantees / does not guarantee" section to the README and a boundary note in
> [docs/design-deterministic-replay.md](docs/design-deterministic-replay.md). Keep (B) as
> opt-in future polish — e.g. an option to freeze a tool's *output* on replay for agents
> with un-replayable reads.

**The tension.** SDK-side replay re-runs the agent from the original's captured `input`
(args/kwargs) and freezes spans before the branch. But an agent can depend on state we
*don't* capture: wall-clock time, RNG, a live DB/API read, environment, files. If
downstream code reads such state, the replayed run diverges for reasons unrelated to the
edit — quietly undermining the "controlled experiment" promise (A8).

**Options.**
- **(A) Document the boundary; capture-and-freeze is the contract.** State plainly:
  replay is faithful only for spans whose inputs were captured; external/un-instrumented
  state is best-effort. This matches the honesty already in the deterministic-replay doc.
- **(B) Broaden capture.** Snapshot more (seed, time, tool inputs/outputs) and replay them
  deterministically. We already capture seed/temperature; extending to time/RNG is real
  work and never total.
- **(C) Sandbox / record-replay everything** (à la `rr`). Out of scope — huge.

**Tradeoffs.** (A) sets honest expectations for free and is consistent with our stated
philosophy. (B) buys more fidelity incrementally but never reaches 100% and adds capture
overhead. (C) is a research project.

**My recommendation: (A), with seed/temperature already in hand.** Write the boundary into
the design doc and the README's "what replay guarantees" section. Treat (B) as opt-in
future polish (e.g. freeze tool *outputs* on request).

**Decision needed.** Are we content to document the capture-and-freeze boundary (A), or do
we want to invest in broader deterministic capture now (B)?

---

### B7 — Authz & cost of server-side branch (whose keys?) ✅ RESOLVED → (A)+(B) document + guard

> **Decision (2026-06-30): Option (A) + (B).** Document the key/cost model *and* add a
> minimal guard. **Rationale:** the implicit "a dashboard click spends the server
> operator's unbounded API budget" is fine for single-user self-host (A6) but worth a cheap
> safety net, and it's a strong "I thought about abuse" signal. Not building tenant billing
> (C) — out of scope.
> **Build tasks** (when we resume):
> - **(A)** README/self-host docs: state that server-side branch re-runs LLM calls with the
>   **server's** configured provider keys; self-host/budget accordingly.
> - **(B)** Config flag `ALLOW_SERVER_SIDE_LLM_REPLAY` (default on for self-host) that, when
>   off, makes the branch endpoint skip live LLM re-execution (ghost/passthrough only) — so
>   a shared deployment can't have its keys spent by branch clicks. Optionally a simple
>   per-API-key/day branch cap. Small, in [replays.py](server/app/routers/replays.py) +
>   [config.py](server/app/config.py).

**The tension.** The server-side branch re-runs LLM calls using the **server's** provider
keys ([config.settings](server/app/config.py)), triggered by anyone holding a project API
key, with no rate limit. On self-hosted single-user MVP that's fine (you pay for your own
keys). But it's an implicit decision: a dashboard click spends the server operator's API
budget, server-side, unbounded.

**Options.**
- **(A) Accept for self-hosted MVP; document it.** "Server-side branch uses the server's
  configured provider keys; self-host accordingly." No code change.
- **(B) Add a guard.** Simple per-key/day branch cap or a config flag to disable
  server-side LLM re-execution. Small, defends against accidents.
- **(C) Full multi-tenant cost isolation.** Out of scope (no teams/billing per A6).

**Tradeoffs.** (A) matches the MVP's single-user posture and current scope boundaries.
(B) is cheap insurance and a nice "I thought about abuse" interview point. (C) contradicts
scope.

**My recommendation: (A) now + a noted (B) as a 1-hour follow-up.** Document the key/cost
model; optionally add a config switch to disable server-side LLM re-exec for shared
deployments. Don't build tenant billing.

**Decision needed.** Document-and-accept (A), or also add a minimal cap/flag (B)?

---

### B8 — Judge / suite infrastructure (v2.2) ✅ RESOLVED → B8.1–B8.4

> **Decided (2026-07-03).** The v2.2 "Prompt CI/CD" umbrella — golden suites of saved traces,
> a `JudgeService` scoring replay-vs-original, suite-run storage, CLI, and a GitHub Action —
> is now designed. The four sub-decisions below are locked. Plain-language walkthrough with
> examples: [docs/concepts-explained.md](docs/concepts-explained.md). Build order: DB →
> JudgeService → endpoints → CLI → GitHub Action.

#### B8.1 — Suite storage: reference vs copy ✅ (A) reference, join table

**Tension.** A suite is a *collection* of traces — store trace **IDs** (by reference) or
**copy** each trace's data into the suite?
**Decision: (A) by reference, via a `suite_traces` join table.** Traces are **immutable** in
Loupe (never updated post-ingest), so the only real benefit of copying — a frozen snapshot —
doesn't apply. Matches **A4** (single source of truth in `traces`). A join table keeps
membership queryable both ways with FK integrity (vs a JSONB array, which loses FKs/indexing).
```
suites:        id, name, project_id, judge_rubric TEXT NULL, created_at
suite_traces:  suite_id → suites.id,  trace_id → traces.id   (composite PK)
```

#### B8.2 — Shape of a suite run ✅ (A) JSONB `results`

**Tension.** A run needs a **summary** (pass/fail counts for the PR comment) and **per-trace
detail** (verdict, reasoning, `new_trace_id` for the diff view). Per-trace detail in a JSONB
column, or a normalized child table?
**Decision: (A) one `suite_runs` row, per-trace results in a JSONB column.** A run is always
read *as a whole* (PR comment, one detail page) — never cross-run analytics — so a normalized
table buys nothing yet. Same call as span payloads in JSONB (**A1**). Revisit only if real
cross-run analytics appears.
```
suite_runs:
  id, suite_id, status ('running'|'done'|'error'),
  prompt_override TEXT, model_override TEXT NULL, judge_backend TEXT,
  total, passed, regressed, improved, errored,
  results JSONB,   -- [{trace_id, new_trace_id, verdict, score_source,
                   --   reasoning, confidence, deterministic_checks}, ...]
  started_at, ended_at, created_at
```

#### B8.3 — Judge rubric: global vs per-suite ✅ (A) global default + optional override

**Tension.** One rubric for all suites, or one per suite?
**Decision: (A) a global default rubric + optional per-suite override
(`suites.judge_rubric TEXT NULL`).** A suite works with zero config (default); a
domain-specific suite (e.g. JSON extraction) can supply stricter criteria. Bonus: the shared
default **prompt-caches** across judgments (~90% cheaper reads). Mandatory-per-suite (C) adds
friction for the demo; global-only (B) can't express domain-specific criteria.

#### B8.4 — Scoring: agentic vs hybrid; judge backend ✅ hybrid + pluggable backend

**Tension.** Should the scorer be an **agent** (multi-step) or a **single Claude call +
regex**? And which model/provider judges?
**Decision — hybrid, single-call judge, pluggable backend:**
- **Not agentic.** Comparing two short outputs is a **classification** task — a single
  rubric-driven call is as accurate as an agent, cheaper, and with fewer failure modes.
  (Agentic here would be an over-engineering red flag.)
- **Deterministic checks first (free).** Structured/tool spans → regex/assert
  (`{"genre": "Sci-Fi"}` → `assert genre == expected`). No LLM call. Can't judge free-text
  *meaning*.
- **LLM judge only on the free-text final answer.** A single structured-output call →
  `{label: equivalent|improved|regressed, reasoning, confidence}`, driven by the B8.3 rubric.
- **Pluggable backend (`judge_backend`):**
  - **Default for development: free Groq/Llama (Llama 3.3 70B)** — keeps the whole loop **$0**
    to build and self-host; reuses the SDK's existing Groq integration.
  - **Optional for demo / production: Claude Sonnet 4.6** — stronger `improved` vs `regressed`
    nuance; per-suite/run override.
- **Cost context (why this is fine either way).** A 100-trace run is <$1 on Claude
  (~$0.39 Sonnet with prompt-cache + Batch API, 50% off), single-double-digit $/month at
  typical volume. **Free-tier caveat:** one ~100-trace run ≈ ~180k tokens ≈ a whole ~200k free
  daily budget, and free RPM limits can throttle large runs — so the free backend is for
  **demos + small suites** (~10–15 traces ≈ ~27k tokens/run), not frequent large-suite CI.
  Demo strategy: **iterate on free Groq, capture final screenshots on Sonnet.**

**Why this is portfolio-strong.** Provider-pluggable judge defaulting to a free backend =
"zero-cost to self-host, Claude as an opt-in quality upgrade" — a clear "I thought about cost
and accessibility" signal, on top of the production-trace → regression-suite → PR-gate loop.

#### B8.5 — GitHub Action packaging & gate policy (D1–D5) ✅

**D1 — Action packaging: composite (wraps the CLI), not a TS action.** The CLI already
does the whole job (call → poll → summary → exit code), so a full TypeScript action would
re-implement it. The Action is a thin composite `action.yml`: set up Python → `pip install
loupe-sdk` → `loupe suite run` → `gh pr comment`. One engine, two entry points (human CLI +
CI). Deviates from CLAUDE.md's "small TS action" note — justified because the CLI didn't
exist when that was written. *(A TS action remains an option purely for a resume bullet; not
worth the duplication.)*

**D2 — PR → suite/prompt mapping: explicit inputs.** The workflow passes `suite-id` and
`prompt-file` explicitly (plus `loupe-host` / `api-key` secrets), and a `paths:` filter runs
the Action only when the prompt file changes. The new prompt is the PR-branch content of
`prompt-file` → `prompt_override`. Auto-detecting changed prompt files is future polish;
explicit is deterministic and demo-clear.

**D3 — PR comment + status check.** The status check is the **job's own exit code** — the
CLI exits non-zero on a regression, the step fails, the PR check goes red (no separate
commit-status API). The comment is posted with `gh pr comment` (`GITHUB_TOKEN`) from the
CLI's summary output (counts + per-regression reasoning + diff links).

**D4 — Demo lives in-monorepo first.** `examples/prompt-ci-demo/` (workflow + a prompt file,
reusing the cinerater agent). GitHub-hosted runners can't reach `localhost`, so the demo
points at the **deployed Render** Loupe via repo secrets; free Groq judge + a small suite
(~10–15 traces) keeps it ~$0. A separate public demo repo (more authentic "install
loupe-action in a consuming repo" story, better screenshot) is a later step.

**D5 — Gate policy: zero-tolerance, no confidence gating.** Any `regressed` verdict blocks
the merge (CLI `exit 1` when `regressed > 0`). We deliberately do **not** gate on the judge's
self-reported `confidence`: it's an unreliable number, and gating a shaky signal on another
shaky signal adds noise, not safety. Confidence is stored in `results` for human review only.
A `--max-regressions N` knob (default 0) is left as an optional future loosening for large
suites. *(Already implemented in the CLI; no code change.)*

---

### B9 — Replay-plan concurrency 🔵 FUTURE

SDK-side replay stores its plan in a `ContextVar` ([_replay.py](sdk/loupe/_replay.py)) and
walks span decisions via a cursor. This is correct for a single synchronous agent run. For
`async` agents or threaded fan-out, ContextVar propagation and the shared cursor could
misclassify spans. Not a problem for current (sync) example agents. Revisit if/when we
support async agent entrypoints. Noted so it isn't a silent assumption.

---

### B10 — Embedded outbound worker (real-tool server-side branch) 🔵 PLANNED (future)

> **Status: committed for a later phase, not now.** This is B1 option (3) — the path that
> closes the gap between server-side branch and SDK-side replay. We are *not* building it
> for the MVP/demo (the North Star demo doesn't need it — see the B1 explainer), but it is
> an intended future direction, recorded here so the design stays coherent toward it.

**What it is.** Today server-side branch can't run the user's tool functions (the server is
the control plane; it holds no user code — see the **B1 explainer**). The fix is an
**outbound worker embedded in the user's own app**: a background listener started by one
flag that *dials out* to the Loupe server and waits for replay jobs, runs them **in-process**
(where the real code + secrets already live), and pushes results back. No inbound ports, no
second deployment, no user code on Loupe's box.

```python
loupe.init(api_key=..., worker=True)   # background thread connects OUT, waits for branch jobs
```

This is the **control-plane / execution-plane** split, the same shape as a self-hosted
GitHub Actions runner or a Temporal worker. Loupe server = job queue + router; the user's
embedded worker = the thing that actually executes.

**What it requires (the reason it's deferred, not trivial).**
- A **job queue** on the server (replay jobs) → revisits **A5** (BackgroundTasks → a real
  broker, e.g. Redis/Celery, once there's cross-process work).
- **Worker registration + auth** (which worker may pull which project's jobs).
- An **outbound transport** (long-poll or websocket) so no inbound port is opened.
- **Retries / liveness / result push-back**, i.e. a small distributed-execution system.
- **Replay-safety enforcement at the worker** — write tools must honour `replay_safe`
  (A9) so a prod-embedded worker can't double-charge a card on "⑂ Branch".

**Safety posture (carry this forward).** A worker embedded in **production** means a branch
click re-runs *real* tools. Intended guardrails: run the worker in **staging** by default,
and enforce per-tool replay-safe flags (read-only → live; dangerous → ghost). These align
with the side-effect policy already locked in **A9**.

**When we'd build it.** After the killer demo (Track D) and the B-blockers, and only if we
push toward a **hosted product** where a non-developer clicks "branch" against a live system.
For the developer-debugging demo, local `loupe replay` stays the answer. Until then, every
new design choice should *not* foreclose this path (e.g. keep branch lineage on the trace so
a worker-produced branch ingests identically — already true via **B2 → A**).

---

### B11 — PII / secret redaction: before capture and before the judge 🟡 OPEN

**The tension.** Loupe's capture is **shape-agnostic** (`_to_jsonable` in
[sdk/loupe/core.py](sdk/loupe/core.py) records *any* value as JSON — see
[docs/concepts-explained.md](docs/concepts-explained.md) §6). That's the right call for
"works on any project with zero config," but it has a direct side-effect: if a secret flows
through an instrumented **tool argument** or an **LLM prompt** (`login(password=...)`, a
prompt containing an SSN), Loupe records it in **plaintext JSONB** in Postgres. Verified:
the SDK has **no redaction today** (`grep -riE 'redact|scrub|mask|sensitive|secret'` over
`sdk/loupe/` returns nothing). This is a real leak class shared by every "capture everything"
observability tool (Sentry, Datadog, LangSmith, Helicone) — none of it is Loupe-specific,
and all of them solve it with redaction.

**Why v2.2 raises the stakes.** The `JudgeService` (v2.2) sends trace payloads to **Anthropic**
(a third party) to score them. So a secret in a trace isn't just "sitting in our DB" — it
**leaves to an external LLM provider**. Redaction is therefore needed at *two* boundaries:
(1) before the SDK sends anything to the server, and (2) before the server sends a payload to
the judge.

**The "logged vs merely used" distinction (the mitigation's foundation).** A secret used
*inside* a function is already safe; only secrets passed *as traced input* or embedded *in a
prompt* leak. `search(id)` reading `os.getenv("API_KEY")` internally never appears in a
trace; `search(id, api_key="sk-...")` does. So the primary defense is partly a **usage
convention** (keep secrets in env/secret-managers, out of tool args and prompts) and partly
**code** (scrub what does slip through).

**Options.**
- **(A) SDK-side redaction before serialization + a doc convention.** Add a scrub step in/before
  `_to_jsonable`: **key-based** denylist (`password`, `token`, `secret`, `api_key`,
  `authorization`, `cookie` → `"[REDACTED]"`), optional **value-based** regex (JWT/card/key
  shapes), and `loupe.init(redact_keys=[...])` for user-defined fields. **On by default**
  ("secure by default"). Plus a per-span opt-out (`@loupe.trace(capture=False)`) for auth
  flows. Secrets never leave the user's process.
- **(B) Server-side redaction only.** Scrub at ingest / before the judge. Simpler for the SDK,
  but the secret has *already left the user's machine* and hit our DB — weaker boundary.
- **(C) Both — defense in depth.** SDK-side scrub (primary) **and** a server-side scrub of the
  payload the judge receives (belt-and-suspenders for the third-party hop). Plus existing
  server hygiene (TLS in transit, hashed API keys, access control, retention).
- **(D) Do nothing; document the convention only.** "Don't put secrets in tool args/prompts."
  Zero code, but one careless user leaks — bad default for a tool people self-host.

**Tradeoffs.** (A) fixes it at the strongest boundary (never leaves the process) for modest
SDK work, but a denylist is never exhaustive. (B) is easy but lets the secret reach our DB
first. (C) is the correct production posture and the natural fit for v2.2 (the judge hop
*must* be scrubbed regardless), at a little more work. (D) is a real footgun for a
self-hosted MVP.

**My recommendation: (A) now (on-by-default SDK redaction + per-span opt-out + doc
convention), and the judge-boundary half of (C) as part of v2.2** — the `JudgeService` scrubs
the payload before sending to Anthropic even if SDK redaction is on, since traces may predate
the SDK feature. Don't build full value-based ML redaction; a sensible key denylist + regex
for obvious secret shapes + user-configurable keys is the right scope.

**Decision needed.** SDK-side on-by-default redaction (A), server-only (B), both/defense-in-depth
(C), or document-the-convention-only (D)? And: is redaction **on by default** (recommended) or
opt-in?

---

## Consolidated build backlog (from the B1–B7 decisions)

> **Status (2026-06-30): ✅ IMPLEMENTED & committed.** Items 1–9 shipped across commits
> `c13ccb4` (schema + ingest), `adc7c5c` (branch/SDK replay_mode + B7 guard), `28dd046`
> (dashboard kind from replay_mode + cost caveat), `d08e89b` (labeling + docs). Item 10
> (Phase 7 notes) was committed earlier. Tests: server 65, SDK 30, dashboard build green.
> Remaining: only the optional local DB cleanup of old lineage-less test branches.

Ordered schema → server → SDK → dashboard → docs so each step builds on the last. This is
the agreed work to apply when building resumes.

1. **DB migration (Alembic)** — add `traces.replay_mode TEXT NULL`. *(B3)*
2. **Server `ingest_trace`** ([traces.py](server/app/routers/traces.py)) — (a) persist
   `replay_mode` from the payload; (b) auto-create a `replays` row when the trace has
   `branched_from_*` and none exists yet, with `modifications = {branch_span_id, new_output?}`
   and a `diff_summary` computed vs the original (idempotent — skip if a row exists). *(B2, B3)*
3. **Server branch endpoint** ([replays.py](server/app/routers/replays.py)) — set
   `replay_mode='server'` on the placeholder trace; gate live LLM re-execution behind
   `ALLOW_SERVER_SIDE_LLM_REPLAY` (optional per-key/day cap). *(B3, B7)*
4. **Server config** ([config.py](server/app/config.py)) — add `ALLOW_SERVER_SIDE_LLM_REPLAY`
   (default true). *(B7)*
5. **SDK** ([core.py](sdk/loupe/core.py) + [models.py](sdk/loupe/models.py)) — set
   `replay_mode='sdk'` in the trace payload when a replay plan is active. *(B3)*
6. **Schema exposure** — add `replay_mode` to server `TraceDetail`
   ([schemas.py](server/app/schemas.py)) and dashboard `TraceDetail`
   ([lib/api.ts](dashboard/lib/api.ts)). *(B3)*
7. **Dashboard `BranchDiff`** ([BranchDiff.tsx](dashboard/components/BranchDiff.tsx)) —
   prefer `trace.replay_mode`, fall back to `inferKind`; extend the frozen note with the
   blended-cost caveat. *(B3, B5)*
8. **Labeling (B1)** — make the two modes explicit in the UI: server-side = "preview
   (LLM-only, tools not re-run)", SDK-side = "true branch (edits propagate)" — dashboard
   branch button + diff caveat.
9. **Docs** — README "What replay guarantees / does not" + boundary note in
   [docs/design-deterministic-replay.md](docs/design-deterministic-replay.md) *(B6)*;
   server-side-keys note for self-host *(B7-A)*.
10. **Phase 7 wrap-up (already pending)** — `notes/26-branch-diff-view.md` (incl. the
    stale-server debugging story) + `notes/README.md` index + commit; and decide the old
    lineage-less test branches (delete the junk `636c6be8` vs leave all).

> Items 1–7 are a coherent migration-backed change set; 8–9 are docs/UX; 10 closes Phase 7.

---

## Appendix — How this maps to what we just shipped (Phase 7)

The branch-diff view ([dashboard/lib/diff.ts](dashboard/lib/diff.ts),
[components/BranchDiff.tsx](dashboard/components/BranchDiff.tsx),
[app/traces/[id]/diff/page.tsx](dashboard/app/traces/[id]/diff/page.tsx)) deliberately
keyed off `branched_from_*` (pre-deciding **B2 → A** in practice) and *infers* branch kind
(the thing **B3** proposes to make explicit). It renders an honest caveat per kind
(**B1**'s labeling idea, lightweight). So Phase 7 already leans toward my B1/B2/B3
recommendations — confirming them just makes the implicit explicit. The stale-server bug we
hit during verification was an *operational* issue (old process serving old code), not an
architectural one, and is not tracked here.

# 24 — Branch Replay Engine (the heart of v2)

> This is the feature that makes Loupe a *debugger*, not a dashboard. It takes a
> recorded trace, lets you edit one step in the middle, and re-runs from there —
> so you can answer "what *should* have happened?" without re-running the whole
> agent live against the real world.

---

## The one-line idea

> **Freeze before the branch, re-run at and after it, dry-run the writes.**

That single sentence is the entire engine. Everything below is just the details
of making it true.

---

## The problem it solves

An agent failed in production. You want to know: *if it had classified that
issue correctly, would the rest have worked?*

You can't just re-run the agent — it's non-deterministic (the LLM might answer
differently this time), and the world moved on (the GitHub issue might be closed,
the API might return different data). And re-running would **repeat side effects**
— post the comment again, add the label again.

So we need a *controlled experiment*: change exactly ONE thing (the step you
edited), hold everything else fixed, and see the effect.

---

## The 3-bucket rule

Sort a trace's spans in time order. Pick one span as the **branch point**. Every
span now falls into exactly one bucket:

| Bucket | What the engine does | Why |
|--------|----------------------|-----|
| **Before** the branch | copy the stored output (freeze) | nothing upstream of your edit is allowed to vary — that's what makes it a controlled experiment |
| **At** the branch | use *your* edited output, don't execute | this edit IS the change you're testing |
| **After** the branch | re-execute, honouring the side-effect policy | this is the counterfactual you want to see |

"After the branch" is where all the subtlety lives.

### What happens to each span type *after* the branch

| Span type | Behaviour | Reason |
|-----------|-----------|--------|
| `llm` | re-run live (call the provider) | stateless; the whole point of replay |
| write tool (e.g. `post_comment`) | **dry-run → ghost span** | re-running a write duplicates real-world actions |
| live read / `retrieval` / `function` | **pass through stored output** | safe in spirit, but the server can't run user code (see below) |

A **ghost span** is a synthetic record that says *"this is what I would have
done"* — `output = {"would_have": <the inputs>}`, tagged `dry_run: true`. The
dashboard will show it greyed-out. No GitHub call is made.

---

## The decision that took the most thought: "live tool after the branch"

The design docs say "read-only tools re-run live after the branch." But here's
the catch nobody wrote down:

- The **server** can re-run an `llm` span — it has the API keys and knows how to
  call Groq/OpenAI/Anthropic.
- The **server cannot** re-run a *tool* span — that tool is a Python function in
  **your agent's process**, not on the server. The server has no way to call it.

So when the engine hits a tool marked `live` after the branch, what does it do?
We chose **Option A: pass through the stored output**, tagged
`{"replay": "stored_passthrough"}`.

Why A and not "ghost it" or "error"?
- **Honest** — we reused the recorded value and we say so in the metadata.
- **Never blocks** — the branch always completes and produces a diff.
- **Clean seam for the future** — the *real* live re-execution belongs in an
  SDK-side replay mode (runs in your process, can call your tools). Passthrough
  is the correct server-side behaviour until that exists.

> Interview-ready framing: *"Re-executing LLMs is a server concern; re-executing
> tools is a client concern, because tool code lives in the user's process. I
> drew the boundary there and made the server honest about what it can't do."*

This never affects the killer demo: branching at `classify_issue` has only writes
downstream, which become ghosts.

---

## What "deterministic" really means here

Not "the LLM returns the same answer." It means **isolate the variable**. By
freezing everything before the branch, the only thing that changed is your edit —
so any difference in the output is *provably caused by your edit*, not by random
LLM variance on an unrelated step.

The branch point and everything after it still run live, so they can still vary
between two replays. We don't pretend otherwise — we capture `seed` +
`temperature` to minimise it, store both outputs side-by-side, and document it as
best-effort. That's a property of LLMs, not a bug.

---

## Honest limitation worth knowing (and saying in interviews)

When a downstream `llm` is re-run after the branch, it's fed its **stored input**
— which was computed from the *old* upstream output, not your edit. To recompute
the new input we'd have to re-run the agent's glue code, which (again) lives in
the user's process. So downstream LLM re-runs are best-effort. For the demo this
doesn't bite, because the branch point's downstream is all writes (ghosts), not
more LLMs.

---

## How it's built (files)

- [`server/app/routers/replays.py`](../server/app/routers/replays.py):
  - `_effective_policy(span_type, replay_policy)` — the tiny classifier. `tool`
    → honour the annotation (default `dry_run`); everything else → `live`.
  - `_invoke_llm(...)` — shared provider dispatch (Groq/OpenAI/Anthropic),
    returns `(content, prompt_tokens, completion_tokens, provider)`.
  - `_copy_span_dict(...)` — builds a verbatim span copy (used for frozen, branch,
    and passthrough spans, with an optional output override).
  - `_run_branch(...)` — the engine. Walks the sorted spans, applies the 3-bucket
    rule, writes a new trace linked via `branched_from_trace_id`, and records a
    `replays` row for diff metadata.
  - `_finalize_branch_error(...)` — clean error path (e.g. bad `branch_span_id`).

A branch reuses the existing `replays` table for diff metadata — a branch is just
a normal trace with two extra lineage columns. No new tables.

### Why a NEW engine instead of reusing `_run_replay`?

The v1 `_run_replay` re-runs **every** LLM span (whole-trace replay with a prompt
override). The branch engine **freezes** LLM spans before the branch point. Those
are opposite behaviours for the same span type, so they're separate code paths.
They share the low-level helpers (`_call_groq`, `_estimate_cost`, `_detect_provider`).

---

## How it's tested

`server/tests/test_branch.py` — 11 tests:

- **Classifier (6):** every `(type, policy)` combination returns the right
  `live` / `dry_run`.
- **Engine (5):**
  1. freeze-before + override-at + ghost-after, all in one triage-shaped trace
  2. an `llm` after the branch is re-run (Groq mocked)
  3. a `live` tool after the branch is passed through
  4. an unknown `branch_span_id` errors cleanly, produces no spans
  5. an `llm` failure after the branch marks the trace `error`

Engine tests follow the same pattern as the `_run_replay` tests: seed a real
trace into Postgres, patch `SessionLocal` to a test session-maker, mock
`_call_groq` so no real network call happens, then assert on the written rows.

Full suite after this work: **55 passing** (44 existing + 11 new).

---

## Interview Q&A

**Q: What does "deterministic replay" mean if LLMs are non-deterministic?**
It means isolating the variable, not freezing the model. Freeze everything before
the branch point so the only change is the user's edit; then any output
difference is attributable to that edit. Residual variance after the branch is
best-effort (seed + temperature=0) and shown side-by-side rather than hidden.

**Q: How do you avoid duplicate side effects during replay?**
Default-safe. Every span after the branch is classified; writes default to
`dry_run`, which emits a ghost span (`would_have`) instead of executing. A tool
opts into live execution explicitly via an SDK annotation. An unannotated agent
is safe to replay by default — you can never accidentally double-charge a card.

**Q: Why can the server re-run LLM calls but not tools?**
LLM calls are stateless HTTP to a provider the server can reach with its own
keys. Tool code lives in the user's process. So I split the responsibility: the
server re-runs LLMs and passes through / ghosts tools; true live tool
re-execution belongs to a future SDK-side replay mode.

**Q: Why reuse the `traces`/`replays` tables instead of new ones?**
A branch is structurally identical to a trace — same schema, same query paths,
same detail page. Two lineage columns (`branched_from_trace_id`,
`branched_from_span_id`) capture the relationship; the `replays` table already
holds diff metadata. Treating branches uniformly means the existing UI works for
them for free, and branching a branch needs zero special handling.

**Q: How does this scale?**
Today it runs in a FastAPI BackgroundTask — fine for one developer. At real
concurrency I'd move replay execution to a queue + workers (Celery/Redis or
similar), because a replay is a slow, retryable job that shouldn't tie up a web
worker.

---

## Phase 5 — the branch endpoint (the door to the engine)

`POST /v1/traces/{trace_id}/branch` (in
[`server/app/routers/traces.py`](../server/app/routers/traces.py)) takes
`{span_id, new_output}` and does four things:

1. Validate the original trace exists + belongs to the caller's project (404 else).
2. Validate the branch span belongs to that trace (404 else).
3. Create a placeholder trace (`status="running"`), linked to the original via
   `branched_from_trace_id` + `branched_from_span_id`, and a `replays` row holding
   the edit in `modifications`.
4. Schedule `_run_branch` as a `BackgroundTask` and return `{replay_id,
   new_trace_id}` immediately.

The dashboard polls `GET /v1/traces/{new_trace_id}` (existing endpoint) until the
status flips `running → success`/`error`, and reads diff metadata from
`GET /v1/replays/{replay_id}` — no new GET needed, because a branch *is* a trace
and *reuses* the replays table.

**Why BackgroundTasks (and the scale answer):** a branch is a slow, retryable job
(it makes live LLM calls). For one developer, FastAPI's in-process BackgroundTask
is enough. At real concurrency I'd move it to a queue + workers (Celery/Redis) so
slow replays don't tie up web workers — same migration path documented for v1
replay.

**Testing note:** API-layer tests mock `_run_branch` (the engine is tested
separately) — this also prevents the real BackgroundTask from leaking a pooled
connection into the next test's event loop (see note 23). 4 endpoint tests:
success (placeholder + replay row + task scheduled), trace-not-found,
span-not-in-trace, and auth-required. Full suite: **59 passing**.

---

## Status

Engine (Phase 4) ✅ and endpoint (Phase 5) ✅ — both done and tested. Next:
Phase 6 — the dashboard "Branch from here" UI (per-span button → output editor →
Continue → poll the new trace), then Phase 7 — the branched-vs-original diff view.

### Follow-up noted during this work
`replay_policy` currently lives only on the ORM model — it isn't in `SpanIn` or
the SDK yet, so every ingested span gets the DB default (`dry_run`). The engine
already honours the column; threading it through ingestion + an SDK annotation
API is a small follow-up that makes the `live`-tool path reachable end-to-end.

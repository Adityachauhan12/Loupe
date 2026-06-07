# Loupe v2 — The Agent Debugger: Master Checklist

> **Framing (read this first, every time):** v2 is not "observability with replay." It is a
> **debugger for non-deterministic agents** — record-and-replay (like `rr` / time-travel
> debugging) for LLM agents. The observability layer (traces/spans) is the *recording
> substrate*; the product is the *reproduce → branch → fix* loop on top of it.
>
> **The problem we're solving:** "An agent failed in production. I can't reproduce the
> failure to understand it, because the run was non-deterministic and the world moved on."
>
> **Hard rule:** Do not build the replay engine until Phase 0 proves the pain is real.
> Validate, then build.

---

## Track A — Planning & Validation (do this FIRST)

### Phase 0: Prove the problem is real
- [ ] **0.1 — Pick the first real failing agent.** Not CineRater (too clean, self-authored).
      Choose a domain (web-research / GitHub-triage / data-analysis) and scope a small agent
      that calls *live, side-effecting tools* and fails non-deterministically.
- [ ] **0.2 — Build that agent and instrument it with Loupe.** Let it break on its own — do
      not script the failures.
- [ ] **0.3 — Debug a real failure with Loupe as-is.** Try to answer "why did it fail + what
      fix works" WITHOUT re-running the whole thing live. Hit the wall. **Write down exactly
      what you wished you could do** → this becomes the v2 spec.
- [ ] **0.4 — Talk to 5 agent builders.** Question: *"Last time your agent failed in prod,
      what did you actually do to debug it, and how long did it take?"* Log answers verbatim.
      Look for "I couldn't reproduce it" appearing unprompted.
- [ ] **0.5 — Go/No-Go decision.** If the pain is real (yours + theirs), proceed to Track B.
      If not, stop and re-scope. Record the decision and reasoning.

### Phase 0.5: Lightweight market / positioning notes
- [ ] Document how this differs from Langfuse (observability), Promptfoo (input→output CI),
      Braintrust (evals). One paragraph each — sharpen the "debugger, not dashboard" wedge.
- [ ] Write the one-line pitch and the killer demo script before building (demo-driven dev).

---

## Track B — Engineering Build

### Phase 1: Capture completeness audit (foundation — replay is impossible without this)
- [ ] **1.1 — Audit span capture.** For a real trace, verify we store enough to deterministically
      reproduce each span:
  - [ ] LLM spans: exact messages, model, temperature, top_p, **seed**, tools/functions schema,
        stop sequences, full raw request + full raw response.
  - [ ] Tool spans: exact input args (serialized), exact output, and whether the call is a
        read or a write (side-effect flag — see Phase 2).
  - [ ] Timing, ordering, and parent/child relationships are unambiguous.
- [ ] **1.2 — Identify capture gaps** and list the SDK changes needed to close them.
- [ ] **1.3 — Content-addressed storage decision.** Decide whether large span I/O is stored
      inline (JSONB) or hashed/deduped. Document the tradeoff.
- [ ] **1.4 — SDK changes** to capture any missing fields. Bump SDK version, add tests.

### Phase 2: Design docs (write BEFORE coding — this is the senior-engineer rigor)
- [ ] **2.1 — Side-effect classification design doc.** For each span at replay time, how do we
      decide: **replay stored output** vs **execute live** vs **mock/block**?
  - [ ] Define read vs write vs idempotent-write taxonomy.
  - [ ] Default-safe policy (when unsure, block the side effect — never double-`book_flight`).
  - [ ] How the user/SDK annotates a tool as safe-to-replay or must-block.
- [ ] **2.2 — Deterministic replay design doc.** Define exactly what "deterministic" means
      here: replay stored outputs up to the branch point, execute live at/after it. Document
      LLM non-determinism handling (seed, temperature=0, or "this is best-effort and why").
- [ ] **2.3 — Branch tree model.** How branches relate to originals; can you branch a branch;
      how the lineage is represented and queried.

### Phase 3: Database migrations (Alembic — never skip)
- [ ] **3.1 — Migration:** add `branched_from_span_id UUID REFERENCES spans(id)` to `traces`.
- [ ] **3.2 — Add any columns** from Phase 1/2 (e.g. `is_side_effect`, `side_effect_policy`,
      content-hash columns) to `spans`.
- [ ] **3.3 — Indexes** for branch lineage queries (`branched_from_span_id`).
- [ ] **3.4 — Downgrade paths** tested. Run migration up + down locally against Postgres.

### Phase 4: Replay engine (server — the heart)
- [ ] **4.1 — Replay executor service.** Given (trace, branch_span_id, override_output), walk
      the span tree: for spans before branch point → return stored output; at/after → execute
      live, honoring the side-effect policy from Phase 2.
- [ ] **4.2 — Override injection.** Apply the user's edited span output as the branch point's
      output and resume downstream.
- [ ] **4.3 — Side-effect guard.** Enforce mock/block for unsafe writes during replay.
- [ ] **4.4 — Write the replayed run as a new trace** (linked via `branched_from_span_id`),
      reuse existing trace schema/query paths.
- [ ] **4.5 — Run via FastAPI BackgroundTasks** (document the Celery+Redis migration path for
      scale — interview talking point).
- [ ] **4.6 — Idempotency** on branch creation (client-generated IDs, safe re-delivery).

### Phase 5: Branch API endpoint
- [ ] **5.1 — `POST /v1/traces/{trace_id}/branch`** taking `{span_id, new_output}`.
- [ ] **5.2 — Pydantic request/response schemas** (schemas.py), type hints throughout.
- [ ] **5.3 — API key auth** consistent with existing endpoints.
- [ ] **5.4 — `GET`** for branch result / status (polling, no websockets).
- [ ] **5.5 — Structured logging** (structlog) around replay lifecycle + Sentry on failures.

### Phase 6: Dashboard UI
- [ ] **6.1 — Per-span "Branch from here"** button on trace detail.
- [ ] **6.2 — Span output editor:** textarea for LLM responses, JSON editor for tool results.
- [ ] **6.3 — "Continue" action** → calls branch endpoint → poll for new trace.
- [ ] **6.4 — Loading/error states**, optimistic UX where sensible.

### Phase 7: Diff view (branched vs original)
- [ ] **7.1 — Side-by-side diff** comparing branched vs original *from the branch point onward*.
- [ ] **7.2 — Surface deltas:** output difference, token delta, latency delta, status change.
- [ ] **7.3 — Link from trace detail → branch → diff** as one coherent flow.

---

## Track C — Infra / CI-CD / Production Rigor (cross-cutting)

- [ ] **C.1 — Tests:** unit tests for replay executor (the determinism logic is the highest-risk
      code — test it hardest), side-effect classification, branch endpoint. Integration test:
      full branch flow against a seeded trace.
- [ ] **C.2 — CI:** extend GitHub Actions to run new server tests + SDK tests + dashboard build
      on every PR. Keep it green.
- [ ] **C.3 — Migrations in CI:** verify Alembic up/down runs cleanly in the pipeline.
- [ ] **C.4 — Observability of the tool itself:** Sentry spans around replay execution;
      structured logs for every branch run with trace IDs for correlation.
- [ ] **C.5 — Deploy:** ship the new endpoints to Render; new dashboard pages to Vercel; verify
      against Neon. Smoke-test the live branch flow.
- [ ] **C.6 — Performance note:** document replay cost/latency characteristics; where it would
      bottleneck at scale and the fix (queue + workers).

---

## Track D — Demo & Docs (the payoff)

- [ ] **D.1 — Killer demo:** agent failed because it called the wrong tool → click bad span →
      paste correct output → Continue → new trace succeeds → side-by-side shows what *should*
      have happened. Record it.
- [ ] **D.2 — README section** for the debugger: problem statement, the record-and-replay
      analogy, the side-effect design decision, demo GIF.
- [ ] **D.3 — Design-decision writeups** (for interviews): deterministic replay, side-effect
      classification, BackgroundTasks→Celery path, content-addressed storage.
- [ ] **D.4 — Update [project_loupe_status](memory) and CLAUDE.md build status.**

---

## Sequencing rule of thumb
**0 → 1 → 2 → 3 → 4 → 5 → 6 → 7**, with Track C woven into each engineering phase and Track D
at the end. Never jump ahead of a completed capture audit (Phase 1) or a written design doc
(Phase 2) — those are the cheap insurance against expensive rework.

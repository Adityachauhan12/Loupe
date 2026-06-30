# Design: Deterministic Replay

## The tension

LLMs are non-deterministic. The same prompt can return a different answer each
call. So what does "replay" even mean when re-running an LLM span might not
reproduce the original result?

If replay re-runs every LLM call freely, you get noise: a prompt fix might fix
one issue while a different, unrelated issue flips its answer due to randomness.
You can't tell whether your change helped or whether you got lucky.

## What "deterministic" means here

Not "the LLM always returns the same output." It means:

> **Isolate exactly what changed, so cause and effect can be reasoned about.**

We achieve this by freezing everything that is not downstream of the branch
point, and only re-executing what the user actually changed.

## The rule

```
Spans BEFORE the branch point   →  use stored output (frozen, never re-run)
The branch point span           →  re-run with the user's edited input/output
Spans AFTER the branch point    →  re-run live (honouring side-effect policy)
```

The freeze of everything before the branch point is the whole game. It removes
all variance that has nothing to do with the change being tested.

## Example — triage agent

Original run:
```
classify_issue("App crashes")        → "bug"       ✅
classify_issue("Add dark mode")      → "feature"   ✅
classify_issue("Reset password")     → "bug"       ❌ should be "question"
```

User branches at the third `classify_issue` and edits the system prompt.

Naive (re-run everything) — WRONG approach:
```
classify_issue("App crashes")        → "feature"   ❌ now broken by randomness
classify_issue("Add dark mode")      → "feature"   ✅
classify_issue("Reset password")     → "question"  ✅ fixed
```
You can't tell if the fix worked — issue #1 changed for unrelated reasons.

Deterministic replay — CORRECT approach:
```
classify_issue("App crashes")        → "bug"       (frozen — stored output)
classify_issue("Add dark mode")      → "feature"   (frozen — stored output)
classify_issue("Reset password")     → "question"  (re-run — this is the branch)
```
Only the changed call re-runs. The fix is provably the cause of the change.

## Residual non-determinism (and how we handle it)

The branch-point span and anything after it still run live, so they can vary
between two replays of the same edit. We do not pretend otherwise. Mitigations:

1. **Capture `seed` and `temperature`** (done in Phase 1). Replaying with the
   same seed + `temperature=0` minimises variance.
2. **Store both original and replay outputs** so the diff view shows them
   side by side — the developer compares directly rather than trusting a single
   run.
3. **Document it honestly:** replay at/after the branch point is best-effort.
   This is a property of LLMs, not a bug in the engine.

## Why this is the right tradeoff

- Full determinism (freeze the LLM output too) would make replay useless — you'd
  never see the effect of your prompt change.
- Full live re-execution drowns the signal in noise.
- Freeze-before, live-after gives a clean experiment: one independent variable
  (the edit), everything else held constant.

This is the same principle as a controlled experiment — change one thing, hold
the rest fixed, observe the effect.

## The replay boundary — what's captured vs best-effort (decision B6)

Replay re-runs the agent from the original's **captured** inputs and freezes spans
before the branch point. It is faithful **only for state that was captured**.
Anything a span reads that we did *not* instrument is best-effort and can cause
divergence unrelated to the edit:

- wall-clock time (`datetime.now()`), randomness / RNG without a fixed seed
- a live DB / API read that returns something different at replay time
- environment variables, files, or other process/host state

This is a fundamental property of non-deterministic agents, **not** a bug in the
engine. We are explicit about it rather than pretending otherwise:

- **Captured & frozen** (faithful): span inputs/outputs recorded in the original
  trace; LLM `seed` + `temperature` (Phase 1).
- **Best-effort** (may vary): un-instrumented external reads as listed above.

Mitigation if you need more fidelity: freeze the *output* of an un-replayable read
(treat it like a frozen span) so downstream sees a stable value. That's opt-in
future polish — the default contract is **capture-and-freeze**, documented here and
in the README's "What replay guarantees" section.

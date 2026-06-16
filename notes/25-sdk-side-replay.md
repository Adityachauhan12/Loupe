# 25 — SDK-side Replay (making the edit actually propagate)

> This note is the answer to a bug we hit live: you branch a trace, edit a
> middle step, and… the final answer doesn't change. This fixes that.

---

## The problem (in one breath)

The **server-side** branch engine ([note 24](24-branch-replay-engine.md)) can re-run
LLM calls (it has the API keys) but **cannot run your tool functions** —
`search_movies` lives in *your* program, not on the server. So when you branched
cinerater's "parse" LLM to `Romance`, the server couldn't re-run the search; it
showed a ghost with the *old* input, and the downstream LLM got the *old*
shortlist (Sinners). **Your edit never propagated.**

Recipe analogy: you swapped the first ingredient, but the cook kept serving the
pre-made dish — because the kitchen (your functions) isn't on the server.

## The fix

Run the replay **inside the user's own process**, where the real tools exist.
That's `loupe.replay(...)`. Same three-bucket rule as the server, but now
"after the branch → live" means *your actual code runs*:

```
before branch  → freeze  (return the stored output, skip execution)
at branch       → edit    (return your edited output)
after branch     → LIVE    (run the real tool / LLM)
```

Now: edit parse → `Romance` ⇒ `search_movies(Romance)` **really runs** ⇒ new
shortlist (Past Lives) ⇒ write-LLM runs on it ⇒ **different answer**. Proven live.

## How it works — one chokepoint

Every span — LLM or tool — flows through `loupe.span()`. That's the single place
we intercept. A `_ReplayPlan` (in [`sdk/loupe/_replay.py`](../sdk/loupe/_replay.py))
holds the original spans' outputs, the branch index, and a **cursor**. As each
span starts, `begin_span()` classifies it by cursor position → `freeze` / `edit`
/ `live`, and pushes the decision so the provider integration can read it.

- **LLM call** ([groq integration](../sdk/loupe/integrations/groq.py)): before
  hitting the API it checks `current_frozen_output()`. If frozen/edited, it
  **synthesizes a response** from the stored/edited content and skips the real
  call. If live, it calls the API for real.
- **Tool span**:
  - `@loupe.span` **decorator** → we can skip the body entirely (return the
    stored output). Safe for side-effecting tools.
  - `with loupe.span()` **context manager** → the body *can't* be skipped (Python
    has no way to no-op a `with` block), so before-branch it runs but we **pin the
    recorded output** to the stored value. ⚠️ This means a side-effecting tool
    using the context-manager form would re-fire before the branch — so
    **decorate side-effecting tools** if you need them frozen.

`loupe.replay(agent_fn, trace_id=, branch_span_id=, new_output=)`:
1. fetches the original trace (`client.fetch_trace`),
2. builds the plan (branch index from the chosen span, stored outputs in order),
3. re-invokes `agent_fn(*original_args)` under the plan,
4. the `@trace` wrapper records the re-run as a **new branched trace**
   (`is_replay=True`, `branched_from_trace_id/span_id`) and enqueues it,
5. returns the new trace id.

## Server vs SDK replay — when to use which

| | Server-side branch | SDK-side replay |
|---|---|---|
| Runs where | Loupe server (BackgroundTask) | your agent process |
| Re-runs LLMs | ✅ | ✅ |
| Re-runs your tools | ❌ (ghost) | ✅ (live) |
| Edit propagates downstream | ❌ | ✅ |
| Triggered from | dashboard button | `loupe.replay()` / CLI |
| Best for | "preview + safely skip writes" | true counterfactual ("what *would* have happened") |

They're complementary: the dashboard branch is a safe one-click preview; SDK
replay is the real time-travel debug when you want the whole chain recomputed.

## What we changed

- `sdk/loupe/_replay.py` — the plan + cursor + freeze/edit/live decision.
- `sdk/loupe/core.py` — `span()` and the `@trace` wrapper consult the plan;
  public `loupe.replay()`; branched-trace markers.
- `sdk/loupe/integrations/groq.py` — short-circuit the API call when frozen/edited.
- `sdk/loupe/client.py` — `fetch_trace()` (GET) to load the original.
- `sdk/loupe/models.py` + server `schemas.py`/`traces.py` — carry & persist
  `branched_from_trace_id` / `branched_from_span_id` through ingestion.

**Tests:** `sdk/tests/test_replay.py` — 8 tests: the cursor decision, and two
full-flow runs (branch at first LLM → downstream runs live & propagates; branch at
last LLM → everything before is frozen, no live API calls). SDK suite 27,
server suite 61.

## Interview Q&A

**Q: Why can't the server just replay everything?**
Tool code lives in the user's process; the server only has the recorded trace and
the LLM API keys. Re-running an LLM is a server concern; re-running a tool is a
client concern. So true propagation has to happen in-process — that's SDK-side
replay. The server-side branch is the safe preview that never touches the real
world.

**Q: How do you intercept without changing the agent's code?**
Everything already funnels through `loupe.span()` and the instrumented client.
I added a replay context (a ContextVar plan + cursor) that those existing
chokepoints consult — zero changes to the user's agent.

**Q: What's the limitation you can't fully solve?**
A `with loupe.span()` context manager can't have its body skipped, so a
side-effecting tool in that form would re-fire before the branch. The honest fix
is to tell users to use the `@loupe.span` decorator for side-effecting tools (it
can be skipped). Documented, not hidden.

---

## Status

SDK-side replay ✅ working and proven live on cinerater. Open follow-ups:
- A `loupe replay` **CLI** wrapper (v2.3) so it's one command, no script.
- Dashboard can't trigger this directly (it's in-process) — it would hand the user
  a copy-paste `loupe.replay(...)` snippet, or this stays a CLI/programmatic flow.

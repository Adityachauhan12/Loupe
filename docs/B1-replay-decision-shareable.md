# Loupe — The "Two Kinds of Replay" Problem & Decision (Shareable Brief)

> A self-contained write-up for someone who is **not** deep in the codebase.
> It explains the problem we hit, why it exists, the options we weighed, and the
> decision we locked. No prior context needed.
>
> Date decided: **2026-06-26** · Decision ID: **B1** · Status: **RESOLVED → Option (1)**

---

## 30-second version

Loupe is an observability + **replay** tool for LLM agents. "Replay" = take a past agent
run (a "trace") and re-run it with a change (different prompt, model, or an edited step)
to see what *would* have happened.

We accidentally built **two different replay engines** that look the same to a user but
behave differently. We had never formally decided which one is "the product." We just did.

**Decision: the SDK-side replay is the real product. The dashboard's server-side button
stays, but is relabeled as a limited "preview." Both kept, clearly labeled.**

---

## Background: what is a "replay" supposed to do?

An agent run is a chain of steps ("spans"): the LLM thinks, calls a tool like
`search_movies("Inception")`, gets a result, the LLM thinks again, answers.

A **good replay** lets you change one step and see the *real* downstream consequence —
e.g. "the agent called the wrong tool; let me fix that call and prove it now succeeds."
This is the product's headline feature ("time-travel debugging").

---

## The problem: we have two engines, and they're not equal

| | **Server-side branch** | **SDK-side replay** |
|---|---|---|
| Triggered by | Dashboard "⑂ Branch from here" button | `loupe.replay()` / `loupe replay` CLI |
| Where it runs | Loupe's server (cloud, on Render) | The user's own app process (their laptop / their service) |
| Can it re-run the user's tool functions? | **No** | **Yes** |
| Does an edit truly propagate downstream? | **No** — downstream still sees the old data | **Yes** — real new results flow through |
| Re-runs the LLM call? | Yes | Yes |

### Why the difference exists (the one fact that explains everything)

To actually run a tool like `search_movies()` with **new arguments**, *some process must
already have the user's Python code loaded in memory.*

- The **Loupe server** is Loupe's own generic code. It does **not** contain any user's
  `search_movies()` function. So it physically **cannot** run it. The best it can do is
  re-call the LLM and reuse the *old stored* tool result (a "ghost"). → limited.
- The **SDK** is a library that runs **inside the user's app**, right next to their tool
  code. So it **can** run `search_movies()` for real with the edited input. → true replay.

This is not a bug or a missing feature. It's a hard boundary: **a server can't execute
code it doesn't have.**

---

## The key mental model: control plane vs execution plane

People get confused because they think "server vs SDK = cloud vs laptop." It's not.
There are **two independent questions**:

1. **Where does it run?** — laptop or cloud (location)
2. **Whose code is it, and what job does it do?** — (ownership / role)

"Server vs SDK" is about **#2**, not #1. A *deployed* SDK is still the SDK.

| Process | Whose code | Role |
|---|---|---|
| Loupe **server** | Loupe's | **Control plane** — stores traces, serves dashboard, routes/queues jobs. Owns no user code or secrets. |
| User's **app + Loupe SDK** | The **user's** | **Execution plane** — runs the real tools, holds the user's DB creds + API keys. |

**They can never merge — because of trust, not distance.** Putting the user's tool code on
Loupe's server would mean uploading their proprietary code and production secrets onto
Loupe's box. Nobody does that.

Same pattern as well-known systems:
- **GitHub** (control plane) vs a **self-hosted Actions runner** (your machine, your code).
- **Temporal server** (queue) vs **Temporal workers** (your code).

> **One-liner:** Server = the post office (routes messages, owns no packages).
> SDK = your house (your stuff, does the actual work). Putting your house in the cloud
> doesn't make it the post office.

---

## "Can't we get true replay on a deployed/hosted setup too?"

Yes — via a **worker**, and importantly it does **not** require deploying the app twice.
You add one flag to the app the user *already* runs:

```python
loupe.init(api_key=..., worker=True)   # starts a background thread that dials OUT to Loupe and waits for jobs
```

Now the user's existing app also listens for "branch" jobs. When someone clicks ⑂ in the
dashboard, the Loupe server just **queues** the job; the user's worker (which has the code)
**runs it for real** and sends the result back. This is exactly how Sentry / Datadog /
OpenTelemetry agents work — in-process, outbound connection, no open ports.

**The real catch is safety, not deployment:** a worker inside *production* would re-run
*real* tools — fine for read-only `search_movies()`, dangerous for `charge_card()`.
Mitigations: run the worker in **staging**, and/or mark tools `replay_safe=False` so they
return a stored ghost instead of firing on replay.

**Why we did NOT build the worker now:** Loupe's headline demo is *a developer debugging a
failed trace*. The developer already has the code on their laptop, so `loupe replay`
locally is the natural zero-setup path. The worker only matters for a narrower future case
(a non-developer clicking "branch" against a live system). So it's scoped and **deferred**.

---

## The options we weighed

1. **SDK-side is the product; server-side is a labeled "preview."** Keep both. Label the
   dashboard button "Quick preview (LLM-only, tools not re-run)" and position
   `loupe.replay`/CLI as the headline "true branch."
2. **Drop server-side entirely.** Branching is SDK-only; the dashboard button just copies
   the `loupe replay` command. Cleanest mental model, but loses the zero-setup one-click
   demo.
3. **Unify them** — build the worker so the dashboard button also runs real tools. Real
   product work, little payoff for a portfolio project right now.

---

## ✅ The decision: Option (1)

**SDK-side replay is the canonical product (the "true branch"). Server-side branch stays
but is honestly relabeled as a "preview (LLM-only, tools not re-run)." Both kept; the
hierarchy is made explicit in the UI (button text + a caveat on the diff view).**

**Why:** it preserves *both* demos — the slick one-click dashboard preview *and* the deep,
real `loupe replay` debugging flow — and it turns the server-side limitation from a
confusing inconsistency into an honestly-labeled feature. Option (3) (the worker) is the
documented "real production" path, deliberately deferred.

**What this unlocks (follow-on decisions):**
- Accept the small amount of duplicated provider-call code between server and SDK (it only
  exists because of the server-side path; now bounded and fine).
- Add an explicit `replay_mode` field to a trace so the dashboard *knows* (instead of
  guessing) whether a branch was server-side or SDK-side, and labels it correctly.

**Remaining small code work from this decision:** relabel the dashboard ⑂ button, and make
the server-vs-SDK distinction explicit in the diff view caveat. (Not yet done.)

---

## Talking point (interview-ready)

> "Server-side branch is LLM-only *by design*, because the server is the control plane and
> can't execute user tool code — that's a trust boundary, not a missing feature. True
> counterfactual replays run in the execution plane (the SDK): locally for debugging, or
> as an embedded outbound worker for hosted use, like a self-hosted CI runner. I scoped
> the worker and deferred it because the debugging demo doesn't need it."

---

*Source of truth for all Loupe decisions: [`ARCHITECTURE_DECISIONS.md`](../ARCHITECTURE_DECISIONS.md)
(see item **B1** and the "B1 explainer — control plane vs execution plane" subsection).*

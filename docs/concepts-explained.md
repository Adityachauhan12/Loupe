# Loupe — Concepts Explained (Layman Terms)

> A plain-language walkthrough of the ideas behind Loupe: how data is captured,
> how it's stored in a standard shape, how replay/experimentation works, the
> security implications, and the v2.2 "Prompt CI/CD" design. Written for learning
> and interview prep — every section ends with a one-line interview answer.
>
> Companion to [ARCHITECTURE_DECISIONS.md](../ARCHITECTURE_DECISIONS.md) (the "why"
> for each locked decision) and [CLAUDE.md](../CLAUDE.md) (the full spec).

---

## Table of contents

1. [What v2.2 is and why "Prompt CI/CD"](#1-what-v22-is-and-why-prompt-cicd)
2. [v2.2 design decisions (B8.1–B8.4)](#2-v22-design-decisions-b81b84)
3. [Why the suite run is async (not synchronous, and not a cron)](#3-why-the-suite-run-is-async)
4. [How logs are actually captured (in-process, not fetched)](#4-how-logs-are-actually-captured)
5. [The two-layer data model: standard envelope + flexible payload](#5-the-two-layer-data-model)
6. [No parsing — shape-agnostic serialization (`_to_jsonable`)](#6-no-parsing--shape-agnostic-serialization)
7. [Security: do we capture passwords? (yes — and it's a real gap)](#7-security-do-we-capture-passwords)
8. [Observability vs Replay/Experimentation](#8-observability-vs-replayexperimentation)
9. [How Loupe compares to LangSmith / Helicone](#9-how-loupe-compares-to-langsmith--helicone)

---

## 1. What v2.2 is and why "Prompt CI/CD"

### The problem: a prompt is a silent landmine

Inside an LLM agent, before calling the model, there's an **instruction string** — the
prompt. It's just a string, but it's effectively the app's brain. Change one word and
the whole behaviour changes.

The danger: a prompt has **no safety net**.

- Break normal code → the test fails, CI goes red, the merge is blocked.
- Break a prompt → no compiler error, no failing test (nobody wrote a test for a
  string), the app keeps "running" — it just gives **wrong answers**, silently.

**Example.** You "improve" a genre-extraction prompt:

```diff
- Extract the genre as JSON: {"genre": "..."}.
+ Figure out what kind of movie the user is in the mood for and tell me.
```

Now the LLM returns *"Sounds like you're in the mood for something sci-fi!"* instead of
`{"genre": "Sci-Fi"}`. Downstream code that does `json.loads(output)["genre"]` **crashes**
— and you won't know until a user complains. One reworded sentence, no alarm.

### The fix: give prompts the same green/red safety net code has

**"CI/CD" for prompts** = when a PR changes a prompt, a robot automatically checks it and
reports pass/fail, blocking bad merges. But you can't test prompt output with exact match
(LLMs are non-deterministic). So the test is:

> **Re-run all your past real cases with the new prompt, and check whether answers got
> better or broke.**

### The full flow (CineRater example)

1. **Setup (once):** take ~100 real production traces (past user queries + what the agent
   answered) and mark them a **golden suite** — your "exam paper" of 100 questions you know
   the right answers to.
2. Someone edits the prompt and opens a **GitHub PR**.
3. A **GitHub Action** wakes up, sees a prompt file changed, and tells Loupe: *"run my
   golden suite against this new prompt."*
4. Loupe **replays** each trace with the new prompt (the replay engine already exists from
   v2.1).
5. A **judge LLM** compares old vs new output per trace → `equivalent` / `improved` /
   `regressed`.
6. The Action posts a **PR comment**: *"93/100 passed · 5 improved · 2 regressed ❌"* and a
   **red status check** blocks the merge.
7. Click "View diffs" → land in the Loupe dashboard with the broken traces side-by-side →
   fix the prompt → push → green ✅.

**Why this matters (portfolio angle):** LangFuse/LangSmith/Helicone are *observe* tools.
Loupe closes a **loop**: production trace → save as test → run on every PR → block bad
merges. That's systems thinking, not "I built a dashboard." And it's only possible because
Loupe built a **replay engine from day one** (v2.1).

> **Interview line:** *Prompts are code, but they fail silently and non-deterministically —
> Loupe turns saved production traces into a regression suite so a prompt PR gets the same
> green/red safety net real code gets.*

---

## 2. v2.2 design decisions (B8.1–B8.4)

Four architectural questions, each laid out as tension → options → decision.

### B8.1 — How to store a suite? ✅ (A) reference, join table

A "golden suite" is a *collection* of traces. Two ways to store it:

- **(A) By reference** — store only trace **IDs**; the trace data stays in the `traces`
  table where it already lives. Analogy: a **playlist stores song names (pointers)**, not
  full MP3 copies.
- **(B) By copy** — snapshot each trace's full data into the suite.

**Decision: (A), via a `suite_traces` join table.** Traces are **immutable** in Loupe (once
ingested, nobody updates them), so copying buys nothing — the "freeze a snapshot" benefit
of (B) doesn't apply. Matches decision **A4** ("replays live in the traces table" — single
source of truth). A join table keeps membership queryable both ways with FK integrity.

```
suites:        id, name, project_id, judge_rubric?, created_at
suite_traces:  suite_id → suites.id,  trace_id → traces.id 
    (composite PK)
```

> **Interview line:** *Traces are immutable, so a suite is just a named set of references —
> no need to duplicate payloads; a join table keeps membership queryable both ways.*

### B8.2 — Shape of a suite run? ✅ (A) JSONB `results`

A "run" (one execution of a suite against a new prompt) needs two kinds of data:

1. **Summary** — pass/fail/regress counts, which prompt (for the PR comment).
2. **Per-trace detail** — verdict, reasoning, and the replay's `new_trace_id` (so the
   dashboard can open the existing diff view).

Analogy: an **exam result-sheet** — total marks on top (summary), per-question breakdown
below (per-trace).

**Recommendation: (A) one `suite_runs` row with per-trace results in a JSONB column.** We
always read a run *as a whole* (PR comment, one detail page) — never cross-run analytics —
so a normalized child table buys nothing yet. Same call as keeping span payloads in JSONB
(**A1**). Revisit if real cross-run analytics ever appears.

```
suite_runs:
  id, suite_id, status ('running'|'done'|'error'),
  prompt_override, model_override?,
  total, passed, regressed, improved, errored,
  results JSONB,      -- [{trace_id, new_trace_id, verdict, score_source,
                      --   reasoning, confidence, deterministic_checks}, ...]
  started_at, ended_at, created_at
```

### B8.3 — Judge rubric: global or per-suite? ✅ (A) global default + override

A **rubric** = gradeable criteria for the judge (not "vibes"): e.g. *"Did the new output
preserve the intended genre? Is it still valid for downstream code? Did it lose info the
original had?"*

**Recommendation: (A) a global default rubric + optional per-suite override
(`suites.judge_rubric TEXT NULL`).** A suite works with zero config (default), but a
JSON-extraction suite can supply its own stricter criteria. Bonus: the shared default
**prompt-caches** across judgments (~90% cheaper reads).

### B8.4 — Scoring: agentic, or framework + regex? ✅ hybrid, single-call judge, Sonnet default

Should the scorer be an **agent** (multi-step, tool-using) or a **simple Claude call +
regex**?

- **Agentic judge → no.** Comparing two short outputs is a **classification** task, not an
  agent task. An agent adds latency, cost, and failure modes for ~zero accuracy gain. (Also
  an over-engineering red flag in interviews.)
- **Regex/deterministic → yes, but only for structured spans.** Free (no LLM call). Perfect
  for `{"genre": "Sci-Fi"}` → `assert genre == expected`. Can't judge the *meaning* of
  free text.
- **Claude judge → yes, but only for the free-text final answer.** A single
  `messages.parse()` call with a rubric → structured `{label, reasoning, confidence}`.

**Decision: a hybrid.** Cheap deterministic checks on structured spans first; a single
Claude judge call only on the free-text answer, driven by a rubric.

**Judge backend is pluggable.** Default for development is a **free Groq/Llama** backend
(keeps the loop $0 to build and self-host, reuses the SDK's Groq integration); **Claude
Sonnet 4.6** is an opt-in upgrade for the demo / production, chosen per suite or run. The cost
tradeoffs and the free-tier token-budget caveat are covered in
[ARCHITECTURE_DECISIONS.md](../ARCHITECTURE_DECISIONS.md) → B8.4.

> **Interview line:** *Exact-match breaks on non-determinism; embeddings give similarity not
> direction; an LLM-as-judge with a rubric + structured output gives a semantic, directional
> verdict — and it's a single classification call, not an agent. Deterministic checks on
> structured spans run first for free; Batch + prompt-caching keep a 100-trace run under a
> dollar.*

---

## 3. Why the suite run is async

**Common misconception:** "if we check the prompt the moment it's sent, what's the point of
a scheduler job?"

Two things to separate:

**There is no cron/scheduler.** The run is **event-driven** — the GitHub Action fires it
**once** when the PR opens/updates. No background polling loop on a timer. So yes — the
check happens *then and there*, when the prompt arrives.

**But the execution is async (background), not synchronous.** Here's why "then and there"
splits into two options:

- **(A) Synchronous** — do all 100 replays + 100 judge calls *inside the HTTP request*,
  then respond. **Problem:** ~3–5s per trace × 100 = **5–8 minutes**. An HTTP request can't
  stay open that long — the Action, load balancer, and server all **time out** (~30–60s).
  The request dies mid-way.
- **(B) Async** — `POST /suites/{id}/run` returns a `run_id` immediately (`status: running`)
  and hands the work to a **BackgroundTask**. The server grinds through 100 traces in the
  background; the GitHub Action **polls** `GET /suite_runs/{id}` until `status: done`, then
  posts the comment.

Analogy: the laundry (dhobi) doesn't make you stand at the counter for 6 hours — he gives
you a **token** (`run_id`), you leave, and you show the token later to collect. Same work,
doesn't block you.

This is decision **A5** ("BackgroundTasks over Celery/Redis") applied at suite scale.

> **Interview line:** *The run is event-driven — triggered by the PR, not a cron — but
> replaying 100 traces plus judge calls takes minutes, which can't fit in one synchronous
> HTTP request without timing out; so the endpoint kicks off a BackgroundTask and returns a
> run_id, and the Action polls until done.*

---

## 4. How logs are actually captured

**Key misconception to kill:** Loupe does **not** "fetch" logs from a file or an external
system. There is **no log file and no parser.** The SDK sits **inside your running agent
process** and grabs data **in-process, at the moment each call executes**, by intercepting
the call itself.

Analogy: a **CCTV camera** doesn't *request* footage from outside — it's mounted **inside
the room** and records what happens, right there. The SDK is the CCTV inside your agent.

There are three capture points, all inside the user's process:

| # | Where | Mechanism |
|---|---|---|
| 1 | **LLM calls** | `loupe.instrument_groq(client)` **monkey-patches** the provider's `create()` method. Every LLM call now runs through a Loupe wrapper that records input + output + tokens, runs the *real* call, and returns the response as if nothing happened. |
| 2 | **Tool calls** | `with loupe.span("search_movies", type="tool", input=inputs) as s:` — a context manager. On `__enter__` it records input and registers the span in the trace tree; on `__exit__` it records output + duration and pops back up the tree. |
| 3 | **Whole run** | `@loupe.trace(name="cinerater")` — a decorator wrapping the entrypoint function; args → trace input, return → trace output. |

### The LLM interception, step by step

```
agent:  groq_client.chat.completions.create(messages=...)
   → Loupe wrapper sits in the middle:
       1. capture `messages`      → span.input
       2. run the REAL Groq call  (actual LLM)
       3. capture the response    → span.output
       4. read usage.tokens/model → span fields (model, provider, cost)
   → response returned to the agent (transparent)
```

The agent never notices. Loupe **stepped into the gap between "call made" and "response
returned"** and lifted the data out.

### Then it's sent (not written to a log)

Captured spans are **batched in memory** and a **background worker thread** POSTs them to
`POST /v1/traces` via `httpx` — non-blocking so the agent isn't slowed. On process exit, an
`atexit` flush sends anything left.

> **Interview line:** *Loupe doesn't parse text logs — the SDK runs inside the agent process
> and intercepts each LLM/tool call at runtime (monkey-patching provider clients, wrapping
> functions with a decorator/context-manager), lifting input/output/tokens out in-process,
> then batching them to the server on a background thread.*

---

## 5. The two-layer data model

Every project's logs look different (`search_movies` vs `run_sql_query` vs
`vector_search`). Loupe standardizes them with **a standard envelope + a flexible payload.**

Analogy: every log is a **courier parcel**. The **label** (from/to/weight/type) is
**standard** — same for every courier. What's **inside** varies per parcel. Loupe fixes the
label, leaves the contents free.

### Layer 1 — Standard envelope (fixed schema, same for all projects)

Whatever the agent, Loupe reduces everything to **4 things**: a `Trace` (one run) containing
`Span`s (one operation each). Every span has a **fixed shape**:

| Field | Meaning | Standardized? |
|---|---|---|
| `type` | `'llm' \| 'tool' \| 'function' \| 'retrieval'` | ✅ fixed taxonomy (only 4 values) |
| `name` | e.g. `"search_movies"` / `"openai.chat"` | ✅ |
| `started_at` / `duration_ms` / `parent_span_id` | timing + tree | ✅ |
| `model`, `provider`, `*_tokens`, `cost_usd` | LLM spans only | ✅ |
| `input` / `output` / `error` / `metadata` | **anything** | ❌ JSONB (Layer 2) |

`search_movies` and `run_sql_query` become the **same-shaped span**: `type="tool"`,
`name=<func>`, `input=JSONB`, `output=JSONB`. Identical from the outside — which is why the
dashboard's span-tree and diff view work for **every** project unchanged.

### Layer 2 — Flexible payload (JSONB — where per-project variety lives)

`input`/`output`/`error`/`metadata` are **JSONB**. Any shape goes in — `{"genre": ...}`, a
500-row SQL result, nested embeddings. This is decision **A1** ("Postgres + JSONB handles
variable span structure cleanly"). No schema enforced on the payload.

### Who standardizes? The SDK

OpenAI, Anthropic, and Groq return **different response shapes** (`usage.prompt_tokens` vs
`usage.input_tokens`, Anthropic's separate `system` field, etc.). The SDK's `integrations/`
layer **normalizes** each provider's response into the common span fields. That's the
normalization layer — provider chaos in, standard envelope out.

This is essentially **OpenTelemetry's model**: a fixed span envelope with semantic
conventions, plus schema-less attributes.

> **Interview line:** *Loupe follows the OTel model — a standardized span envelope with a
> fixed type taxonomy and normalized LLM fields, plus a schema-less JSONB payload for
> arbitrary tool I/O; the SDK integrations are the normalization layer.*

---

## 6. No parsing — shape-agnostic serialization

**Biggest misconception:** that Loupe "parses logs into key-value pairs." **It doesn't.
There is no parsing step.**

### Parse vs serialize

- **Traditional logging:** the agent writes **text** to a file → a parser reads the text →
  regex/grok **extracts** fields → key-value. This **is** parsing, and it's
  **hardcoded per-format** and fragile. This is the model people fear.
- **Loupe:** the return value is **already a Python object** (a dict / list). Loupe grabs
  the **live object** and **serializes** it to JSON. No text, no regex, no per-format
  knowledge.

> **Parse** = extract structure from unstructured text (per-format).
> **Serialize** = write already-structured data as JSON (generic).
> Loupe only serializes — so there's no "parsing logic" to be hardcoded.

### The one generic function: `_to_jsonable`

```python
def _to_jsonable(obj):
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj                                                # native → as-is
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}  # recurse
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(i) for i in obj]                     # recurse
    return str(obj)                                               # anything else → str()
```

Three layers:
1. **JSON-native** → keep as-is.
2. **Containers** (dict/list/tuple) → **recurse**.
3. **Everything else** (custom class, datetime, numpy, DB row) → **`str()` fallback.**

Notice: **no CineRater-specific code** — no `"genre"`, no field names. Only generic Python
types. It runs **identically** for any project. Zero hardcoding.

### Worked example — a stranger's fintech agent (nothing to do with us)

```python
return {
    "txn_id": "TXN-9981",
    "amount": Decimal("99.50"),          # JSON doesn't know Decimal
    "ts": datetime(2026, 7, 1, 12, 30),  # JSON doesn't know datetime
    "items": [{"sku": "A1", "qty": 2}],
}
```

| Field | Type | `_to_jsonable` result |
|---|---|---|
| `txn_id` | str | `"TXN-9981"` (as-is) |
| `amount` | Decimal | `"99.50"` (**str() fallback**) |
| `ts` | datetime | `"2026-07-01 12:30:00"` (**str() fallback**) |
| `items` | list of dict | `[{"sku": "A1", "qty": 2}]` (**recurse**) |

Valid JSON → JSONB → dashboard. **We changed zero lines and wrote zero config.** Same
function that ran on CineRater ran on fintech.

### The honest tradeoff

The `str()` fallback means rich objects are **lossy** — you see the `repr`, not structured
fields. This is deliberate:

> Loupe guarantees *"capture never crashes your agent, and you'll always see something"* —
> **not** *"perfect structured capture of every object type."*

A user who wants structured capture passes a dict explicitly (as CineRater does with
`input=inputs`).

> **Interview line:** *Capture is schema-less by design — a recursive serializer keeps
> JSON-native types, recurses into containers, and falls back to `str()` for anything else,
> so any agent's output is recorded as valid JSON with zero per-project config. There's no
> parsing, so there's nothing hardcoded to our project. The deliberate tradeoff is that
> exotic objects are stringified rather than failing.*

---

## 7. Security: do we capture passwords?

**Yes — currently, by default, Loupe would capture a password in plaintext.** If a secret
flows through an instrumented tool argument or an LLM prompt, `_to_jsonable` records it like
any other data, straight into JSONB. **That is a real security issue** — and hiding it would
be wrong. (Confirmed: the SDK has **no redaction** today.)

### The important distinction: "logged" vs "merely used"

A secret used *inside* a function is safe; a secret passed *as input* is captured.

```python
# ✅ SAFE — key is used, never part of traced input/output
def search(customer_id):
    api_key = os.getenv("API_KEY")   # stays inside the function
    ...

# ❌ LEAK — key is a tool argument, so it's captured
search(customer_id="123", api_key="sk-live-...")
```

Same for prompts: if a prompt contains an SSN or medical record and prompt-logging is on,
the SSN gets stored.

### This isn't Loupe-specific

Every "capture everything" observability tool (Sentry, Datadog, LangSmith, Helicone) faces
this. The industry-standard defense is **redaction (PII/secret scrubbing).** Loupe just
hasn't built it yet — it was out of MVP scope.

### How to fix it (the plan)

1. **SDK-side redaction, before serialization (the real fix).** So secrets never reach the
   DB:
   - **key-based:** keys like `password`, `token`, `secret`, `api_key`, `authorization`,
     `cookie` → value `"[REDACTED]"`.
   - **value-based:** values that look like keys/JWTs/cards (regex) → mask.
   - **configurable:** `loupe.init(redact_keys=[...])`.
2. **Per-span opt-out:** `@loupe.trace(capture=False)` for auth flows.
3. **Defense in depth server-side:** TLS in transit (done), hashed API keys (done), access
   control, retention policies.
4. **Secure by default:** redaction **on by default** with a sensible denylist, so a new
   user can't leak by accident.

### Why this matters *more* in v2.2

The judge sends traces to **Anthropic** (a third party). A secret in a trace wouldn't just
sit in the DB — it would **leave to an external LLM.** So the fix isn't only "DB safe"; the
JudgeService must send a **redacted payload** to the judge.

> **Interview line:** *Yes — shape-agnostic capture means Loupe would record a password in
> plaintext, a risk shared by every capture-everything tool. The fix is a client-side
> redaction layer before serialization — key-name and value-pattern denylists, on by
> default, user-configurable — so secrets never leave the user's process; plus per-span
> opt-out and server-side defense in depth. It matters doubly in v2.2 because the judge ships
> traces to a third-party LLM.*

*(Tracked as a proposed new item **B11 — PII/secret redaction** in ARCHITECTURE_DECISIONS.md.)*

---

## 8. Observability vs Replay/Experimentation

Two different capabilities:

| Observability | Replay / Experimentation |
|---|---|
| "What happened?" | "What if this had happened instead?" |
| Passive — records traces | Active — re-executes traces |
| LangSmith, Helicone | LangSmith Experiments, Braintrust, Loupe |

### The core insight

You **cannot** answer "what if the tool returned X instead?" from the stored trace alone —
you must **re-run the downstream graph**. And crucially:

> The replay is **not** created automatically from logs. Some **execution engine** must
> resume the workflow from a point in the graph.

This is exactly Loupe's **B1** decision — **control plane vs execution plane:**

- **Loupe server** (observability/control plane) — stores traces, serves the dashboard;
  **cannot** replay (it doesn't hold the user's tool code).
- **Loupe SDK** (`loupe.replay`, execution plane) — runs in the user's process, re-executes
  real tools.

So where LangSmith needs LangGraph as the execution engine for experiments, **Loupe's SDK
*is* that engine.**

### How Loupe replay works (freeze-before / live-after)

Everything before the edited span is **frozen** (replayed from stored output); the edited
span uses the new value; everything at/after it runs **live**. Decision **A8**.

```
Original:  Planner → Search[A,B] → Booking → "Recommend Flight A"
Replay:    Planner(frozen) → Search[C,D](edited) → Booking(live) → "Recommend Flight D"
```

- **Tokens:** frozen spans reuse the original's tokens; only re-run spans cost new tokens →
  a small edit can show a large negative token delta (correct, if unintuitive). Decision
  **B5**.
- **Latency:** frozen spans are instant; only re-run spans take time.
- **Diff:** the dashboard shows a Git-like old/new comparison (the `BranchDiff` view).

CineRater's `genre: Sci-Fi → Comedy` and the flight `A → D` example are the **same thing.**

### Honest limitation: linear, not a full DAG

A full DAG engine marks only **dependent** downstream nodes "dirty" and reruns just those.
**Loupe uses a linear cursor:** freeze everything before the branch point, re-run everything
at/after it in sequence — even branches unrelated to the edit. For sequential agents the
result is identical; for parallel fan-out it's less precise. Scoped and deferred as **B9
(replay-plan concurrency)**.

> **Interview line:** *Server-side capture is observability; true "what-if" replay needs an
> execution engine that resumes the workflow — that's the SDK (execution plane) vs the server
> (control plane), Loupe's B1 split. Loupe does linear freeze-before/live-after replay via a
> cursor, not full DAG dirty-node propagation; identical for sequential agents, and I scoped
> per-span dependency edges as B9 for parallel fan-out.*

---

## 9. How Loupe compares to LangSmith / Helicone

- **Helicone** is primarily an **observability proxy** — it records requests/responses and
  can compare prompts/cost/latency across requests, but it **does not run your agent graph.**
  It can't "change a tool output and see how downstream agents react" — it doesn't know the
  dependencies. If you want that, *your app* must do the replay; Helicone just observes the
  new run.
- **LangSmith** does observability **and** (via LangSmith Experiments + an execution engine
  like LangGraph) replay. It stores rich per-run data (run IDs, inputs/outputs, parent/child,
  timing, tokens) so it can rerun a downstream run using a modified upstream output.
- **Loupe** builds the same replay loop, and goes further into **replay-driven prompt
  testing** (v2.2): replay *many* traces + auto-judge + wrap in GitHub to block bad prompt
  merges.

### The general architecture (how teams split this)

- **Execution engine** (LangGraph / custom orchestrator / **Loupe SDK**) — knows how to run
  and *resume* workflows.
- **Observability layer** (LangSmith / Helicone / OpenTelemetry / **Loupe server**) — records
  executions, metrics, comparisons.
- **Experimentation layer** (**Loupe v2.2 suites + judge**) — injects modified prompts / tool
  outputs / model params and initiates replay to measure impact on cost, latency, behaviour.

Loupe's differentiator: it's one coherent tool that spans all three, with the
production-trace → regression-suite → PR-gate loop on top.

> **Interview line:** *Helicone observes but can't replay your graph; LangSmith needs a
> separate execution engine for experiments; Loupe's SDK is both the instrumentation and the
> execution engine, so it delivers the full loop — capture, replay, diff — and v2.2 extends it
> into PR-gated prompt regression testing.*

---

## Quick decision recap

| ID | Topic | Status |
|----|-------|--------|
| B8.1 | Suite storage = reference + `suite_traces` join table | ✅ decided |
| B8.2 | `suite_runs.results` as JSONB (per-trace records) | ✅ decided |
| B8.3 | Global default rubric + optional per-suite override | ✅ decided |
| B8.4 | Hybrid scoring; single-call judge; **pluggable backend** (Groq free dev / Sonnet demo) | ✅ decided |
| B11 | PII/secret redaction before capture + before judge | 🟡 tracked (open) |

See [ARCHITECTURE_DECISIONS.md](../ARCHITECTURE_DECISIONS.md) for the full tension → options
→ tradeoffs → decision writeups.

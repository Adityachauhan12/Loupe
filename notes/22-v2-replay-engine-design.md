# 22 — v2 Replay Engine: Design (Time-Travel Debugger)

> This is the v2 headline feature: a **debugger for non-deterministic agents**.
> Think `rr` (record-and-replay) or time-travel debugging — but for LLM agents.
> This note is interview prep. It explains the three design decisions in plain
> language with the GitHub-triage agent as the running example.

---

## The one-sentence pitch

> "An agent failed in production. I can't reproduce the failure because the run
> was non-deterministic and the world moved on. Loupe lets me open the trace,
> click the span that went wrong, change it, and replay from there — without
> re-running the whole agent or causing duplicate side effects."

No incumbent (Langfuse, LangSmith, Helicone, Braintrust) does this. They replay
a single LLM call in a playground at best. None replay a full agent trace from
the middle. That gap is the wedge.

---

## The running example: GitHub-triage agent

The agent triages GitHub issues. One run = one trace:

```
list_open_issues   → reads GitHub          [issue #1, #2, #3]
classify_issue #1  → Groq LLM call          "bug"      ✅
classify_issue #2  → Groq LLM call          "feature"  ✅
classify_issue #3  → Groq LLM call          "bug"      ❌ should be "question"
add_label          → WRITES to GitHub
post_comment       → WRITES to GitHub
```

Issue #3 ("How do I reset my password?") was misclassified as `bug`. I want to
fix the prompt and prove my fix works — without re-posting comments on GitHub.

---

## Decision 1 — Side effects: dry-run by default

### The problem
Replaying re-runs spans. Some spans **write to the real world** — post a comment,
send an email, charge a card. Re-running them = duplicates. Some duplicates are
irreversible (you can't un-send an email or un-charge a card).

### The decision
Every span during replay falls into one of three buckets:

```
BEFORE the branch point   →  use stored output (never re-run)
AT the branch point       →  use my edited output
AFTER the branch point    →  re-run, but writes are DRY-RUN by default
```

A **dry-run** doesn't execute the write. It shows a ghost span:
> "Would add label: question"
> "Would post comment: ..."

The developer opts a tool into real execution explicitly:
```python
@loupe.span(type="tool", name="add_label", replay="live")     # really write
@loupe.span(type="tool", name="add_label", replay="dry_run")  # default, safe
```

### Why
Replay is a **debugging tool, not a re-execution tool**. You want to compute the
new outcome, not perform the actions again. Safe default = never cause a
duplicate. Unannotated agents are automatically safe.

### Heuristic fallback (no annotation)
- `llm` → live (stateless, the whole point)
- `tool` → dry-run (safe)
- `retrieval` / `function` → live (reads / pure computation are safe)

---

## Decision 2 — Determinism: freeze before, live after

### The problem
LLMs are non-deterministic. Same prompt → possibly different answer. So if replay
re-runs **every** LLM call, you get noise. Example of the WRONG approach:

```
I fix the prompt and re-run ALL classify_issue calls:
classify_issue #1  → "feature"   ❌ now THIS broke (randomness, not my fix)
classify_issue #2  → "feature"   ✅
classify_issue #3  → "question"  ✅ fixed
```
Did my fix work? I can't tell — #1 changed for unrelated reasons.

### The decision
"Deterministic" here does NOT mean "the LLM always returns the same thing." It
means **isolate exactly what changed**:

```
classify_issue #1  → "bug"       FROZEN (stored output, before branch)
classify_issue #2  → "feature"   FROZEN (stored output, before branch)
classify_issue #3  → "question"  RE-RUN (this is the branch point)
add_label          → dry-run     (after branch)
post_comment       → dry-run     (after branch)
```

Only the call I changed re-runs. Everything before is frozen. Now the change in
#3 is **provably caused by my edit** — nothing else moved.

### Analogy
A **controlled experiment**: change one variable, hold everything else fixed,
observe the effect. Freezing the before-branch spans = holding everything fixed.

### Residual randomness (be honest)
The branch span and anything after still run live, so two replays can differ.
Mitigations: capture `seed` + `temperature` (done in Phase 1), replay with
`temperature=0`, and store both original + replay outputs so the diff shows them
side by side. Replay at/after the branch is **best-effort** — that's a property
of LLMs, not a bug.

---

## Decision 3 — Branch tree: lineage on the traces table

### The idea
A branched run is just a normal trace. Same `traces` table, same span tree, same
detail page. It only carries two extra fields saying where it came from.

```sql
ALTER TABLE traces ADD COLUMN branched_from_trace_id UUID REFERENCES traces(id);
ALTER TABLE traces ADD COLUMN branched_from_span_id  UUID REFERENCES spans(id);
ALTER TABLE spans  ADD COLUMN replay_policy TEXT DEFAULT 'dry_run';  -- live|dry_run
```

- `branched_from_span_id` → tells the **engine** where to start re-running
- `branched_from_trace_id` → tells the **dashboard** what to diff against
  (storing both avoids a join on the diff render path)

### Branches form a tree
A branch can be branched again — no special handling, because a branch is just a
trace:

```
trace_A  (production run, root, branched_from = NULL)
  ├── trace_B  branched from A at classify_issue#3
  │     └── trace_D  branched from B at add_label
  └── trace_C  branched from A at classify_issue#1
```

Adjacency list (each node knows its parent) — the same pattern as `parent_span_id`
on spans. Walk parent links to get full lineage. Recursive CTE is the at-scale
option but not needed at MVP depth.

### Query the dashboard runs on every trace page
```sql
SELECT * FROM traces WHERE branched_from_trace_id = :trace_id;  -- "branches from here"
CREATE INDEX idx_traces_branched_from ON traces(branched_from_trace_id);
```

### Reuses the existing replays table
A branch = one `traces` row (the run) + one `replays` row (the diff metadata:
`original_trace_id`, `new_trace_id`, `modifications`). No new diff table needed.

---

## Why Phase 1 (capture) was the hard part

Replay is only possible if we already stored each span's **exact** input and
output. We fixed that in Phase 1:
- `@loupe.span` as a decorator now auto-captures args + return value
- `instrument_groq` now captures messages, model, temperature, seed
With capture complete, the schema change for replay is tiny — two columns.

**Interview line:** "Deterministic replay is an architectural commitment you make
on day one — you have to capture exact inputs from the start. Most observability
tools didn't, which is why they can't offer this. Loupe captured it from the
beginning."

---

## Likely interview questions

**Q: How do you avoid duplicate side effects when replaying?**
Dry-run by default. Post-branch write spans don't execute — they produce a ghost
span showing what *would* have happened. Developers opt specific tools into live
execution with `replay="live"`. Unannotated agents are safe automatically.

**Q: LLMs are non-deterministic. How is "replay" even meaningful?**
Determinism here means isolating the change, not freezing LLM output. Everything
before the branch point uses stored outputs (frozen); only the branch span and
downstream re-run. So any change in the output is provably caused by the edit —
a controlled experiment. Residual variance after the branch is best-effort,
minimised with seed + temperature=0, and shown via side-by-side diff.

**Q: How do branches relate to each other in the schema?**
Two nullable columns on `traces`: `branched_from_trace_id` (parent trace) and
`branched_from_span_id` (branch point). Adjacency-list tree, same as
`parent_span_id` on spans. Branching a branch needs no special handling because a
branch is a normal trace. Diff metadata reuses the existing `replays` table.

**Q: Why store both branched_from_trace_id and branched_from_span_id?**
The span id is for the replay engine (where to start re-running). The trace id is
for the dashboard (what to diff against, what to list as children) — storing it
avoids a join on the hot diff-render path. Cheap denormalisation.

**Q: Why not just re-run the whole agent?**
Three reasons: (1) cost — you'd re-call every LLM; (2) side effects — duplicate
GitHub comments / emails / charges; (3) signal — re-running everything buries the
effect of your change in unrelated LLM randomness. Branch + freeze solves all
three.

**Q: How would this scale?**
Lineage walk becomes a recursive CTE. Replay jobs move from FastAPI
BackgroundTasks to Celery + Redis for real concurrency. Large span payloads move
from inline JSONB to content-addressed blob storage (hash in Postgres, blob in
S3). All documented as known migration paths.

**Q: What's the safety story if someone replays a payment agent?**
The write span (`charge_card`) defaults to dry-run — it shows "would charge $X"
and never hits the payment API unless explicitly annotated `replay="live"`. The
unsafe action is opt-in, not opt-out. That default is the entire point.

---

## One-liner to remember

**"Freeze before the branch, re-run at and after it, dry-run the writes."**
That single sentence is the whole replay engine.

# Design: Side-Effect Classification for Replay

## The Problem

When replaying a trace from a branch point, the engine re-executes spans after
the branch. Some of those spans have real-world side effects — posting a GitHub
comment, sending an email, booking a flight, charging a card. Re-executing them
naively causes duplicates.

Replay is primarily a debugging tool. The goal is to compute the new outcome,
not to perform real-world actions again.

## The Rule

Every span during replay falls into exactly one of three cases:

```
Before branch point  →  use stored output (never re-execute)
At branch point      →  use user's edited output (never re-execute)
After branch point   →  re-execute, but honour side-effect policy
```

## Side-Effect Policy (after branch point)

| Span type | Default behaviour | Why |
|-----------|-------------------|-----|
| LLM call | Re-execute (live) | Stateless, the whole point of replay |
| Read-only tool | Re-execute (live) | Safe, no side effects |
| Write tool | Dry-run | Would cause duplicates |
| Idempotent write | Re-execute (live) | Safe — same result if done twice |

**Default is dry-run for writes.** The developer must explicitly opt a tool into
live execution during replay.

### What dry-run means

The span is not executed. Instead the engine records a synthetic span with:
```json
{
  "name": "add_label",
  "type": "tool",
  "dry_run": true,
  "output": { "would_have": { "issue": 3, "label": "question" } }
}
```

The dashboard shows this as a ghost span — same position in the tree, visually
distinct, with the computed inputs so the developer can verify the new outcome
without touching the real world.

## Example — Triage Agent

Original trace:
```
list_open_issues   → [issue #1, #2, #3]
classify_issue     → { label: "bug", comment: "..." }   ← WRONG
add_label          → GitHub: adds "bug"
post_comment       → GitHub: posts comment
```

User branches at `classify_issue`, fixes the system prompt.

Replay execution:
```
list_open_issues   → stored output (before branch point)
classify_issue     → re-executed with new prompt → { label: "feature" }
add_label          → DRY-RUN → "Would add label: feature"
post_comment       → DRY-RUN → "Would post comment: ..."
```

No duplicate GitHub actions. Developer sees the correct new outcome.
If they're satisfied, they can promote the replay to a real run with
`--live-writes` flag or a dashboard toggle.

## How tools are classified

### Option 1 — SDK annotation (explicit, preferred)

```python
@loupe.span(type="tool", name="add_label", replay="dry_run")
def add_label(issue_number: int, label: str) -> dict:
    ...

@loupe.span(type="tool", name="list_open_issues", replay="live")
def list_open_issues() -> list:
    ...
```

### Option 2 — Heuristic fallback (when no annotation)

If `replay` is not annotated, the engine falls back to:
- `type="llm"` → always live
- `type="tool"` → dry-run (safe default, never causes duplicates)
- `type="retrieval"` → live (reads are safe)
- `type="function"` → live (pure computation, no side effects assumed)

This means an unannotated agent is safe to replay by default.
The developer only needs to annotate tools they explicitly want live.

## What we are NOT doing

- No automatic detection of side effects from code analysis
- No sandboxed execution environment
- No network interception / mocking at the HTTP level

These are more complex and not needed for the MVP replay engine.
The annotation approach is explicit, simple, and sufficient.

## Tradeoffs

**Why not re-execute all writes?**
Duplicate side effects are often irreversible (emails, payments, bookings).
Dry-run by default is the only safe choice. An agent that double-charges a
card during debugging is worse than an agent that shows a ghost span.

**Why not block all tool calls?**
Read-only tools (list_issues, search_db, fetch_url) are safe and often
necessary — downstream LLM calls depend on their output being fresh.
Blocking them would force the engine to use stale stored data, which
defeats the purpose of branching.

**Why not detect idempotency automatically?**
Idempotency is a semantic property the framework can't infer from code.
Explicit annotation is more honest. Document the convention; let developers
opt in.

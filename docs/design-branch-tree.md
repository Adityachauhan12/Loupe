# Design: Branch Tree Model

## What a "branch" is

A branch is a new trace created by replaying an existing trace from a chosen
span (the branch point), with that span's output modified.

The branched trace is structurally identical to any other trace — same `traces`
table, same `spans`, same query paths, same detail page. The only difference is
two extra fields recording where it came from.

This is the same design decision already made for replays: a replayed run lives
in the `traces` table and is treated uniformly. Branching extends that idea.

## Schema

### `traces` — two new fields

```sql
ALTER TABLE traces ADD COLUMN branched_from_trace_id UUID REFERENCES traces(id);
ALTER TABLE traces ADD COLUMN branched_from_span_id  UUID REFERENCES spans(id);
```

- `branched_from_trace_id` — the parent trace this branch grew from
- `branched_from_span_id`  — the exact span where the branch was taken

Both are NULL for normal (non-branched) traces.

### `spans` — one new field (from the side-effects design)

```sql
ALTER TABLE spans ADD COLUMN replay_policy TEXT DEFAULT 'dry_run';
-- 'live' | 'dry_run'
```

## Lineage — branches form a tree

A trace can be branched. A branch can itself be branched. This forms a tree of
traces linked by `branched_from_trace_id`.

```
trace_A  (original production run)
  │
  ├── trace_B   branched from A at classify_issue#3   (fixed the prompt)
  │     │
  │     └── trace_D   branched from B at add_label    (then tweaked a tool)
  │
  └── trace_C   branched from A at classify_issue#1   (a different experiment)
```

- `trace_B.branched_from_trace_id = trace_A.id`
- `trace_D.branched_from_trace_id = trace_B.id`
- `trace_A.branched_from_trace_id = NULL` (it's a root)

Each node knows only its direct parent (`branched_from_trace_id`). The full tree
is reconstructed by walking parent links — a standard adjacency-list tree, the
same pattern already used for `parent_span_id` in the spans table.

## Why store BOTH trace and span id?

- `branched_from_span_id` tells the **replay engine** where to start re-executing
  (freeze everything before this span, re-run at/after it).
- `branched_from_trace_id` tells the **dashboard** how to draw lineage and which
  original to diff against, without having to look up the span's trace first.

Storing both is cheap and removes a join on the hot path (rendering the diff).

## Queries

**Direct children of a trace** (the "branches from here" list):
```sql
SELECT * FROM traces WHERE branched_from_trace_id = :trace_id;
```

**The original a branch came from** (for the diff view):
```sql
SELECT * FROM traces WHERE id = :branched_from_trace_id;
```

**Full lineage of a branch** (walk up to the root) — done in application code by
following `branched_from_trace_id` until NULL. At MVP depth (a handful of
branches) this is trivial; a recursive CTE is the path at scale.

```sql
-- scale option, not needed for MVP
WITH RECURSIVE lineage AS (
  SELECT * FROM traces WHERE id = :trace_id
  UNION ALL
  SELECT t.* FROM traces t
  JOIN lineage l ON t.id = l.branched_from_trace_id
)
SELECT * FROM lineage;
```

## Index

```sql
CREATE INDEX idx_traces_branched_from ON traces(branched_from_trace_id);
```

Makes "list branches of this trace" fast — the query the dashboard runs on every
trace detail page.

## Relationship to the existing `replays` table

The `replays` table already holds diff metadata (modifications, diff_summary)
between an original and a new trace. Branching reuses it:

- `replays.original_trace_id` = the branch's parent
- `replays.new_trace_id`      = the branch itself
- `replays.modifications`     = `{ branch_span_id, new_output }`

So a branch produces one `traces` row (the run) plus one `replays` row (the diff
metadata). No new table needed for the diff — only the two lineage columns on
`traces`.

## Can you branch a branch?

Yes, and it requires no special handling. A branch is a normal trace, so
branching it follows the identical path. The lineage tree simply grows one level
deeper. This falls out of treating branched traces uniformly — we get arbitrary
branch depth for free.

## What we are NOT doing

- No separate `branches` table — lineage lives on `traces`
- No materialised tree / closure table — adjacency list is enough at MVP scale
- No limit on branch depth — the uniform model makes depth a non-issue

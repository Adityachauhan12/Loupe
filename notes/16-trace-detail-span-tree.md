# 16 — Dashboard: Trace Detail + Span Tree

## What changed

- `dashboard/app/traces/[id]/page.tsx` — Server Component: fetches full trace, renders metadata row (started/duration/tokens/cost/spans), input/output JSON blocks, span tree
- `dashboard/components/SpanTree.tsx` — Client Component: builds nested tree from flat span list, click-to-expand per span showing input/output/error JSON, type badges (llm/tool/fn/ret), duration bar relative to trace total
- `dashboard/lib/api.ts` — added `SpanOut`, `TraceDetail` types + `getTrace(id)` function
- Also fixed: `client.py` broad `Exception` catch so unexpected errors don't silently kill the worker thread; `page.tsx` NaN-safe offset parsing

## How the span tree works (simple explanation)

Imagine your agent ran 5 steps:
- Step 1: agent decides what to do (LLM call)
- Step 2: agent calls search_movies (tool)
- Step 3: inside search, calls the DB (function)
- Step 4: agent reads result and responds (LLM call)
- Step 5: done

These are saved as a **flat list** in the DB (like a list of items). But they have a parent-child relationship: Step 3 is a child of Step 2, which is a child of Step 1.

The span tree component takes that flat list and builds a visual tree:
```
[llm] openai.chat                  1.2s   400 tok  $0.04
  [tool] search_movies             0.4s
    [fn] db.query                  0.1s
  [llm] openai.chat                0.6s   834 tok  $0.01
```

Click any row → see the exact JSON that went in and came out of that step.

## Sub-step learnings

### Building a tree from a flat list

The server returns spans as a flat array. The component builds the tree:

```typescript
function buildTree(spans: SpanOut[]): SpanNode[] {
  const byId = new Map<string, SpanNode>()
  spans.forEach(s => byId.set(s.id, { span: s, children: [] }))

  const roots: SpanNode[] = []
  spans.forEach(s => {
    const node = byId.get(s.id)!
    if (s.parent_span_id == null) {
      roots.push(node)   // no parent = top-level span
    } else {
      const parent = byId.get(s.parent_span_id)
      if (parent) parent.children.push(node)
      else roots.push(node)  // orphan (parent not in list) → treat as root
    }
  })
  return roots
}
```

**Time complexity:** O(n) — two passes over the flat list. First pass builds the map. Second pass links children to parents.

**Why flat list in DB, not tree?** Trees in relational DBs are painful. Flat list with `parent_span_id` is the standard approach (used by Jaeger, Zipkin, OpenTelemetry). The tree is a view-layer concern, not a storage concern.

### `"use client"` boundary — where to draw it

The page (`traces/[id]/page.tsx`) is a Server Component — data fetching, static rendering, no JS sent to browser.

The span tree needs to be a Client Component because of `useState` (for tracking which spans are expanded). But the actual DATA (span list) comes from the server.

The pattern:
```
Page (Server Component)
  ↓ fetches data
  ↓ passes as props
SpanTree (Client Component)
  ↓ interactive: expand/collapse
  ↓ uses useState, useCallback
```

Server Components can pass **serializable** data (plain objects, strings, numbers) to Client Components as props. `SpanOut[]` is just JSON, so this works.

**What you cannot do:** pass functions or class instances from Server to Client. They don't serialize.

### `useCallback` for the toggle handler

Every render of `SpanTree` recreates the `toggle` function. Without `useCallback`, each `SpanRow` gets a new `onToggle` prop on every re-render (even if nothing changed) → React re-renders all rows unnecessarily.

With `useCallback`:
```typescript
const onToggle = useCallback((id: string) => {
  setExpanded(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
}, [])  // empty deps — function never changes
```

The function is memoized. `SpanRow` only re-renders when its specific data changes.

### Duration bar (visual relative timing)

Each span shows a horizontal bar whose width = `(span.duration_ms / total_trace_duration) * 100%`. This gives an instant visual sense of where time was spent.

```typescript
const pct = Math.min(100, (ms / totalMs) * 100)
<div style={{ width: `${pct}%` }} className="h-full rounded-full bg-gray-500" />
```

Without this bar, rows of numbers are hard to scan. The bar makes "this LLM call took 80% of the total time" obvious at a glance.

### `notFound()` vs throwing an error

When a trace doesn't exist (404 from server), we call Next.js's `notFound()` instead of throwing an error. This renders the nearest `not-found.tsx` (or the default Next.js 404 page) which is cleaner than a crash page.

```typescript
try {
  trace = await getTrace(id)
} catch (err) {
  console.error("Failed to fetch trace:", err)
  notFound()  // renders 404 page, not error boundary
}
```

For a real 500 (server crash), throwing would trigger `error.tsx` (if it exists). For "resource not found", `notFound()` is semantically correct.

## Interview questions this covers

**Q: Why store spans as a flat list with parent_span_id instead of a nested JSON tree?**
A: Flat list in Postgres + parent FK gives you: O(1) span inserts (no tree traversal needed), standard SQL queries (find all spans for a trace = simple WHERE), easy indexing (`idx_spans_trace`, `idx_spans_parent`). A nested JSON tree would be one JSONB blob — you can't query individual spans, can't page them, can't index by type or duration. Tree structure is reconstructed in the application layer where it belongs.

**Q: What's the difference between `notFound()` and `throw new Error()` in Next.js?**
A: `notFound()` triggers the 404 response path — renders `not-found.tsx` or the default 404 page. `throw new Error()` triggers the error boundary — renders `error.tsx`. Use `notFound()` when a resource doesn't exist (expected), `throw` when something broke unexpectedly.

**Q: How do you prevent unnecessary re-renders in the span tree?**
A: `useCallback` on the toggle handler (stable function reference), and each `SpanRow` only re-renders when its `node`, `depth`, or `expanded` set changes. For larger trees (100+ spans), you'd also want `React.memo` on `SpanRow` so it bails out of rendering when props haven't changed.

**Q: Why not use a library like react-flow for the span tree?**
A: CLAUDE.md explicitly says "react-flow is overkill, custom gives full control." For spans, a nested list is the right visualization — not a graph. Graph libs add 500KB+ to the bundle and complex APIs for a simple indented list. Custom recursive component is 100 lines and gives exactly the UX we want.

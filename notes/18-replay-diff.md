# 18 — Dashboard: Side-by-Side Replay Diff

## What changed

**Server:**
- `server/app/schemas.py` — added `ReplayDetail` schema with `original_trace_id`, `new_trace_id`, `modifications`, `diff_summary`, `created_at`
- `server/app/routers/replays.py` — updated `GET /v1/replays/{id}` to return full `ReplayDetail` instead of minimal `ReplayCreated`

**Dashboard:**
- `dashboard/app/replays/[id]/page.tsx` — diff page: fetches replay + both traces in parallel, shows `ReplayDiff`, handles "still running" state with auto-refresh
- `dashboard/components/ReplayDiff.tsx` — two-column layout: header cards (model/status/tokens/cost per side), delta summary row (Δ tokens, Δ cost, Δ latency with colour), per-LLM-span output pairs
- `dashboard/components/AutoRefresh.tsx` — tiny client component that calls `router.refresh()` every 3s while replay is running
- `dashboard/app/traces/[id]/actions.ts` — redirect changed from `/traces/{new_trace_id}` to `/replays/{replay_id}`
- `dashboard/lib/api.ts` — added `ReplayDetail` type + `getReplay(id)` function

## How the diff page works (simple explanation)

When you submit a replay:
1. Server creates the replay and returns `replay_id` + `new_trace_id`
2. Dashboard redirects you to `/replays/{replay_id}`
3. Page fetches the replay record → gets both trace IDs → fetches both traces in parallel
4. Shows them side by side:

```
ORIGINAL                          REPLAY
claude-sonnet-4-5                 llama-3.3-70b-versatile (Groq)
success · 3.2s · 450 tok · $0.02  success · 0.8s · 78 tok · $0.00
─────────────────────────────────────────────────────────────────
Δ tokens: −372 (−83%)   Δ cost: −$0.02   Δ latency: −2.4s (−75%)
─────────────────────────────────────────────────────────────────
LLM OUTPUT #1             LLM OUTPUT #1
"I recommend Arrival..."  "As a film critic, I recommend Arrival..."
```

**Analogy:** Like a git diff but for LLM outputs — you see exactly what changed when you tweaked the prompt or swapped the model.

## Sub-step learnings

### `Promise.all` for parallel fetches in Server Components

Both traces (original + replay) are independent — no reason to fetch them one after the other. `Promise.all` fires both requests simultaneously:

```typescript
const [original, replayTrace] = await Promise.all([
  getTrace(replay.original_trace_id),
  getTrace(replay.new_trace_id),
])
```

**Why this matters:** If each trace fetch takes 100ms, serial = 200ms total. Parallel = 100ms total. For pages with multiple independent data sources, `Promise.all` is always the right move.

### AutoRefresh — client island in a Server Component page

The diff page is a Server Component — no client JS runs by default. But when the replay is still "running", we need to poll. The fix: a tiny Client Component (`AutoRefresh`) that does just the interactive work:

```typescript
"use client"
export function AutoRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter()
  useEffect(() => {
    const t = setInterval(() => router.refresh(), intervalMs)
    return () => clearInterval(t)
  }, [router, intervalMs])
  return null  // renders nothing, just runs the side-effect
}
```

`router.refresh()` in Next.js re-runs all server components on the current page (re-fetches data) without a full browser reload. This is the idiomatic way to poll in App Router.

**The pattern:** Server Components handle data; Client Components handle interactivity. Keep the Client Component surface as small as possible (this one is 8 lines). The rest of the page stays server-rendered.

### Redirect to `/replays/{id}` not `/traces/{new_trace_id}`

Initially we redirected to the new trace page. The problem: that page just shows the replay trace in isolation — you lose context of "what changed compared to the original."

Redirecting to `/replays/{id}` gives the user the comparison immediately. They can always click "View replay trace →" to see the full span tree for the replay.

**Rule of thumb:** After a user action that creates a comparison, send them to the comparison view, not one of the individual items.

### Colour-coding Δ values — green for savings, red for increases

For cost/tokens/latency, **lower is better**. So:
- Negative delta (−) → green (you used fewer tokens / less money / faster)
- Positive delta (+) → red (you used more)

```typescript
function delta(n: number, unit: string, invert = false): React.ReactNode {
  const negative = invert ? n > 0 : n < 0
  return <span className={negative ? "text-green-400" : "text-red-400"}>...</span>
}
```

The `invert` flag handles cases where higher is better (not used here, but the helper supports it).

### LLM span matching by index

Both traces have LLM spans. To show them side by side, we match by position (first LLM span in original ↔ first LLM span in replay):

```typescript
const origLLM = llmSpans(original)  // sorted by started_at
const repLLM  = llmSpans(replay)
Array.from({ length: Math.max(origLLM.length, repLLM.length) }).map((_, i) => (
  <OutputBlock span={origLLM[i]} />  // undefined if replay has more spans
  <OutputBlock span={repLLM[i]} />
))
```

Matching by `name` would be more robust for multi-span agents, but index matching is correct for MVP (same structure, different outputs).

## Interview questions this covers

**Q: How do you handle a page that shows data from two different sources?**
A: `Promise.all` for parallel fetching in a Server Component. One await, both responses available simultaneously. If one fails, the catch block handles both.

**Q: How do you add real-time updates to a Next.js Server Component page?**
A: A small `"use client"` island that calls `router.refresh()` on an interval. `router.refresh()` re-runs the server components without a full navigation, fetching fresh data. The server component itself stays unchanged — it just re-executes with new data.

**Q: Why redirect to `/replays/{id}` instead of `/traces/{new_trace_id}`?**
A: The user's goal after creating a replay is to compare, not to inspect one trace in isolation. The diff page is the direct answer to "did my change improve things?" — it shows token delta, cost delta, and output side by side in one view. The trace detail is one click away if needed.

**Q: How do you show token/cost savings in a meaningful way?**
A: Absolute delta + percentage. "−372 tokens (−83%)" is more readable than just "−372" because it contextualises the saving. A 372-token saving on a 1000-token trace is significant; on a 1M-token trace it's noise. The percentage makes that clear at a glance.

**Q: What's the difference between `router.refresh()` and `router.push()`?**
A: `router.push()` navigates to a new URL — adds a history entry, runs full page lifecycle. `router.refresh()` re-fetches server component data for the *current* URL — no navigation, no history change, no client state reset. It's like hitting F5 but without losing React state (like scroll position, open modals, etc.).

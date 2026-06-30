# 26 — Branch Diff View (original vs counterfactual, side by side)

> The payoff of everything in notes 22–25. You branched a trace and re-ran it;
> now you see **original vs branched, from the branch point onward**, with the
> deltas and the status flip that make the change obvious.

---

## What it is (in one breath)

A `git diff`, but between two **agent runs**. "I changed this one step — what
changed downstream?" One screen: original on the left, branched on the right,
aligned span-by-span from the branch point, with token / cost / latency deltas and
a big banner when the branch turned a **failed** run into a **passing** one.

Route: `/traces/<branched_id>/diff`. Reachable from the lineage banner on any
branched trace ("⑂ Branched run · View original · **View diff →**").

## The one idea that makes it work — positional alignment

Diffing non-deterministic runs sounds hard: if you match spans by *content*, a
re-run whose text drifted looks "added/removed" even when nothing structural
changed. We sidestep that entirely.

The branch engine produces a trace that is a **1:1 structural copy** of the
original in execution order: frozen spans before the branch, the edited
**branch-point** span (tagged `metadata.branch_point = true`), then the re-run /
ghost spans after. So alignment is **positional, not fuzzy**:

```
sort both by started_at  →  find the branch index  →  pair index-by-index from there
```

Original's branch index = the span whose `id == branched_from_span_id`. Branched
trace's branch index = the span carrying the `branch_point` marker (fallback to the
same position). Everything before is identical (frozen) and shown only as a count;
everything from the branch point onward is paired and compared. Robust because the
structure is *guaranteed* the same — only outputs differ.

> Analogy: two printouts of the same form, same fields in the same order. You don't
> hunt for matching sentences — you read line N against line N.

This logic is a **pure function**, `alignFromBranch()` in
[`dashboard/lib/diff.ts`](../dashboard/lib/diff.ts). The component
([`BranchDiff.tsx`](../dashboard/components/BranchDiff.tsx)) is a dumb render layer
on top — decisions in one place, UI churn in another.

## What the diff surfaces

- **Status-change banner** — the money shot. `error → success` ⇒ green "✓ Branch
  fixed the run"; `success → error` ⇒ red "✗ Branch broke the run".
- **Trace deltas** — Δ tokens / Δ cost / Δ latency (a drop renders green: cheaper/
  faster is better).
- **Per-span pairs** — original vs branched output, each tagged `edited` (the branch
  point), `changed`, or `same`, plus marker badges (branch point / ghost / passthrough).
- **Branch kind label** — "SDK-side replay (edit propagated)" vs "Server-side branch
  (preview, tools not re-run)". Today this is *inferred* from span markers (see the
  honest caveat below; we decided to make it an explicit column — arch decision B3).

## Honest caveats (designed in, not bugs)

- **First-span branches show no frozen note and "Branch" not a kind.** If you branch
  at the very first span there are no frozen spans and no markers to read, so the
  count and kind are legitimately empty. The code is honest about not knowing.
- **Server-side branch diffs look "unchanged" downstream.** That path can't run your
  tools, so the edit doesn't propagate — expected (note 24/25). The *SDK-side* diff
  is the compelling one. Hence the kind label.
- **Blended cost.** Frozen spans reuse the original's tokens; a small edit can show
  ~0 token delta because most spans were frozen copies. Correct, just unintuitive —
  we label it (arch decision B5).

## The debugging story worth remembering (stale server)

During live verification the branched trace's `branched_from_trace_id` came back
**null** — which would mean the diff could never find the original. I chased it
layer by layer instead of guessing:

1. Stale data? Made a **fresh** branch → still null. Not old data.
2. SDK sending it? Code + a `model_dump_json()` repro → it serializes fine.
3. Right package running? `loupe.__file__` → yes, the editable `sdk/loupe`.
4. Intercepted `enqueue` → the payload **had** `branched_from` set. SDK is innocent.
5. Hand-crafted `curl` POST with the field → DB stored **null**. **Server drops it.**
6. But the server *source* persisted it… because the **running server was an old
   process**, started before that line existed. Restart → persists → diff works.

**Lesson:** when behaviour contradicts the source, suspect the *running artifact*
before the code. A long-lived dev server silently serving stale bytecode is a
classic. Binary-search the pipeline (SDK → wire → server → DB); prove each hop,
don't assume. The negative result that cracked it — `is_replay:true` persisted but
`branched_from:null` — ruled out serialization (it's all-or-nothing), pointing
straight at the server.

## Interview Q&A

**Q: How do you diff two runs of a non-deterministic agent without flaky matching?**
A: We don't match by content. The branch engine emits a structural 1:1 copy of the
original in execution order and tags the branch point explicitly, so alignment is
positional — find the branch index, pair index-by-index from there. Spans before the
branch are frozen and identical; only the part after the edit is compared.

**Q: Why one route keyed by the branched trace id instead of reusing the replay row?**
A: The lineage (`branched_from_*`) lives on the trace and is set by *both* replay
paths, while a `replays` row is only written by the server-side path. Keying the
diff on the trace id covers server-side and SDK-side branches with one route and no
new endpoint — it just reads `branched_from_trace_id` and fetches both traces.

**Q: You hit a bug where lineage was null. How did you find it was the server, not
the SDK?** A: I isolated each hop. A serialization repro and an `enqueue` intercept
proved the SDK sent the field; a hand-crafted POST proved the *server* dropped it
despite correct source — which only makes sense if the running server was stale.
Restarting it fixed it. The tell was that `is_replay` persisted while
`branched_from` didn't: same payload, so it wasn't serialization.

**Q: Isn't "kind inferred from markers" fragile?** A: It's best-effort and returns
"unknown" for marker-less (first-span) branches — honest, but vague on a flagship
screen. So we decided to store an explicit `replay_mode` column (arch decision B3)
and keep inference only as a fallback for old rows.

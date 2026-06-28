// Pure alignment logic for the branched-vs-original diff (Phase 7).
//
// A branch is a *structural 1:1 copy* of the original trace in execution order:
// every span before the branch point is frozen (stored output), the branch-point
// span carries the user's edit, and everything after it is re-run / ghosted.
// Because the structure is guaranteed identical, we align spans *positionally*
// from the branch point onward — no fragile content matching.

import type { SpanOut, TraceDetail } from "@/lib/api";

export interface DiffPair {
  /** Same execution slot in the original trace (may be undefined if lengths differ). */
  original?: SpanOut;
  /** Same execution slot in the branched trace. */
  branched?: SpanOut;
  /** True for the edited span where the branch starts. */
  isBranchPoint: boolean;
  /** Output text/JSON differs between the two sides. */
  changed: boolean;
}

export type BranchKind = "sdk" | "server" | "unknown";

export interface BranchDiff {
  /** Index of the branch point in the original's execution order; -1 if not found. */
  branchPointIndex: number;
  /** Spans before the branch point — identical on both sides, not shown in detail. */
  frozenCount: number;
  /** Paired spans from the branch point onward (the interesting part). */
  pairs: DiffPair[];
  tokenDelta: number;
  latencyDelta: number;
  costDelta: number;
  statusChanged: boolean;
  /** Best-effort label of which replay path produced the branch. */
  kind: BranchKind;
}

function byStart(spans: SpanOut[]): SpanOut[] {
  return [...spans].sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  );
}

function isBranchPointSpan(s: SpanOut): boolean {
  return s.metadata?.branch_point === true;
}

/** Stable-ish compare: outputs are copied with the same key order, so a plain
 * JSON.stringify diff is enough to flag a real change. */
function outputsDiffer(a: SpanOut | undefined, b: SpanOut | undefined): boolean {
  if (!a || !b) return true;
  return JSON.stringify(a.output ?? null) !== JSON.stringify(b.output ?? null);
}

/** Infer the replay path from the markers the engines leave on span metadata.
 * Server engine writes `dry_run` / `stored_passthrough`; SDK engine writes
 * `replay: "frozen"` on pre-branch spans. Soft label only — falls back to
 * "unknown" (e.g. a server branch whose downstream was pure-LLM has no ghosts). */
function inferKind(branchedSpans: SpanOut[]): BranchKind {
  let sawFrozen = false;
  for (const s of branchedSpans) {
    const m = s.metadata;
    if (!m) continue;
    if (m.dry_run === true || m.replay === "stored_passthrough") return "server";
    if (m.replay === "frozen") sawFrozen = true;
  }
  return sawFrozen ? "sdk" : "unknown";
}

/**
 * Align a branched trace against its original, from the branch point onward.
 *
 * @param original  the trace the branch was forked from
 * @param branched  the branched/replayed trace (its `branched_from_span_id`
 *                  points at the edited span in `original`)
 */
export function alignFromBranch(
  original: TraceDetail,
  branched: TraceDetail,
): BranchDiff {
  const origSorted = byStart(original.spans);
  const newSorted = byStart(branched.spans);

  // Branch point in the original: the span whose id was edited.
  const branchSpanId = branched.branched_from_span_id;
  let branchIndex = branchSpanId
    ? origSorted.findIndex((s) => s.id === branchSpanId)
    : -1;

  // Branch point in the branched trace: the span carrying the marker. If the
  // marker is missing, fall back to the same positional index as the original.
  let newBranchIndex = newSorted.findIndex(isBranchPointSpan);
  if (newBranchIndex === -1) newBranchIndex = branchIndex;
  if (branchIndex === -1) branchIndex = newBranchIndex;

  const origTail = branchIndex >= 0 ? origSorted.slice(branchIndex) : origSorted;
  const newTail = newBranchIndex >= 0 ? newSorted.slice(newBranchIndex) : newSorted;

  const len = Math.max(origTail.length, newTail.length);
  const pairs: DiffPair[] = [];
  for (let i = 0; i < len; i++) {
    const o = origTail[i];
    const n = newTail[i];
    pairs.push({
      original: o,
      branched: n,
      isBranchPoint: i === 0 && branchIndex >= 0,
      changed: outputsDiffer(o, n),
    });
  }

  return {
    branchPointIndex: branchIndex,
    frozenCount: branchIndex >= 0 ? branchIndex : 0,
    pairs,
    tokenDelta: (branched.total_tokens ?? 0) - (original.total_tokens ?? 0),
    latencyDelta: (branched.duration_ms ?? 0) - (original.duration_ms ?? 0),
    costDelta:
      Number(branched.total_cost_usd ?? 0) - Number(original.total_cost_usd ?? 0),
    statusChanged: original.status !== branched.status,
    kind: inferKind(newSorted),
  };
}

import {
  CheckCircle2,
  XCircle,
  GitBranch,
  ArrowRight,
  Pencil,
  Zap,
  Coins,
  Clock,
} from "lucide-react";
import type { SpanOut, TraceDetail } from "@/lib/api";
import { alignFromBranch, type BranchKind, type DiffPair } from "@/lib/diff";
import { TypeBadge, MarkerBadges, StatusBadge } from "@/components/badges";
import { TextDiff } from "@/components/TextDiff";
import { CodeBlock } from "@/components/CodeBlock";
import { formatDuration, formatTokens, formatCost } from "@/lib/format";
import { cn } from "@/lib/utils";

// ── Trace summary card ───────────────────────────────────────────────────────

function TraceCard({ trace, label }: { trace: TraceDetail; label: string }) {
  return (
    <div className="min-w-0 flex-1 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-faint">
          {label}
        </p>
        <StatusBadge status={trace.status} />
      </div>
      <p className="truncate font-mono text-sm text-fg">
        {trace.name ?? trace.id.slice(0, 16)}
      </p>
      <p className="text-xs tabular-nums text-faint">
        {formatTokens(trace.total_tokens)} tokens · {formatCost(trace.total_cost_usd)} ·{" "}
        {formatDuration(trace.duration_ms)}
      </p>
    </div>
  );
}

/** The headline: did the branch fix or break the run? */
function StatusChangeBanner({
  original,
  branched,
}: {
  original: TraceDetail;
  branched: TraceDetail;
}) {
  if (original.status === branched.status) return null;

  const fixed = original.status === "error" && branched.status === "success";
  const broke = original.status === "success" && branched.status === "error";

  const cls = fixed
    ? "from-success/20 to-transparent border-success/30 text-success"
    : broke
      ? "from-error/20 to-transparent border-error/30 text-error"
      : "from-surface-2 to-transparent border-line text-muted";
  const Icon = fixed ? CheckCircle2 : broke ? XCircle : ArrowRight;
  const headline = fixed
    ? "Branch fixed the run"
    : broke
      ? "Branch broke the run"
      : "Status changed";

  return (
    <div className={cn("flex items-center gap-2.5 border-b bg-gradient-to-r px-4 py-3", cls)}>
      <Icon className="size-5 shrink-0" />
      <span className="text-sm font-semibold">{headline}</span>
      <span className="ml-1 font-mono text-xs opacity-80">
        {original.status} → {branched.status}
      </span>
    </div>
  );
}

function DeltaStat({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  unit: string;
}) {
  // Lower is better for tokens/cost/latency → drop = green.
  const node =
    value === 0 ? (
      <span className="text-faint">±0{unit}</span>
    ) : (
      <span className={value < 0 ? "text-success" : "text-error"}>
        {value > 0 ? "+" : ""}
        {value}
        {unit}
      </span>
    );
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-3.5 text-faint" />
      <span className="text-[10px] uppercase tracking-[0.12em] text-faint">{label}</span>
      <span className="font-mono text-sm tabular-nums">{node}</span>
    </div>
  );
}

function SpanPair({ pair, index }: { pair: DiffPair; index: number }) {
  const ref = pair.branched ?? pair.original;
  const type = ref?.type ?? "?";
  const name = ref?.name ?? "—";

  return (
    <div className="border-t border-line">
      {/* Pair header */}
      <div className="flex items-center gap-2 bg-surface-2/50 px-4 py-2">
        <span className="w-6 text-xs tabular-nums text-faint">#{index + 1}</span>
        <TypeBadge type={type} />
        <MarkerBadges meta={pair.branched?.metadata} />
        <span className="flex-1 truncate font-mono text-sm text-fg">{name}</span>
        <PairTag pair={pair} />
      </div>

      {/* Diff body */}
      <div className="p-4">
        <PairBody pair={pair} />
      </div>
    </div>
  );
}

function PairTag({ pair }: { pair: DiffPair }) {
  if (pair.isBranchPoint)
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-[0.1em] text-primary">
        <Pencil className="size-3" />
        edited
      </span>
    );
  if (pair.changed)
    return (
      <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-warning">
        changed
      </span>
    );
  return (
    <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-faint">
      same
    </span>
  );
}

function PairBody({ pair }: { pair: DiffPair }) {
  // Errors → just show them raw, side by side.
  if (pair.original?.error || pair.branched?.error) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <SideError span={pair.original} label="Original" />
        <SideError span={pair.branched} label="Branched" />
      </div>
    );
  }
  // Unchanged → collapse to a single muted block to reduce noise.
  if (!pair.changed && !pair.isBranchPoint) {
    return <CodeBlock data={pair.branched?.output ?? pair.original?.output} collapsedHeight={140} />;
  }
  return (
    <TextDiff
      original={pair.original?.output}
      modified={pair.branched?.output}
      originalLabel="Original output"
      modifiedLabel="Branched output"
    />
  );
}

function SideError({ span, label }: { span: SpanOut | undefined; label: string }) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">{label}</p>
      {span?.error ? (
        <CodeBlock data={span.error} isError collapsedHeight={160} />
      ) : (
        <CodeBlock data={span?.output} collapsedHeight={160} />
      )}
    </div>
  );
}

const KIND_LABEL: Record<BranchKind, string> = {
  sdk: "SDK-side replay · edit propagated through real tools",
  server: "Server-side branch · downstream tools dry-run (edit not propagated)",
  unknown: "Branch",
};

// ── Public export ───────────────────────────────────────────────────────────

export function BranchDiff({
  original,
  branched,
}: {
  original: TraceDetail;
  branched: TraceDetail;
}) {
  const diff = alignFromBranch(original, branched);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface/50">
      {/* Branch-kind label */}
      <div className="flex items-center gap-1.5 border-b border-line bg-primary-soft/20 px-4 py-2 text-xs">
        <GitBranch className="size-3.5 text-primary" />
        <span className="text-muted">{KIND_LABEL[diff.kind]}</span>
      </div>

      {/* Headline */}
      <StatusChangeBanner original={original} branched={branched} />

      {/* Trace summaries */}
      <div className="grid gap-4 border-b border-line p-4 sm:grid-cols-2 sm:divide-x sm:divide-line">
        <TraceCard trace={original} label="Original" />
        <div className="sm:pl-4">
          <TraceCard trace={branched} label="Branched" />
        </div>
      </div>

      {/* Trace-level deltas */}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-line bg-surface-2/40 px-4 py-3">
        <DeltaStat icon={Zap} label="Δ tokens" value={diff.tokenDelta} unit="" />
        <DeltaStat icon={Coins} label="Δ cost" value={parseFloat(diff.costDelta.toFixed(6))} unit="$" />
        <DeltaStat icon={Clock} label="Δ latency" value={diff.latencyDelta} unit="ms" />
      </div>

      {/* Frozen note */}
      {diff.frozenCount > 0 && (
        <p className="border-b border-line px-4 py-2 text-xs text-faint">
          {diff.frozenCount} span{diff.frozenCount > 1 ? "s" : ""} before the branch point{" "}
          {diff.frozenCount > 1 ? "are" : "is"} identical (frozen) — diff starts from the branch
          point. Frozen spans reuse the original&rsquo;s tokens/cost, so the deltas above reflect
          only re-run spans.
        </p>
      )}

      {/* Per-span diff */}
      {diff.pairs.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-faint">
          No spans to compare from the branch point.
        </p>
      ) : (
        diff.pairs.map((pair, i) => <SpanPair key={i} pair={pair} index={i} />)
      )}
    </div>
  );
}

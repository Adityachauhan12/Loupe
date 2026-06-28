import {
  CheckCircle2,
  XCircle,
  Repeat,
  Cpu,
  FileText,
  Zap,
  Coins,
  Clock,
} from "lucide-react";
import type { TraceDetail, SpanOut } from "@/lib/api";
import { StatusBadge } from "@/components/badges";
import { TextDiff } from "@/components/TextDiff";
import { formatDuration, formatTokens, formatCost } from "@/lib/format";
import { cn } from "@/lib/utils";

function llmSpans(trace: TraceDetail): SpanOut[] {
  return trace.spans
    .filter((s) => s.type === "llm")
    .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
}

function TraceCard({ trace, label }: { trace: TraceDetail; label: string }) {
  const llm = llmSpans(trace)[0];
  return (
    <div className="min-w-0 flex-1 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-faint">{label}</p>
        <StatusBadge status={trace.status} />
      </div>
      <p className="truncate font-mono text-sm text-fg">{trace.name ?? trace.id.slice(0, 16)}</p>
      {llm && (
        <p className="truncate font-mono text-xs text-faint">
          {llm.provider} / {llm.model}
        </p>
      )}
      <p className="text-xs tabular-nums text-faint">
        {formatTokens(trace.total_tokens)} tokens · {formatCost(trace.total_cost_usd)} ·{" "}
        {formatDuration(trace.duration_ms)}
      </p>
    </div>
  );
}

function StatusChangeBanner({
  original,
  replay,
}: {
  original: TraceDetail;
  replay: TraceDetail;
}) {
  if (original.status === replay.status) return null;
  const fixed = original.status === "error" && replay.status === "success";
  const broke = original.status === "success" && replay.status === "error";
  const cls = fixed
    ? "from-success/20 to-transparent border-success/30 text-success"
    : broke
      ? "from-error/20 to-transparent border-error/30 text-error"
      : "from-surface-2 to-transparent border-line text-muted";
  const Icon = fixed ? CheckCircle2 : broke ? XCircle : Repeat;
  const headline = fixed ? "Replay fixed the run" : broke ? "Replay broke the run" : "Status changed";
  return (
    <div className={cn("flex items-center gap-2.5 border-b bg-gradient-to-r px-4 py-3", cls)}>
      <Icon className="size-5 shrink-0" />
      <span className="text-sm font-semibold">{headline}</span>
      <span className="ml-1 font-mono text-xs opacity-80">
        {original.status} → {replay.status}
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

export function ReplayDiff({
  original,
  replay,
  modifications,
}: {
  original: TraceDetail;
  replay: TraceDetail;
  modifications: { prompt_override?: string | null; model_override?: string | null } | null;
}) {
  const origLLM = llmSpans(original);
  const repLLM = llmSpans(replay);
  const maxSpans = Math.max(origLLM.length, repLLM.length);

  const tokenDelta = (replay.total_tokens ?? 0) - (original.total_tokens ?? 0);
  const latencyDelta = (replay.duration_ms ?? 0) - (original.duration_ms ?? 0);
  const costDelta = Number(replay.total_cost_usd ?? 0) - Number(original.total_cost_usd ?? 0);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface/50">
      {/* Modifications banner */}
      {(modifications?.prompt_override || modifications?.model_override) && (
        <div className="space-y-1.5 border-b border-line bg-primary-soft/20 px-4 py-3 text-xs">
          {modifications.model_override && (
            <p className="flex items-center gap-2">
              <Cpu className="size-3.5 text-primary" />
              <span className="font-semibold text-primary">Model:</span>
              <span className="font-mono text-muted">{modifications.model_override}</span>
            </p>
          )}
          {modifications.prompt_override && (
            <p className="flex items-start gap-2">
              <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" />
              <span className="shrink-0 font-semibold text-primary">Prompt:</span>
              <span className="line-clamp-2 italic text-muted">
                {modifications.prompt_override}
              </span>
            </p>
          )}
        </div>
      )}

      <StatusChangeBanner original={original} replay={replay} />

      {/* Trace summaries */}
      <div className="grid gap-4 border-b border-line p-4 sm:grid-cols-2 sm:divide-x sm:divide-line">
        <TraceCard trace={original} label="Original" />
        <div className="sm:pl-4">
          <TraceCard trace={replay} label="Replay" />
        </div>
      </div>

      {/* Deltas */}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-line bg-surface-2/40 px-4 py-3">
        <DeltaStat icon={Zap} label="Δ tokens" value={tokenDelta} unit="" />
        <DeltaStat icon={Coins} label="Δ cost" value={parseFloat(costDelta.toFixed(6))} unit="$" />
        <DeltaStat icon={Clock} label="Δ latency" value={latencyDelta} unit="ms" />
      </div>

      {/* LLM output diffs */}
      {maxSpans === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-faint">No LLM spans to compare.</p>
      ) : (
        Array.from({ length: maxSpans }).map((_, i) => {
          const o = origLLM[i];
          const r = repLLM[i];
          return (
            <div key={i} className="border-t border-line p-4">
              {maxSpans > 1 && (
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">
                  LLM output #{i + 1}
                </p>
              )}
              <TextDiff
                original={r?.error ?? o?.error ?? o?.output}
                modified={r?.error ?? r?.output}
                originalLabel="Original output"
                modifiedLabel="Replay output"
              />
            </div>
          );
        })
      )}
    </div>
  );
}

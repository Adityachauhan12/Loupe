import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Clock,
  Zap,
  Coins,
  Layers,
  GitBranch,
  AlertTriangle,
  Play,
  ArrowRight,
} from "lucide-react";
import { getTrace, TraceDetail, SpanOut } from "@/lib/api";
import { SpanTree } from "@/components/SpanTree";
import { ReplayForm } from "@/components/ReplayForm";
import { AutoRefresh } from "@/components/AutoRefresh";
import { TopBar } from "@/components/TopBar";
import { StatusBadge, BranchBadge, ReplayBadge } from "@/components/badges";
import { CodeBlock } from "@/components/CodeBlock";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui/button";
import { SectionLabel } from "@/components/ui/card";
import { formatDate, formatDuration, formatTokens, formatCost } from "@/lib/format";

export default async function TraceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let trace: TraceDetail;
  try {
    trace = await getTrace(id);
  } catch (err) {
    console.error("Failed to fetch trace:", err);
    notFound();
  }

  const { model, systemPrompt } = extractLlmContext(trace.spans);

  return (
    <div className="min-h-dvh">
      <TopBar
        back={{ label: "Traces", href: "/" }}
        crumbs={[{ label: trace.name ?? trace.id.slice(0, 12) }]}
        right={
          <>
            <StatusBadge status={trace.status} />
            {trace.branched_from_trace_id ? (
              <BranchBadge />
            ) : (
              trace.is_replay && <ReplayBadge />
            )}
            {!trace.is_replay && (
              <Link href="#replay">
                <Button size="sm" className="ml-1">
                  <Play className="size-3.5" />
                  Replay
                </Button>
              </Link>
            )}
          </>
        }
      />

      <main className="mx-auto w-full max-w-6xl space-y-6 px-5 py-7">
        {trace.status === "running" && <AutoRefresh intervalMs={2500} />}

        {/* Branch lineage */}
        {trace.branched_from_trace_id && (
          <Reveal className="flex flex-wrap items-center gap-3 rounded-xl border border-primary-strong/30 bg-primary-soft/20 px-4 py-3 text-sm">
            <span className="inline-flex items-center gap-1.5 font-medium text-primary">
              <GitBranch className="size-4" />
              Branched run
            </span>
            <span className="text-faint">·</span>
            <Link
              href={`/traces/${trace.branched_from_trace_id}`}
              className="text-muted transition-colors hover:text-fg"
            >
              View original trace
            </Link>
            <Link
              href={`/traces/${trace.id}/diff`}
              className="ml-auto inline-flex items-center gap-1 font-medium text-primary transition-colors hover:text-accent"
            >
              View diff
              <ArrowRight className="size-4" />
            </Link>
          </Reveal>
        )}

        {/* Hero + meta cards */}
        <Reveal>
          <h1 className="font-mono text-lg font-semibold text-fg">
            {trace.name ?? trace.id.slice(0, 24)}
          </h1>
          <p className="mt-0.5 text-xs text-faint">{formatDate(trace.started_at, { withSeconds: true })}</p>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard icon={Clock} label="Duration" value={formatDuration(trace.duration_ms)} />
            <StatCard icon={Zap} label="Tokens" value={formatTokens(trace.total_tokens)} />
            <StatCard icon={Coins} label="Cost" value={formatCost(trace.total_cost_usd)} />
            <StatCard icon={Layers} label="Spans" value={String(trace.spans.length)} />
          </div>
        </Reveal>

        {/* Error callout — the "spot the bug" moment */}
        {trace.error && (
          <Reveal className="overflow-hidden rounded-xl border border-error/30 bg-error-dim/25">
            <div className="flex items-center gap-2 border-b border-error/20 px-4 py-2.5 text-sm font-medium text-error">
              <AlertTriangle className="size-4" />
              This run failed
            </div>
            <div className="p-4">
              <CodeBlock data={trace.error} isError />
            </div>
          </Reveal>
        )}

        {/* Input / Output */}
        {(trace.input || trace.output) && (
          <Reveal className="grid gap-4 lg:grid-cols-2">
            {trace.input && (
              <div className="space-y-2">
                <SectionLabel>Trace input</SectionLabel>
                <CodeBlock data={trace.input} />
              </div>
            )}
            {trace.output && (
              <div className="space-y-2">
                <SectionLabel>Trace output</SectionLabel>
                <CodeBlock data={trace.output} />
              </div>
            )}
          </Reveal>
        )}

        {/* Span tree */}
        <Reveal className="space-y-3">
          <SectionLabel>Spans ({trace.spans.length})</SectionLabel>
          <SpanTree
            spans={trace.spans}
            totalMs={trace.duration_ms}
            traceId={trace.id}
            replayHref={!trace.is_replay ? "#replay" : undefined}
          />
        </Reveal>

        {/* Replay */}
        {!trace.is_replay && (
          <Reveal
            id="replay"
            className="scroll-mt-20 overflow-hidden rounded-xl border border-line bg-surface/70"
          >
            <div className="flex items-center gap-2 border-b border-line bg-surface-2/60 px-5 py-3">
              <Play className="size-4 text-primary" />
              <h2 className="text-sm font-semibold text-fg">Replay this trace</h2>
              <span className="text-xs text-faint">
                — change the prompt or model, re-run, and diff the output
              </span>
            </div>
            <div className="p-5">
              <ReplayForm
                traceId={trace.id}
                currentModel={model}
                currentPrompt={systemPrompt}
              />
            </div>
          </Reveal>
        )}
      </main>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface/60 p-3.5 transition-colors hover:border-line-strong">
      <div className="flex items-center gap-1.5 text-faint">
        <Icon className="size-3.5" />
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em]">
          {label}
        </span>
      </div>
      <p className="mt-1.5 font-mono text-lg tabular-nums text-fg">{value}</p>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Best-effort: pull the model + system prompt from the first LLM span so the
 *  replay form can show what you're about to override (no more blind edits). */
function extractLlmContext(spans: SpanOut[]): {
  model: string | null;
  systemPrompt: string | null;
} {
  const llm = spans
    .filter((s) => s.type === "llm")
    .sort(
      (a, b) =>
        new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
    )[0];
  if (!llm) return { model: null, systemPrompt: null };

  const input = llm.input as Record<string, unknown> | null;
  let systemPrompt: string | null = null;
  if (input) {
    if (typeof input.system === "string") {
      systemPrompt = input.system;
    } else if (Array.isArray(input.messages)) {
      const sys = (input.messages as Array<Record<string, unknown>>).find(
        (m) => m.role === "system",
      );
      if (sys && typeof sys.content === "string") systemPrompt = sys.content;
    }
  }
  return { model: llm.model, systemPrompt };
}

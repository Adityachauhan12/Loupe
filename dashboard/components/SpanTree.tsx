"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, AlertTriangle, CornerDownRight, ArrowRight } from "lucide-react";
import type { SpanOut } from "@/lib/api";
import { BranchEditor } from "@/components/BranchEditor";
import { TypeBadge, MarkerBadges } from "@/components/badges";
import { CodeBlock } from "@/components/CodeBlock";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

// ── Tree building ──────────────────────────────────────────────────────────

interface SpanNode {
  span: SpanOut;
  children: SpanNode[];
}

function buildTree(spans: SpanOut[]): SpanNode[] {
  const byId = new Map<string, SpanNode>();
  spans.forEach((s) => byId.set(s.id, { span: s, children: [] }));

  const roots: SpanNode[] = [];
  spans.forEach((s) => {
    const node = byId.get(s.id)!;
    if (s.parent_span_id == null) {
      roots.push(node);
    } else {
      const parent = byId.get(s.parent_span_id);
      if (parent) parent.children.push(node);
      else roots.push(node); // orphan → treat as root
    }
  });
  return roots;
}

const BAR_COLOR: Record<string, string> = {
  llm: "bg-llm",
  tool: "bg-tool",
  function: "bg-fn",
  retrieval: "bg-retrieval",
};

function spanMarkers(meta: Record<string, unknown> | null) {
  return {
    isBranchPoint: meta?.branch_point === true,
    isDryRun: meta?.dry_run === true,
    isPassthrough: meta?.replay === "stored_passthrough",
  };
}

// ── Components ─────────────────────────────────────────────────────────────

function DurationBar({
  ms,
  totalMs,
  type,
}: {
  ms: number | null;
  totalMs: number | null;
  type: string;
}) {
  if (!ms || !totalMs) return <div className="hidden w-20 sm:block" />;
  const pct = Math.max(2, Math.min(100, (ms / totalMs) * 100));
  return (
    <div className="hidden h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-surface-2 sm:block">
      <div
        className={cn("h-full rounded-full", BAR_COLOR[type] ?? "bg-fn")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function SpanRow({
  node,
  depth,
  totalMs,
  traceId,
  maxStart,
  replayHref,
  expanded,
  onToggle,
}: {
  node: SpanNode;
  depth: number;
  totalMs: number | null;
  traceId: string;
  maxStart: number;
  replayHref?: string;
  expanded: Set<string>;
  onToggle: (id: string) => void;
}) {
  const { span, children } = node;
  const isExpanded = expanded.has(span.id);
  const hasDetail = !!(span.input || span.output || span.error);
  const hasError = !!span.error;
  const { isDryRun, isBranchPoint } = spanMarkers(span.metadata);
  // Branching only matters when something runs after this span.
  const canBranch = new Date(span.started_at).getTime() < maxStart;

  return (
    <div>
      {/* Row */}
      <div
        role={hasDetail ? "button" : undefined}
        tabIndex={hasDetail ? 0 : undefined}
        aria-expanded={hasDetail ? isExpanded : undefined}
        onClick={() => hasDetail && onToggle(span.id)}
        onKeyDown={(e) => {
          if (hasDetail && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onToggle(span.id);
          }
        }}
        style={{ paddingLeft: `${depth * 18 + 12}px` }}
        className={cn(
          "flex items-center gap-2 border-b border-line/50 py-2 pr-3 transition-colors",
          hasDetail && "cursor-pointer hover:bg-surface-2/60 focus-visible:bg-surface-2/60",
          hasError && "bg-error-dim/15 hover:bg-error-dim/25",
          isBranchPoint && "bg-primary-soft/15",
        )}
      >
        <ChevronRight
          className={cn(
            "size-3.5 shrink-0 text-faint transition-transform",
            !hasDetail && "opacity-0",
            isExpanded && "rotate-90",
          )}
        />

        <TypeBadge type={span.type} />
        <MarkerBadges meta={span.metadata} />
        {hasError && <AlertTriangle className="size-3.5 shrink-0 text-error" />}

        <span
          className={cn(
            "flex-1 truncate font-mono text-sm",
            hasError ? "text-error" : isDryRun ? "italic text-faint" : "text-fg",
          )}
        >
          {span.name}
        </span>

        {span.total_tokens != null && (
          <span className="hidden shrink-0 text-xs tabular-nums text-faint sm:inline">
            {span.total_tokens} tok
          </span>
        )}
        {span.cost_usd != null && (
          <span className="hidden shrink-0 font-mono text-xs tabular-nums text-faint md:inline">
            ${Number(span.cost_usd).toFixed(4)}
          </span>
        )}

        <DurationBar ms={span.duration_ms} totalMs={totalMs} type={span.type} />
        <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-muted">
          {formatDuration(span.duration_ms)}
        </span>
      </div>

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden border-b border-line/50 bg-bg/40"
          >
            <div
              className="space-y-3 py-3 pr-4"
              style={{ paddingLeft: `${depth * 18 + 38}px` }}
            >
              {span.model && (
                <p className="text-[11px] text-muted">
                  <span className="text-faint">{span.provider} / </span>
                  <span className="font-mono">{span.model}</span>
                  {span.prompt_tokens != null && (
                    <span className="ml-2 text-faint">
                      {span.prompt_tokens} in + {span.completion_tokens} out
                    </span>
                  )}
                </p>
              )}
              {span.input && (
                <Detail label="Input">
                  <CodeBlock data={span.input} collapsedHeight={180} />
                </Detail>
              )}
              {span.output && (
                <Detail label="Output">
                  <CodeBlock data={span.output} collapsedHeight={180} />
                </Detail>
              )}
              {span.error && (
                <Detail label="Error" error>
                  <CodeBlock data={span.error} isError collapsedHeight={180} />
                </Detail>
              )}

              {!isDryRun &&
                (canBranch ? (
                  <BranchEditor traceId={traceId} span={span} />
                ) : (
                  <TerminalHint replayHref={replayHref} />
                ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Children */}
      {children.map((child) => (
        <SpanRow
          key={child.span.id}
          node={child}
          depth={depth + 1}
          totalMs={totalMs}
          traceId={traceId}
          maxStart={maxStart}
          replayHref={replayHref}
          expanded={expanded}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

/** Shown on terminal spans: editing their output changes nothing downstream,
 *  so we point the user at Replay (which re-runs from a new prompt/model). */
function TerminalHint({ replayHref }: { replayHref?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface-2/50 px-3 py-2 text-[11px] text-faint">
      <CornerDownRight className="size-3.5 shrink-0" />
      <span>Nothing runs after this span — editing its output changes nothing.</span>
      {replayHref && (
        <Link
          href={replayHref}
          className="inline-flex items-center gap-1 font-medium text-primary transition-colors hover:text-accent"
        >
          Replay with a new prompt
          <ArrowRight className="size-3" />
        </Link>
      )}
    </div>
  );
}

function Detail({
  label,
  error,
  children,
}: {
  label: string;
  error?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <p
        className={cn(
          "text-[10px] font-semibold uppercase tracking-[0.12em]",
          error ? "text-error" : "text-faint",
        )}
      >
        {label}
      </p>
      {children}
    </div>
  );
}

// ── Public export ──────────────────────────────────────────────────────────

export function SpanTree({
  spans,
  totalMs,
  traceId,
  replayHref,
}: {
  spans: SpanOut[];
  totalMs: number | null;
  traceId: string;
  /** Anchor to the replay form, shown to terminal spans where branching is a no-op. */
  replayHref?: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const onToggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const roots = buildTree(spans);

  // A span is branchable only if something executes *after* it — editing the
  // output of a terminal span (the last thing to run) changes nothing downstream.
  const maxStart = Math.max(
    0,
    ...spans.map((s) => new Date(s.started_at).getTime()),
  );

  if (roots.length === 0) {
    return (
      <div className="rounded-xl border border-line bg-surface/60 py-10 text-center text-sm text-faint">
        No spans recorded.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface/50">
      {/* Header row */}
      <div className="flex items-center gap-2 border-b border-line bg-surface-2/60 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">
        <span className="w-3.5" />
        <span>Span</span>
        <span className="flex-1" />
        <span className="hidden w-20 sm:inline">Latency</span>
        <span className="w-14 text-right">Time</span>
      </div>

      {roots.map((node) => (
        <SpanRow
          key={node.span.id}
          node={node}
          depth={0}
          totalMs={totalMs}
          traceId={traceId}
          maxStart={maxStart}
          replayHref={replayHref}
          expanded={expanded}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

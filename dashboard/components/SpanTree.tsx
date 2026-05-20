"use client";

import { useState, useCallback } from "react";
import type { SpanOut } from "@/lib/api";

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

// ── Utilities ──────────────────────────────────────────────────────────────

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

const TYPE_STYLES: Record<string, string> = {
  llm: "bg-purple-900/60 text-purple-300",
  tool: "bg-blue-900/60 text-blue-300",
  function: "bg-gray-700 text-gray-300",
  retrieval: "bg-amber-900/60 text-amber-300",
};

const TYPE_LABELS: Record<string, string> = {
  llm: "llm",
  tool: "tool",
  function: "fn",
  retrieval: "ret",
};

// ── Components ─────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  const cls = TYPE_STYLES[type] ?? "bg-gray-700 text-gray-300";
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold shrink-0 ${cls}`}>
      {TYPE_LABELS[type] ?? type}
    </span>
  );
}

function DurationBar({
  ms,
  totalMs,
}: {
  ms: number | null;
  totalMs: number | null;
}) {
  if (!ms || !totalMs) return <div className="w-20" />;
  const pct = Math.min(100, (ms / totalMs) * 100);
  return (
    <div className="w-20 h-1.5 rounded-full bg-gray-800 shrink-0">
      <div
        className="h-full rounded-full bg-gray-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function JsonBlock({
  label,
  data,
  isError,
}: {
  label: string;
  data: Record<string, unknown>;
  isError?: boolean;
}) {
  return (
    <div className="mt-1">
      <span className={`text-[10px] font-semibold uppercase tracking-widest ${isError ? "text-red-500" : "text-gray-600"}`}>
        {label}
      </span>
      <pre className={`mt-1 text-xs rounded p-2 overflow-x-auto whitespace-pre-wrap break-words max-h-48 overflow-y-auto ${isError ? "bg-red-950/40 text-red-300" : "bg-gray-900 text-gray-300"}`}>
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

function SpanRow({
  node,
  depth,
  totalMs,
  expanded,
  onToggle,
}: {
  node: SpanNode;
  depth: number;
  totalMs: number | null;
  expanded: Set<string>;
  onToggle: (id: string) => void;
}) {
  const { span, children } = node;
  const isExpanded = expanded.has(span.id);
  const hasDetail = !!(span.input || span.output || span.error);

  return (
    <div>
      {/* Row */}
      <div
        onClick={() => hasDetail && onToggle(span.id)}
        className={`flex items-center gap-2 py-2 pr-4 border-b border-gray-800/50 transition-colors ${hasDetail ? "cursor-pointer hover:bg-gray-900/60" : ""}`}
        style={{ paddingLeft: `${depth * 20 + 12}px` }}
      >
        {/* Expand indicator */}
        <span className="text-gray-700 text-xs w-3 shrink-0">
          {hasDetail ? (isExpanded ? "▾" : "▸") : " "}
        </span>

        <TypeBadge type={span.type} />

        <span className="font-mono text-sm text-gray-200 truncate flex-1">
          {span.name}
        </span>

        {/* LLM tokens / cost */}
        {span.total_tokens != null && (
          <span className="text-xs text-gray-500 tabular-nums shrink-0">
            {span.total_tokens} tok
          </span>
        )}
        {span.cost_usd != null && (
          <span className="text-xs text-gray-600 tabular-nums font-mono shrink-0">
            ${Number(span.cost_usd).toFixed(4)}
          </span>
        )}

        {/* Duration bar + label */}
        <DurationBar ms={span.duration_ms} totalMs={totalMs} />
        <span className="text-xs text-gray-500 tabular-nums font-mono w-14 text-right shrink-0">
          {span.duration_ms != null ? formatDuration(span.duration_ms) : "—"}
        </span>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div
          className="pb-3 border-b border-gray-800/50"
          style={{ paddingLeft: `${depth * 20 + 12 + 28}px`, paddingRight: "16px" }}
        >
          {span.model && (
            <p className="text-[11px] text-gray-500 mt-1">
              {span.provider} / {span.model}
              {span.prompt_tokens != null && (
                <span className="ml-2">
                  {span.prompt_tokens} in + {span.completion_tokens} out
                </span>
              )}
            </p>
          )}
          {span.input && <JsonBlock label="Input" data={span.input} />}
          {span.output && <JsonBlock label="Output" data={span.output} />}
          {span.error && <JsonBlock label="Error" data={span.error} isError />}
        </div>
      )}

      {/* Children */}
      {children.map((child) => (
        <SpanRow
          key={child.span.id}
          node={child}
          depth={depth + 1}
          totalMs={totalMs}
          expanded={expanded}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

// ── Public export ──────────────────────────────────────────────────────────

export function SpanTree({
  spans,
  totalMs,
}: {
  spans: SpanOut[];
  totalMs: number | null;
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

  if (roots.length === 0) {
    return <p className="text-gray-600 text-sm py-4">No spans recorded.</p>;
  }

  return (
    <div className="rounded border border-gray-800 overflow-hidden">
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-900 border-b border-gray-800 text-[10px] text-gray-600 uppercase tracking-widest font-semibold">
        <span className="w-3" />
        <span className="w-12">Type</span>
        <span className="flex-1">Name</span>
        <span className="w-16 text-right">Tokens</span>
        <span className="w-16 text-right">Cost</span>
        <span className="w-20">Bar</span>
        <span className="w-14 text-right">Duration</span>
      </div>

      {roots.map((node) => (
        <SpanRow
          key={node.span.id}
          node={node}
          depth={0}
          totalMs={totalMs}
          expanded={expanded}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

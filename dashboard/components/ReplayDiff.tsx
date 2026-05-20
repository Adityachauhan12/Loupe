import type { TraceDetail, SpanOut } from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
}

function delta(n: number, unit: string, invert = false): React.ReactNode {
  if (n === 0) return <span className="text-gray-500">±0{unit}</span>;
  const negative = invert ? n > 0 : n < 0;
  const sign = n > 0 ? "+" : "";
  return (
    <span className={negative ? "text-green-400" : "text-red-400"}>
      {sign}{n}{unit}
    </span>
  );
}

function pct(a: number, b: number): string {
  if (b === 0) return "";
  const p = Math.round(((a - b) / b) * 100);
  return ` (${p > 0 ? "+" : ""}${p}%)`;
}

function llmSpans(trace: TraceDetail): SpanOut[] {
  return trace.spans
    .filter((s) => s.type === "llm")
    .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
}

// ── Sub-components ─────────────────────────────────────────────────────────

function TraceCard({ trace, label }: { trace: TraceDetail; label: string }) {
  const statusColor: Record<string, string> = {
    success: "text-green-400",
    error: "text-red-400",
    running: "text-amber-400",
  };

  const llm = llmSpans(trace);
  const model = llm[0]?.model ?? "—";
  const provider = llm[0]?.provider ?? "—";

  return (
    <div className="flex-1 min-w-0">
      <p className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold mb-2">
        {label}
      </p>
      <div className="space-y-1 text-sm">
        <p className="font-mono text-gray-300 truncate">{trace.name ?? trace.id.slice(0, 16)}</p>
        <p>
          <span className={statusColor[trace.status ?? ""] ?? "text-gray-400"}>
            {trace.status ?? "unknown"}
          </span>
          {trace.duration_ms != null && (
            <span className="text-gray-500 ml-2">{fmt(trace.duration_ms)}</span>
          )}
        </p>
        <p className="text-gray-500 text-xs font-mono">{provider} / {model}</p>
        <p className="text-gray-500 text-xs tabular-nums">
          {trace.total_tokens != null ? `${trace.total_tokens.toLocaleString()} tokens` : "—"}
          {trace.total_cost_usd != null && (
            <span className="ml-2">${Number(trace.total_cost_usd).toFixed(4)}</span>
          )}
        </p>
      </div>
    </div>
  );
}

function DeltaRow({
  original,
  replay,
}: {
  original: TraceDetail;
  replay: TraceDetail;
}) {
  const tokDelta = (replay.total_tokens ?? 0) - (original.total_tokens ?? 0);
  const latDelta = (replay.duration_ms ?? 0) - (original.duration_ms ?? 0);
  const costDelta =
    Number(replay.total_cost_usd ?? 0) - Number(original.total_cost_usd ?? 0);

  return (
    <div className="flex flex-wrap gap-6 px-4 py-3 bg-gray-900/60 border-y border-gray-800 text-sm">
      <div>
        <span className="text-gray-600 text-xs uppercase tracking-widest mr-2">Δ tokens</span>
        {delta(tokDelta, "", true)}
        <span className="text-gray-600 text-xs ml-1">
          {pct(replay.total_tokens ?? 0, original.total_tokens ?? 1)}
        </span>
      </div>
      <div>
        <span className="text-gray-600 text-xs uppercase tracking-widest mr-2">Δ cost</span>
        {delta(parseFloat(costDelta.toFixed(6)), "$", true)}
      </div>
      <div>
        <span className="text-gray-600 text-xs uppercase tracking-widest mr-2">Δ latency</span>
        {delta(latDelta, "ms", true)}
        <span className="text-gray-600 text-xs ml-1">
          {pct(replay.duration_ms ?? 0, original.duration_ms ?? 1)}
        </span>
      </div>
    </div>
  );
}

function OutputBlock({ span }: { span: SpanOut | undefined }) {
  if (!span)
    return <p className="text-gray-700 text-xs italic">No LLM span</p>;

  const content =
    (span.output?.content as string | undefined) ??
    JSON.stringify(span.output, null, 2);

  if (span.error) {
    return (
      <pre className="text-xs text-red-400 bg-red-950/30 rounded p-3 whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
        {JSON.stringify(span.error, null, 2)}
      </pre>
    );
  }

  return (
    <pre className="text-xs text-gray-300 bg-gray-900 rounded p-3 whitespace-pre-wrap break-words max-h-64 overflow-y-auto border border-gray-800">
      {content}
    </pre>
  );
}

// ── Public export ──────────────────────────────────────────────────────────

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

  return (
    <div className="rounded border border-gray-800 overflow-hidden">
      {/* Modifications banner */}
      {(modifications?.prompt_override || modifications?.model_override) && (
        <div className="px-4 py-3 bg-indigo-950/40 border-b border-indigo-900/40 text-xs space-y-1">
          {modifications.model_override && (
            <p>
              <span className="text-indigo-400 font-semibold">Model override: </span>
              <span className="font-mono text-gray-300">{modifications.model_override}</span>
            </p>
          )}
          {modifications.prompt_override && (
            <p>
              <span className="text-indigo-400 font-semibold">Prompt override: </span>
              <span className="text-gray-300 italic truncate">
                {modifications.prompt_override.slice(0, 120)}
                {modifications.prompt_override.length > 120 ? "…" : ""}
              </span>
            </p>
          )}
        </div>
      )}

      {/* Header row */}
      <div className="grid grid-cols-2 divide-x divide-gray-800 border-b border-gray-800">
        <div className="p-4">
          <TraceCard trace={original} label="Original" />
        </div>
        <div className="p-4">
          <TraceCard trace={replay} label="Replay" />
        </div>
      </div>

      {/* Delta summary */}
      <DeltaRow original={original} replay={replay} />

      {/* LLM output pairs */}
      {maxSpans === 0 ? (
        <p className="text-gray-600 text-sm px-4 py-6 text-center">No LLM spans to compare.</p>
      ) : (
        Array.from({ length: maxSpans }).map((_, i) => (
          <div key={i} className="grid grid-cols-2 divide-x divide-gray-800 border-t border-gray-800">
            <div className="p-4">
              <p className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold mb-2">
                LLM output {maxSpans > 1 ? `#${i + 1}` : ""}
              </p>
              <OutputBlock span={origLLM[i]} />
            </div>
            <div className="p-4">
              <p className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold mb-2">
                LLM output {maxSpans > 1 ? `#${i + 1}` : ""}
              </p>
              <OutputBlock span={repLLM[i]} />
            </div>
          </div>
        ))
      )}
    </div>
  );
}

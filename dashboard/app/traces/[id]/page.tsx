
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTrace, TraceDetail } from "@/lib/api";
import { SpanTree } from "@/components/SpanTree";
import { ReplayForm } from "@/components/ReplayForm";

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

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <Link href="/" className="text-gray-500 hover:text-gray-200 transition-colors text-sm">
          ← Traces
        </Link>
        <span className="text-gray-700">/</span>
        <span className="font-mono text-sm text-gray-300">
          {trace.name ?? trace.id.slice(0, 16)}
        </span>
        <StatusBadge status={trace.status} />
        {trace.is_replay && (
          <span className="text-xs text-purple-400 font-medium">replay</span>
        )}
      </header>

      <main className="flex-1 px-6 py-6 max-w-5xl mx-auto w-full space-y-6">
        {/* Meta row */}
        <MetaRow trace={trace} />

        {/* Input / Output */}
        {(trace.input || trace.output || trace.error) && (
          <section className="space-y-3">
            {trace.input && (
              <JsonSection label="Trace Input" data={trace.input} />
            )}
            {trace.output && (
              <JsonSection label="Trace Output" data={trace.output} />
            )}
            {trace.error && (
              <JsonSection label="Error" data={trace.error} isError />
            )}
          </section>
        )}

        {/* Span tree */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Spans ({trace.spans.length})
          </h2>
          <SpanTree spans={trace.spans} totalMs={trace.duration_ms} />
        </section>

        {/* Replay */}
        {!trace.is_replay && (
          <section className="border border-gray-800 rounded p-5">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest mb-4">
              Replay this trace
            </h2>
            <ReplayForm traceId={trace.id} />
          </section>
        )}
      </main>
    </div>
  );
}

// ── Sub-components (server-rendered) ───────────────────────────────────────

function MetaRow({ trace }: { trace: TraceDetail }) {
  const metaItems = [
    { label: "Started", value: formatDate(trace.started_at) },
    {
      label: "Duration",
      value: trace.duration_ms != null ? formatDuration(trace.duration_ms) : "—",
    },
    {
      label: "Tokens",
      value: trace.total_tokens != null ? trace.total_tokens.toLocaleString() : "—",
    },
    {
      label: "Cost",
      value:
        trace.total_cost_usd != null
          ? `$${Number(trace.total_cost_usd).toFixed(4)}`
          : "—",
    },
    { label: "Spans", value: String(trace.spans.length) },
  ];

  return (
    <div className="flex flex-wrap gap-6">
      {metaItems.map(({ label, value }) => (
        <div key={label}>
          <p className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold">
            {label}
          </p>
          <p className="text-sm text-gray-200 font-mono tabular-nums mt-0.5">{value}</p>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  const styles: Record<string, string> = {
    success: "bg-green-900/50 text-green-400",
    error: "bg-red-900/50 text-red-400",
    running: "bg-amber-900/50 text-amber-400",
  };
  const cls = styles[status ?? ""] ?? "bg-gray-800 text-gray-400";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status ?? "unknown"}
    </span>
  );
}

function JsonSection({
  label,
  data,
  isError,
}: {
  label: string;
  data: Record<string, unknown>;
  isError?: boolean;
}) {
  return (
    <div>
      <p className={`text-[10px] font-semibold uppercase tracking-widest mb-1 ${isError ? "text-red-500" : "text-gray-600"}`}>
        {label}
      </p>
      <pre className={`text-xs rounded p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-64 overflow-y-auto ${isError ? "bg-red-950/40 text-red-300 border border-red-900/40" : "bg-gray-900 text-gray-300 border border-gray-800"}`}>
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

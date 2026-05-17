import Link from "next/link";
import { getTraces, TraceListItem } from "@/lib/api";

const LIMIT = 20;

const STATUS_FILTERS = [
  { label: "All", value: undefined },
  { label: "Success", value: "success" },
  { label: "Error", value: "error" },
  { label: "Running", value: "running" },
] as const;

export default async function TracesPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string; status?: string }>;
}) {
  const { offset: offsetStr, status } = await searchParams;
  const offset = Math.max(0, Number(offsetStr ?? 0));

  let data;
  try {
    data = await getTraces({ limit: LIMIT, offset, status });
  } catch {
    return (
      <Shell status={status}>
        <p className="text-red-400 text-sm py-12 text-center">
          Could not reach the Loupe server. Is it running?
        </p>
      </Shell>
    );
  }

  return (
    <Shell status={status}>
      {data.items.length === 0 ? (
        <p className="text-gray-500 text-sm py-12 text-center">No traces yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-800">
              <th className="pb-3 pr-4 font-medium">Name</th>
              <th className="pb-3 pr-4 font-medium">Status</th>
              <th className="pb-3 pr-4 font-medium">Started</th>
              <th className="pb-3 pr-4 font-medium">Duration</th>
              <th className="pb-3 pr-4 font-medium">Tokens</th>
              <th className="pb-3 pr-4 font-medium">Cost</th>
              <th className="pb-3 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {data.items.map((t) => (
              <TraceRow key={t.id} trace={t} />
            ))}
          </tbody>
        </table>
      )}

      <Pagination offset={offset} limit={LIMIT} hasMore={data.has_more} status={status} />
    </Shell>
  );
}

function Shell({
  children,
  status,
}: {
  children: React.ReactNode;
  status?: string;
}) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-6">
        <span className="font-semibold tracking-tight text-white">Loupe</span>
        <nav className="flex gap-1">
          {STATUS_FILTERS.map((f) => {
            const active = (f.value ?? "") === (status ?? "");
            return (
              <Link
                key={f.label}
                href={f.value ? `/?status=${f.value}` : "/"}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  active
                    ? "bg-gray-700 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {f.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="flex-1 px-6 py-6 max-w-6xl mx-auto w-full">
        <h1 className="text-xl font-bold mb-6">Traces</h1>
        {children}
      </main>
    </div>
  );
}

function TraceRow({ trace: t }: { trace: TraceListItem }) {
  return (
    <tr className="hover:bg-gray-900/50 transition-colors group">
      <td className="py-3 pr-4">
        <Link
          href={`/traces/${t.id}`}
          className="font-mono text-gray-200 group-hover:text-white transition-colors"
        >
          {t.name ?? t.id.slice(0, 8)}
        </Link>
        {t.is_replay && (
          <span className="ml-2 text-xs text-purple-400 font-medium">replay</span>
        )}
      </td>
      <td className="py-3 pr-4">
        <StatusBadge status={t.status} />
      </td>
      <td className="py-3 pr-4 text-gray-400 tabular-nums">{formatDate(t.started_at)}</td>
      <td className="py-3 pr-4 text-gray-400 tabular-nums font-mono">
        {t.duration_ms != null ? formatDuration(t.duration_ms) : "—"}
      </td>
      <td className="py-3 pr-4 text-gray-400 tabular-nums">
        {t.total_tokens != null ? t.total_tokens.toLocaleString() : "—"}
      </td>
      <td className="py-3 pr-4 text-gray-400 tabular-nums font-mono">
        {t.total_cost_usd != null ? `$${Number(t.total_cost_usd).toFixed(4)}` : "—"}
      </td>
      <td className="py-3">
        <Link
          href={`/traces/${t.id}`}
          className="text-xs text-gray-600 hover:text-gray-300 transition-colors"
        >
          →
        </Link>
      </td>
    </tr>
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

function Pagination({
  offset,
  limit,
  hasMore,
  status,
}: {
  offset: number;
  limit: number;
  hasMore: boolean;
  status?: string;
}) {
  const statusParam = status ? `&status=${status}` : "";
  const page = Math.floor(offset / limit) + 1;

  return (
    <div className="mt-6 flex items-center gap-4 text-sm">
      {offset > 0 ? (
        <Link
          href={`/?offset=${offset - limit}${statusParam}`}
          className="px-3 py-1 rounded border border-gray-700 text-gray-300 hover:border-gray-500 transition-colors"
        >
          ← Prev
        </Link>
      ) : (
        <span className="px-3 py-1 rounded border border-gray-800 text-gray-700 cursor-not-allowed">
          ← Prev
        </span>
      )}

      <span className="text-gray-500">Page {page}</span>

      {hasMore ? (
        <Link
          href={`/?offset=${offset + limit}${statusParam}`}
          className="px-3 py-1 rounded border border-gray-700 text-gray-300 hover:border-gray-500 transition-colors"
        >
          Next →
        </Link>
      ) : (
        <span className="px-3 py-1 rounded border border-gray-800 text-gray-700 cursor-not-allowed">
          Next →
        </span>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

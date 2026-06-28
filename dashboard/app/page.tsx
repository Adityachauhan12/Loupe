import Link from "next/link";
import {
  List,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Inbox,
  type LucideIcon,
} from "lucide-react";
import { getTraces, TraceListItem } from "@/lib/api";
import { TopBar } from "@/components/TopBar";
import { StatusBadge, BranchBadge, ReplayBadge } from "@/components/badges";
import { Reveal, MotionRow } from "@/components/motion";
import { Button } from "@/components/ui/button";
import { formatDate, formatDuration, formatTokens, formatCost } from "@/lib/format";
import { cn } from "@/lib/utils";

const LIMIT = 20;

const STATUS_FILTERS: { label: string; value?: string; icon: LucideIcon }[] = [
  { label: "All", value: undefined, icon: List },
  { label: "Success", value: "success", icon: CheckCircle2 },
  { label: "Error", value: "error", icon: XCircle },
  { label: "Running", value: "running", icon: Loader2 },
];

export default async function TracesPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string; status?: string }>;
}) {
  const { offset: offsetStr, status } = await searchParams;
  const rawOffset = Number(offsetStr ?? 0);
  const offset = Number.isFinite(rawOffset) ? Math.max(0, rawOffset) : 0;

  let data;
  let failed = false;
  try {
    data = await getTraces({ limit: LIMIT, offset, status });
  } catch (err) {
    console.error("[loupe] Failed to fetch traces:", err);
    failed = true;
  }

  return (
    <div className="min-h-dvh">
      <TopBar
        right={
          <nav className="flex items-center gap-1">
            {STATUS_FILTERS.map((f) => {
              const active = (f.value ?? "") === (status ?? "");
              const Icon = f.icon;
              return (
                <Link
                  key={f.label}
                  href={f.value ? `/?status=${f.value}` : "/"}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "bg-surface-2 text-fg"
                      : "text-muted hover:bg-surface-2/60 hover:text-fg",
                  )}
                >
                  <Icon className="size-3.5" />
                  <span className="hidden sm:inline">{f.label}</span>
                </Link>
              );
            })}
          </nav>
        }
      />

      <main className="mx-auto w-full max-w-6xl px-5 py-7">
        <Reveal className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Traces</h1>
          <p className="mt-1 text-sm text-muted">
            Every end-to-end agent run. Click one to inspect spans, then replay it.
          </p>
        </Reveal>

        {failed ? (
          <ErrorState />
        ) : data!.items.length === 0 ? (
          <EmptyState status={status} />
        ) : (
          <>
            {/* Desktop table */}
            <Reveal className="hidden overflow-hidden rounded-xl border border-line bg-surface/50 md:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line bg-surface-2/60 text-left text-[10px] uppercase tracking-[0.12em] text-faint">
                    <th className="px-4 py-2.5 font-semibold">Name</th>
                    <th className="px-4 py-2.5 font-semibold">Status</th>
                    <th className="px-4 py-2.5 font-semibold">Started</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Duration</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Tokens</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data!.items.map((t, i) => (
                    <TraceRow key={t.id} trace={t} index={i} />
                  ))}
                </tbody>
              </table>
            </Reveal>

            {/* Mobile cards */}
            <div className="space-y-3 md:hidden">
              {data!.items.map((t, i) => (
                <TraceCardMobile key={t.id} trace={t} index={i} />
              ))}
            </div>

            <Pagination
              offset={offset}
              limit={LIMIT}
              hasMore={data!.has_more}
              status={status}
            />
          </>
        )}
      </main>
    </div>
  );
}

// ── Rows ─────────────────────────────────────────────────────────────────────

function TraceRow({ trace: t, index }: { trace: TraceListItem; index: number }) {
  return (
    <MotionRow
      index={index}
      className="group relative border-b border-line/50 transition-colors last:border-0 hover:bg-surface-2/50"
    >
      <td className="px-4 py-3">
        <Link
          href={`/traces/${t.id}`}
          className="font-mono text-fg after:absolute after:inset-0 after:content-['']"
        >
          {t.name ?? t.id.slice(0, 8)}
        </Link>
        <LineageTag trace={t} />
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={t.status} />
      </td>
      <td className="px-4 py-3 tabular-nums text-muted">{formatDate(t.started_at)}</td>
      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">
        {formatDuration(t.duration_ms)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-muted">
        {formatTokens(t.total_tokens)}
      </td>
      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">
        {formatCost(t.total_cost_usd)}
      </td>
    </MotionRow>
  );
}

function TraceCardMobile({ trace: t, index }: { trace: TraceListItem; index: number }) {
  return (
    <Reveal index={index}>
      <Link
        href={`/traces/${t.id}`}
        className="block rounded-xl border border-line bg-surface/60 p-4 transition-colors hover:border-line-strong"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-sm text-fg">
            {t.name ?? t.id.slice(0, 8)}
          </span>
          <StatusBadge status={t.status} />
        </div>
        <LineageTag trace={t} />
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-faint">
          <span>{formatDate(t.started_at)}</span>
          <span>{formatDuration(t.duration_ms)}</span>
          <span>{formatTokens(t.total_tokens)} tok</span>
          <span>{formatCost(t.total_cost_usd)}</span>
        </div>
      </Link>
    </Reveal>
  );
}

function LineageTag({ trace: t }: { trace: TraceListItem }) {
  if (!t.is_replay && !t.replay_of_trace_id) return null;
  return (
    <span className="relative z-10 ml-2 inline-flex align-middle">
      <ReplayBadge />
    </span>
  );
}

// ── States ───────────────────────────────────────────────────────────────────

function EmptyState({ status }: { status?: string }) {
  return (
    <Reveal className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line bg-surface/40 py-20 text-center">
      <div className="grid size-12 place-items-center rounded-full bg-surface-2 text-faint">
        <Inbox className="size-6" />
      </div>
      <p className="mt-4 text-sm font-medium text-fg">
        {status ? `No ${status} traces` : "No traces yet"}
      </p>
      <p className="mt-1 max-w-sm text-xs text-muted">
        {status
          ? "Try a different filter, or run your agent to generate traces."
          : "Instrument your agent with the Loupe SDK and runs will show up here."}
      </p>
      {status && (
        <Link href="/" className="mt-4">
          <Button variant="secondary" size="sm">
            <List className="size-3.5" />
            Show all traces
          </Button>
        </Link>
      )}
    </Reveal>
  );
}

function ErrorState() {
  return (
    <Reveal className="flex flex-col items-center justify-center rounded-xl border border-error/30 bg-error-dim/20 py-20 text-center">
      <div className="grid size-12 place-items-center rounded-full bg-error/10 text-error">
        <XCircle className="size-6" />
      </div>
      <p className="mt-4 text-sm font-medium text-fg">Could not reach the Loupe server</p>
      <p className="mt-1 text-xs text-muted">
        Is it running on{" "}
        <span className="font-mono text-faint">
          {process.env.LOUPE_API_URL ?? "http://localhost:8000"}
        </span>
        ?
      </p>
    </Reveal>
  );
}

// ── Pagination ────────────────────────────────────────────────────────────────

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
    <div className="mt-6 flex items-center gap-3">
      {offset > 0 ? (
        <Link href={`/?offset=${offset - limit}${statusParam}`}>
          <Button variant="secondary" size="sm">
            <ChevronLeft className="size-4" />
            Prev
          </Button>
        </Link>
      ) : (
        <Button variant="secondary" size="sm" disabled>
          <ChevronLeft className="size-4" />
          Prev
        </Button>
      )}

      <span className="text-xs tabular-nums text-faint">Page {page}</span>

      {hasMore ? (
        <Link href={`/?offset=${offset + limit}${statusParam}`}>
          <Button variant="secondary" size="sm">
            Next
            <ChevronRight className="size-4" />
          </Button>
        </Link>
      ) : (
        <Button variant="secondary" size="sm" disabled>
          Next
          <ChevronRight className="size-4" />
        </Button>
      )}
    </div>
  );
}

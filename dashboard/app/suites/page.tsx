import Link from "next/link";
import { FolderGit2, XCircle, Terminal } from "lucide-react";
import { getSuites, getSuiteRuns, SuiteListItem, SuiteRunSummary } from "@/lib/api";
import { TopBar } from "@/components/TopBar";
import { Reveal, MotionRow } from "@/components/motion";
import { CodeBlock } from "@/components/CodeBlock";
import { formatDate, formatRelative } from "@/lib/format";

/** A suite plus its most recent run (or null when it has never been run). */
type SuiteWithLastRun = SuiteListItem & { lastRun: SuiteRunSummary | null };

export default async function SuitesPage() {
  let suites: SuiteWithLastRun[] = [];
  let failed = false;
  try {
    const base = await getSuites();
    // One extra request per suite. Fine at this scale — a project has a handful
    // of suites, not thousands — and it keeps the list endpoint cheap for the
    // CLI, which doesn't need run history. Revisit with a joined
    // `last_run` field if suite counts ever grow.
    suites = await Promise.all(
      base.map(async (s) => {
        try {
          const runs = await getSuiteRuns(s.id, 1);
          return { ...s, lastRun: runs[0] ?? null };
        } catch {
          return { ...s, lastRun: null };
        }
      }),
    );
  } catch (err) {
    console.error("[loupe] Failed to fetch suites:", err);
    failed = true;
  }

  return (
    <div className="min-h-dvh">
      <TopBar back={{ label: "Traces", href: "/" }} />

      <main className="mx-auto w-full max-w-6xl px-5 py-7">
        <Reveal className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Suites</h1>
          <p className="mt-1 text-sm text-muted">
            Golden sets of saved traces. Every prompt change gets replayed against
            them and judged, so a regression blocks the PR instead of shipping.
          </p>
        </Reveal>

        {failed ? (
          <ErrorState />
        ) : suites.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            {/* Desktop table */}
            <Reveal className="hidden overflow-hidden rounded-xl border border-line bg-surface/50 md:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line bg-surface-2/60 text-left text-[10px] uppercase tracking-[0.12em] text-faint">
                    <th className="px-4 py-2.5 font-semibold">Name</th>
                    <th className="px-4 py-2.5 text-right font-semibold">Traces</th>
                    <th className="px-4 py-2.5 font-semibold">Last run</th>
                    <th className="px-4 py-2.5 font-semibold">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {suites.map((s, i) => (
                    <SuiteRow key={s.id} suite={s} index={i} />
                  ))}
                </tbody>
              </table>
            </Reveal>

            {/* Mobile cards */}
            <div className="space-y-3 md:hidden">
              {suites.map((s, i) => (
                <SuiteCardMobile key={s.id} suite={s} index={i} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

// ── Rows ─────────────────────────────────────────────────────────────────────

function SuiteRow({ suite: s, index }: { suite: SuiteWithLastRun; index: number }) {
  return (
    <MotionRow
      index={index}
      className="group relative border-b border-line/50 transition-colors last:border-0 hover:bg-surface-2/50"
    >
      <td className="px-4 py-3">
        <Link
          href={`/suites/${s.id}`}
          className="font-medium text-fg after:absolute after:inset-0 after:content-['']"
        >
          {s.name}
        </Link>
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-muted">{s.trace_count}</td>
      <td className="px-4 py-3">
        <LastRunCell run={s.lastRun} />
      </td>
      <td className="px-4 py-3 tabular-nums text-muted">{formatDate(s.created_at)}</td>
    </MotionRow>
  );
}

function SuiteCardMobile({ suite: s, index }: { suite: SuiteWithLastRun; index: number }) {
  return (
    <Reveal index={index}>
      <Link
        href={`/suites/${s.id}`}
        className="block rounded-xl border border-line bg-surface/60 p-4 transition-colors hover:border-line-strong"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-medium text-fg">{s.name}</span>
          <span className="shrink-0 text-xs tabular-nums text-faint">
            {s.trace_count} traces
          </span>
        </div>
        <div className="mt-3">
          <LastRunCell run={s.lastRun} />
        </div>
      </Link>
    </Reveal>
  );
}

/** Pass/regress counts for the newest run — the "is this suite healthy" glance. */
export function LastRunCell({ run }: { run: SuiteRunSummary | null }) {
  if (!run) return <span className="text-xs text-faint">never run</span>;
  if (run.status === "running") {
    return <span className="text-xs text-warning">running…</span>;
  }
  const bad = run.regressed > 0 || run.errored > 0;
  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <span className={bad ? "font-medium text-error" : "font-medium text-success"}>
        {bad ? "✗" : "✓"} {run.passed}/{run.total}
      </span>
      {run.regressed > 0 && (
        <span className="text-muted">{run.regressed} regressed</span>
      )}
      <span className="tabular-nums text-faint">{formatRelative(run.created_at)}</span>
    </span>
  );
}

// ── States ───────────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <Reveal className="rounded-xl border border-dashed border-line bg-surface/40 px-6 py-14 text-center">
      <div className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-faint">
        <FolderGit2 className="size-6" />
      </div>
      <p className="mt-4 text-sm font-medium text-fg">No suites yet</p>
      <p className="mx-auto mt-1 max-w-md text-xs text-muted">
        A suite snapshots real production traces so a prompt change can be tested
        against them. Create one from your most recent runs:
      </p>
      <div className="mx-auto mt-5 max-w-md text-left">
        <CodeBlock text={'loupe suite create --name "golden" --from last:15'} />
      </div>
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
      <p className="mt-1 flex items-center gap-1.5 text-xs text-muted">
        <Terminal className="size-3.5" />
        Is it running on{" "}
        <span className="font-mono text-faint">
          {process.env.LOUPE_API_URL ?? "http://localhost:8000"}
        </span>
        ?
      </p>
    </Reveal>
  );
}

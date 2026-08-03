import Link from "next/link";
import { notFound } from "next/navigation";
import { History, Scale } from "lucide-react";
import { getSuite, getSuiteRuns, SuiteRunSummary } from "@/lib/api";
import { TopBar } from "@/components/TopBar";
import { Reveal, MotionRow } from "@/components/motion";
import { AutoRefresh } from "@/components/AutoRefresh";
import { CodeBlock } from "@/components/CodeBlock";
import { formatDate, formatDuration, formatRelative } from "@/lib/format";

export default async function SuiteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let suite;
  let runs: SuiteRunSummary[] = [];
  try {
    [suite, runs] = await Promise.all([getSuite(id), getSuiteRuns(id, 20)]);
  } catch (err) {
    console.error("[loupe] Failed to fetch suite:", err);
    notFound();
  }

  // Poll while a run is in flight — a suite run is a BackgroundTask, so the row
  // fills in after the response. Same 2s polling the trace detail page uses.
  const anyRunning = runs.some((r) => r.status === "running");

  return (
    <div className="min-h-dvh">
      {anyRunning && <AutoRefresh intervalMs={2000} />}
      <TopBar
        back={{ label: "Suites", href: "/suites" }}
        crumbs={[{ label: suite!.name }]}
      />

      <main className="mx-auto w-full max-w-6xl px-5 py-7">
        <Reveal className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">{suite!.name}</h1>
          <p className="mt-1 text-sm text-muted">
            {suite!.trace_count} {suite!.trace_count === 1 ? "trace" : "traces"} ·
            created {formatDate(suite!.created_at)}
          </p>
        </Reveal>

        {suite!.judge_rubric && (
          <Reveal className="mb-6">
            <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <Scale className="size-4 text-faint" />
              Custom rubric
            </h2>
            <p className="mb-2 text-xs text-muted">
              This suite overrides the default judging criteria.
            </p>
            <CodeBlock text={suite!.judge_rubric} />
          </Reveal>
        )}

        <Reveal>
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
            <History className="size-4 text-faint" />
            Run history
          </h2>

          {runs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line bg-surface/40 px-6 py-12 text-center">
              <p className="text-sm font-medium text-fg">No runs yet</p>
              <p className="mx-auto mt-1 max-w-md text-xs text-muted">
                Run this suite against a changed prompt — locally, or from CI via
                the Loupe GitHub Action.
              </p>
              <div className="mx-auto mt-5 max-w-md text-left">
                <CodeBlock text={`loupe suite run ${id} --prompt new_prompt.txt`} />
              </div>
            </div>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden overflow-hidden rounded-xl border border-line bg-surface/50 md:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-left text-[10px] uppercase tracking-[0.12em] text-faint">
                      <th className="px-4 py-2.5 font-semibold">Result</th>
                      <th className="px-4 py-2.5 font-semibold">Judge</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Duration</th>
                      <th className="px-4 py-2.5 font-semibold">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r, i) => (
                      <RunRow key={r.id} run={r} index={i} />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="space-y-3 md:hidden">
                {runs.map((r, i) => (
                  <RunCardMobile key={r.id} run={r} index={i} />
                ))}
              </div>
            </>
          )}
        </Reveal>
      </main>
    </div>
  );
}

// ── Rows ─────────────────────────────────────────────────────────────────────

function runDuration(r: SuiteRunSummary): number | null {
  if (!r.ended_at) return null;
  return new Date(r.ended_at).getTime() - new Date(r.started_at).getTime();
}

function RunRow({ run: r, index }: { run: SuiteRunSummary; index: number }) {
  return (
    <MotionRow
      index={index}
      className="group relative border-b border-line/50 transition-colors last:border-0 hover:bg-surface-2/50"
    >
      <td className="px-4 py-3">
        <Link
          href={`/suite_runs/${r.id}`}
          className="after:absolute after:inset-0 after:content-['']"
        >
          <RunResult run={r} />
        </Link>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-muted">
        {r.judge_backend ?? "—"}
      </td>
      <td className="px-4 py-3 text-right font-mono tabular-nums text-muted">
        {formatDuration(runDuration(r))}
      </td>
      <td className="px-4 py-3 tabular-nums text-muted">
        {formatRelative(r.created_at)}
      </td>
    </MotionRow>
  );
}

function RunCardMobile({ run: r, index }: { run: SuiteRunSummary; index: number }) {
  return (
    <Reveal index={index}>
      <Link
        href={`/suite_runs/${r.id}`}
        className="block rounded-xl border border-line bg-surface/60 p-4 transition-colors hover:border-line-strong"
      >
        <RunResult run={r} />
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-faint">
          <span className="font-mono">{r.judge_backend ?? "—"}</span>
          <span>{formatDuration(runDuration(r))}</span>
          <span>{formatRelative(r.created_at)}</span>
        </div>
      </Link>
    </Reveal>
  );
}

/** The headline: did this run pass, and by how much. */
export function RunResult({ run: r }: { run: SuiteRunSummary }) {
  if (r.status === "running") {
    return <span className="text-sm text-warning">running…</span>;
  }
  const bad = r.regressed > 0 || r.errored > 0;
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span
        className={
          bad ? "text-sm font-semibold text-error" : "text-sm font-semibold text-success"
        }
      >
        {bad ? "✗" : "✓"} {r.passed}/{r.total} passed
      </span>
      {r.improved > 0 && (
        <span className="text-xs text-accent">{r.improved} improved</span>
      )}
      {r.regressed > 0 && (
        <span className="text-xs text-error">{r.regressed} regressed</span>
      )}
      {r.errored > 0 && <span className="text-xs text-muted">{r.errored} errored</span>}
    </span>
  );
}

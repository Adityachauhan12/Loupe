import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, FileText, Zap } from "lucide-react";
import { getSuiteRun, SuiteRunDetail, SuiteRunResult } from "@/lib/api";
import { TopBar } from "@/components/TopBar";
import { Reveal } from "@/components/motion";
import { AutoRefresh } from "@/components/AutoRefresh";
import { CodeBlock } from "@/components/CodeBlock";
import { VerdictBadge } from "@/components/badges";
import { formatDate, formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

export default async function SuiteRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let run: SuiteRunDetail;
  try {
    run = await getSuiteRun(id);
  } catch (err) {
    console.error("[loupe] Failed to fetch suite run:", err);
    notFound();
  }

  const running = run!.status === "running";
  const results = run!.results ?? [];
  // Regressions first — this page exists to answer "what broke?".
  const ordered = [...results].sort((a, b) => rank(a) - rank(b));
  const duration = run!.ended_at
    ? new Date(run!.ended_at).getTime() - new Date(run!.started_at).getTime()
    : null;

  return (
    <div className="min-h-dvh">
      {running && <AutoRefresh intervalMs={2000} />}
      <TopBar
        back={{ label: "Suite", href: `/suites/${run!.suite_id}` }}
        crumbs={[{ label: `run ${id.slice(0, 8)}` }]}
      />

      <main className="mx-auto w-full max-w-6xl px-5 py-7">
        <Reveal className="mb-6">
          <Headline run={run!} />
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5">
              <Zap className="size-3.5 text-faint" />
              judge <span className="font-mono">{run!.judge_backend ?? "—"}</span>
            </span>
            {run!.model_override && (
              <span className="font-mono">model → {run!.model_override}</span>
            )}
            <span>{formatDuration(duration)}</span>
            <span>{formatDate(run!.created_at)}</span>
          </p>
        </Reveal>

        {run!.error && (
          <Reveal className="mb-6">
            <h2 className="mb-2 text-sm font-semibold text-error">Run failed</h2>
            <CodeBlock data={run!.error} isError />
          </Reveal>
        )}

        {run!.prompt_override && (
          <Reveal className="mb-6">
            <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <FileText className="size-4 text-faint" />
              Prompt under test
            </h2>
            <CodeBlock text={run!.prompt_override} />
          </Reveal>
        )}

        <Reveal>
          <h2 className="mb-3 text-sm font-semibold">
            Per-trace verdicts{" "}
            <span className="font-normal text-faint">({results.length})</span>
          </h2>

          {results.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line bg-surface/40 px-6 py-12 text-center">
              <p className="text-sm font-medium text-fg">
                {running ? "Replaying traces…" : "No results recorded"}
              </p>
              <p className="mt-1 text-xs text-muted">
                {running
                  ? "Each trace is replayed with the new prompt, then judged. This page refreshes itself."
                  : "The run finished without judging any trace."}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {ordered.map((r, i) => (
                <ResultRow key={r.trace_id} result={r} index={i} />
              ))}
            </div>
          )}
        </Reveal>
      </main>
    </div>
  );
}

/** Sort key: regressions, then errors, then improvements, then equivalents. */
function rank(r: SuiteRunResult): number {
  if (r.error) return 1;
  if (r.verdict === "regressed") return 0;
  if (r.verdict === "improved") return 2;
  return 3;
}

function Headline({ run }: { run: SuiteRunDetail }) {
  if (run.status === "running") {
    return (
      <h1 className="text-2xl font-bold tracking-tight text-warning">
        Running… {run.total > 0 && `${run.passed + run.regressed}/${run.total}`}
      </h1>
    );
  }
  const bad = run.regressed > 0 || run.errored > 0;
  return (
    <>
      <h1
        className={cn(
          "text-2xl font-bold tracking-tight",
          bad ? "text-error" : "text-success",
        )}
      >
        {bad ? "✗" : "✓"} {run.passed}/{run.total} passed
      </h1>
      <p className="mt-1 text-sm text-muted">
        {run.improved} improved · {run.regressed} regressed · {run.errored} errored
        {bad && " — this run would block the PR."}
      </p>
    </>
  );
}

// ── Result row ───────────────────────────────────────────────────────────────

function ResultRow({ result: r, index }: { result: SuiteRunResult; index: number }) {
  const verdict = r.error ? "errored" : (r.verdict ?? "unknown");
  const isBad = verdict === "regressed" || verdict === "errored";

  return (
    <Reveal
      index={index}
      className={cn(
        "rounded-xl border bg-surface/50 p-4",
        isBad ? "border-error/25" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={verdict} />
        <Link
          href={`/traces/${r.trace_id}`}
          className="font-mono text-xs text-muted transition-colors hover:text-fg"
        >
          {r.trace_id.slice(0, 8)}
        </Link>
        {r.score_source && (
          <span
            title={
              r.score_source === "deterministic"
                ? "Decided by a free deterministic check — no LLM call was needed."
                : "Scored by the judge LLM."
            }
            className="rounded border border-line px-1.5 py-0.5 text-[10px] font-medium text-faint"
          >
            {r.score_source}
          </span>
        )}
        {r.confidence != null && (
          <span className="text-[10px] tabular-nums text-faint">
            confidence {r.confidence.toFixed(2)}
          </span>
        )}

        {r.new_trace_id && (
          <Link
            href={`/traces/${r.new_trace_id}/diff`}
            className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:text-primary-strong"
          >
            View diff
            <ArrowRight className="size-3.5" />
          </Link>
        )}
      </div>

      {r.reasoning && <p className="mt-2 text-xs leading-relaxed text-muted">{r.reasoning}</p>}
      {r.error && (
        <p className="mt-2 font-mono text-xs leading-relaxed text-error">{r.error}</p>
      )}
    </Reveal>
  );
}

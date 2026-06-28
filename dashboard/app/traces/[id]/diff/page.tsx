import Link from "next/link";
import { notFound } from "next/navigation";
import { Loader2, GitBranch, ArrowLeft } from "lucide-react";
import { getTrace, TraceDetail } from "@/lib/api";
import { BranchDiff } from "@/components/BranchDiff";
import { AutoRefresh } from "@/components/AutoRefresh";
import { TopBar } from "@/components/TopBar";
import { Reveal } from "@/components/motion";
import { Button } from "@/components/ui/button";

// Diff a branched trace against the original it was forked from.
export default async function BranchDiffPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let branched: TraceDetail;
  try {
    branched = await getTrace(id);
  } catch {
    notFound();
  }

  if (!branched.branched_from_trace_id) return <NotABranch traceId={id} />;
  if (branched.status === "running") return <WaitingPage />;

  let original: TraceDetail;
  try {
    original = await getTrace(branched.branched_from_trace_id);
  } catch (err) {
    console.error("Failed to fetch original trace for branch diff:", err);
    notFound();
  }

  return (
    <div className="min-h-dvh">
      <TopBar
        back={{ label: "Original trace", href: `/traces/${branched.branched_from_trace_id}` }}
        crumbs={[{ label: "Branch diff" }]}
        right={
          <Link
            href={`/traces/${branched.id}`}
            className="text-xs text-muted transition-colors hover:text-fg"
          >
            View branched trace →
          </Link>
        }
      />
      <main className="mx-auto w-full max-w-6xl space-y-4 px-5 py-7">
        <Reveal>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <GitBranch className="size-6 text-primary" />
            Branch Diff
          </h1>
          <p className="mt-1 text-sm text-muted">
            Original vs branched run, from the branch point onward.
          </p>
        </Reveal>
        <Reveal index={1}>
          <BranchDiff original={original} branched={branched} />
        </Reveal>
      </main>
    </div>
  );
}

function NotABranch({ traceId }: { traceId: string }) {
  return (
    <div className="min-h-dvh">
      <TopBar crumbs={[{ label: "Branch diff" }]} />
      <main className="flex min-h-[60vh] items-center justify-center px-5">
        <div className="max-w-sm space-y-3 text-center">
          <p className="text-sm text-fg">This trace isn&apos;t a branch.</p>
          <p className="text-xs text-muted">
            Only branched / replayed traces have an original to diff against.
          </p>
          <Link href={`/traces/${traceId}`} className="inline-block">
            <Button variant="secondary" size="sm">
              <ArrowLeft className="size-3.5" />
              Back to trace
            </Button>
          </Link>
        </div>
      </main>
    </div>
  );
}

function WaitingPage() {
  return (
    <div className="min-h-dvh">
      <TopBar crumbs={[{ label: "Branch diff" }]} />
      <main className="flex min-h-[60vh] items-center justify-center px-5">
        <div className="space-y-3 text-center">
          <Loader2 className="mx-auto size-7 animate-spin text-warning" />
          <p className="text-sm font-medium text-warning">Branch in progress…</p>
          <p className="text-xs text-muted">
            Re-running from the branch point. This page refreshes automatically.
          </p>
          <AutoRefresh intervalMs={3000} />
        </div>
      </main>
    </div>
  );
}

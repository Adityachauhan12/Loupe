import Link from "next/link";
import { notFound } from "next/navigation";
import { Loader2, Repeat } from "lucide-react";
import { getReplay, getTrace, TraceDetail } from "@/lib/api";
import { ReplayDiff } from "@/components/ReplayDiff";
import { AutoRefresh } from "@/components/AutoRefresh";
import { TopBar } from "@/components/TopBar";
import { Reveal } from "@/components/motion";

export default async function ReplayDiffPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let replay, original: TraceDetail, replayTrace: TraceDetail;

  try {
    replay = await getReplay(id);
  } catch {
    notFound();
  }

  if (!replay.new_trace_id) return <WaitingPage />;

  try {
    [original, replayTrace] = await Promise.all([
      getTrace(replay.original_trace_id),
      getTrace(replay.new_trace_id),
    ]);
  } catch (err) {
    console.error("Failed to fetch traces for diff:", err);
    notFound();
  }

  if (replayTrace.status === "running") return <WaitingPage />;

  return (
    <div className="min-h-dvh">
      <TopBar
        back={{ label: "Original trace", href: `/traces/${replay.original_trace_id}` }}
        crumbs={[{ label: "Replay diff" }]}
        right={
          <Link
            href={`/traces/${replay.new_trace_id}`}
            className="text-xs text-muted transition-colors hover:text-fg"
          >
            View replay trace →
          </Link>
        }
      />
      <main className="mx-auto w-full max-w-6xl space-y-4 px-5 py-7">
        <Reveal>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Repeat className="size-6 text-accent" />
            Replay Diff
          </h1>
          <p className="mt-1 text-sm text-muted">
            Original vs replayed run — what changed when you tweaked the prompt or model.
          </p>
        </Reveal>
        <Reveal index={1}>
          <ReplayDiff
            original={original}
            replay={replayTrace}
            modifications={replay.modifications}
          />
        </Reveal>
      </main>
    </div>
  );
}

function WaitingPage() {
  return (
    <div className="min-h-dvh">
      <TopBar crumbs={[{ label: "Replay diff" }]} />
      <main className="flex min-h-[60vh] items-center justify-center px-5">
        <div className="space-y-3 text-center">
          <Loader2 className="mx-auto size-7 animate-spin text-warning" />
          <p className="text-sm font-medium text-warning">Replay in progress…</p>
          <p className="text-xs text-muted">
            The LLM is running. This page refreshes automatically.
          </p>
          <AutoRefresh intervalMs={3000} />
        </div>
      </main>
    </div>
  );
}

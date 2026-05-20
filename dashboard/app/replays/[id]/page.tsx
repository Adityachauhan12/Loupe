import Link from "next/link";
import { notFound } from "next/navigation";
import { getReplay, getTrace, TraceDetail } from "@/lib/api";
import { ReplayDiff } from "@/components/ReplayDiff";
import { AutoRefresh } from "@/components/AutoRefresh";

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

  // Replay still running — show waiting state
  if (!replay.new_trace_id) {
    return <WaitingPage replayId={id} />;
  }

  try {
    [original, replayTrace] = await Promise.all([
      getTrace(replay.original_trace_id),
      getTrace(replay.new_trace_id),
    ]);
  } catch (err) {
    console.error("Failed to fetch traces for diff:", err);
    notFound();
  }

  if (replayTrace.status === "running") {
    return <WaitingPage replayId={id} />;
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <Link
          href={`/traces/${replay.original_trace_id}`}
          className="text-gray-500 hover:text-gray-200 transition-colors text-sm"
        >
          ← Original trace
        </Link>
        <span className="text-gray-700">/</span>
        <span className="text-sm text-gray-300">Replay diff</span>
        <Link
          href={`/traces/${replay.new_trace_id}`}
          className="ml-auto text-xs text-gray-600 hover:text-gray-400 transition-colors"
        >
          View replay trace →
        </Link>
      </header>

      <main className="flex-1 px-6 py-6 max-w-6xl mx-auto w-full space-y-4">
        <h1 className="text-xl font-bold">Replay Diff</h1>
        <ReplayDiff
          original={original}
          replay={replayTrace}
          modifications={replay.modifications}
        />
      </main>
    </div>
  );
}

function WaitingPage({ replayId }: { replayId: string }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-gray-800 px-6 py-4">
        <span className="text-sm text-gray-500">Replay diff</span>
      </header>
      <main className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="text-amber-400 text-sm font-medium">Replay in progress…</div>
          <p className="text-gray-600 text-xs">
            The LLM is running. This page will refresh automatically.
          </p>
          <AutoRefresh intervalMs={3000} />
        </div>
      </main>
    </div>
  );
}

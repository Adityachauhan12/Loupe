import { TopBar } from "@/components/TopBar";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto w-full max-w-6xl px-5 py-7">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="mt-2 h-4 w-80" />
        <div className="mt-6 overflow-hidden rounded-xl border border-line bg-surface/50">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-4 border-b border-line/50 px-4 py-3.5 last:border-0"
            >
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-16 rounded-md" />
              <Skeleton className="ml-auto h-4 w-20" />
              <Skeleton className="h-4 w-14" />
              <Skeleton className="h-4 w-16" />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

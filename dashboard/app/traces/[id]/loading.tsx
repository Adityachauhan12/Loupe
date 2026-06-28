import { TopBar } from "@/components/TopBar";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="min-h-dvh">
      <TopBar back={{ label: "Traces", href: "/" }} />
      <main className="mx-auto w-full max-w-6xl space-y-6 px-5 py-7">
        <div>
          <Skeleton className="h-6 w-64" />
          <Skeleton className="mt-2 h-3 w-32" />
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-xl" />
            ))}
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-40 rounded-lg" />
          <Skeleton className="h-40 rounded-lg" />
        </div>
        <Skeleton className="h-64 rounded-xl" />
      </main>
    </div>
  );
}

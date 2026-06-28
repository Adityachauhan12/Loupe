import {
  CheckCircle2,
  XCircle,
  Loader2,
  CircleHelp,
  Sparkles,
  Wrench,
  Braces,
  Database,
  GitBranch,
  Repeat,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Status badge (icon + text → never color-only) ───────────────────────────

const STATUS: Record<
  string,
  { icon: LucideIcon; cls: string; spin?: boolean }
> = {
  success: { icon: CheckCircle2, cls: "bg-success/12 text-success border-success/25" },
  error: { icon: XCircle, cls: "bg-error/12 text-error border-error/25" },
  running: {
    icon: Loader2,
    cls: "bg-warning/12 text-warning border-warning/25",
    spin: true,
  },
};

export function StatusBadge({
  status,
  className,
}: {
  status: string | null;
  className?: string;
}) {
  const s = STATUS[status ?? ""] ?? {
    icon: CircleHelp,
    cls: "bg-surface-2 text-muted border-line",
  };
  const Icon = s.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium capitalize",
        s.cls,
        className,
      )}
    >
      <Icon className={cn("size-3.5", s.spin && "animate-spin")} />
      {status ?? "unknown"}
    </span>
  );
}

// ── Span-type badge ─────────────────────────────────────────────────────────

const TYPE: Record<string, { icon: LucideIcon; label: string; cls: string }> = {
  llm: { icon: Sparkles, label: "llm", cls: "bg-llm/12 text-llm border-llm/25" },
  tool: { icon: Wrench, label: "tool", cls: "bg-tool/12 text-tool border-tool/25" },
  function: { icon: Braces, label: "fn", cls: "bg-fn/10 text-fn border-fn/20" },
  retrieval: {
    icon: Database,
    label: "ret",
    cls: "bg-retrieval/12 text-retrieval border-retrieval/25",
  },
};

export function TypeBadge({
  type,
  className,
}: {
  type: string;
  className?: string;
}) {
  const t = TYPE[type] ?? {
    icon: Braces,
    label: type,
    cls: "bg-surface-2 text-muted border-line",
  };
  const Icon = t.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-mono font-semibold shrink-0",
        t.cls,
        className,
      )}
    >
      <Icon className="size-3" />
      {t.label}
    </span>
  );
}

// ── Lineage badges ──────────────────────────────────────────────────────────

export function BranchBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-primary-strong/30 bg-primary-soft/30 px-2 py-0.5 text-xs font-medium text-primary",
        className,
      )}
    >
      <GitBranch className="size-3.5" />
      branch
    </span>
  );
}

export function ReplayBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent",
        className,
      )}
    >
      <Repeat className="size-3.5" />
      replay
    </span>
  );
}

// ── Replay-engine markers on a span ─────────────────────────────────────────

export function MarkerBadges({
  meta,
}: {
  meta: Record<string, unknown> | null | undefined;
}) {
  if (!meta) return null;
  const badges: { label: string; cls: string; title: string }[] = [];
  if (meta.branch_point === true)
    badges.push({
      label: "branch point",
      cls: "bg-primary-soft/40 text-primary border-primary-strong/30",
      title: "The span you edited — the branch starts here.",
    });
  if (meta.dry_run === true)
    badges.push({
      label: "dry-run",
      cls: "bg-surface-2 text-faint border-line",
      title: "Write skipped during replay — output shows what would have happened.",
    });
  if (meta.replay === "stored_passthrough")
    badges.push({
      label: "passthrough",
      cls: "bg-surface-2 text-faint border-line",
      title: "Stored output reused — the server can't re-run this tool live.",
    });
  if (badges.length === 0) return null;
  return (
    <>
      {badges.map((b) => (
        <span
          key={b.label}
          title={b.title}
          className={cn(
            "inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium shrink-0",
            b.cls,
          )}
        >
          {b.label}
        </span>
      ))}
    </>
  );
}

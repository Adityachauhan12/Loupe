// Shared formatters — single source of truth (previously duplicated across
// the traces list, trace detail, and both diff views).

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export function formatCost(usd: string | number | null | undefined): string {
  if (usd == null) return "—";
  return `$${Number(usd).toFixed(4)}`;
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

export function formatDate(
  iso: string,
  opts: { withSeconds?: boolean } = {},
): string {
  return new Intl.DateTimeFormat("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...(opts.withSeconds ? { second: "2-digit" } : {}),
    hour12: false,
    timeZone: "Asia/Kolkata",
  }).format(new Date(iso));
}

/** Relative "3m ago" style for recency at a glance. */
export function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.round(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

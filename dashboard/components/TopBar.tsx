import Link from "next/link";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/** Loupe wordmark with a lens/aperture glyph. */
export function Logo({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      className={cn(
        "group inline-flex items-center gap-2 font-semibold tracking-tight text-fg",
        className,
      )}
    >
      <span className="relative grid size-7 place-items-center rounded-lg bg-gradient-to-br from-primary to-accent shadow-[0_4px_16px_-4px_rgba(124,124,245,0.7)] transition-transform group-hover:scale-105">
        <svg viewBox="0 0 24 24" className="size-4 text-white" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
          <circle cx="10.5" cy="10.5" r="6.5" />
          <line x1="15.5" y1="15.5" x2="21" y2="21" />
        </svg>
      </span>
      Loupe
    </Link>
  );
}

/** Top app bar. Pass breadcrumb crumbs and an optional right slot. */
export function TopBar({
  crumbs,
  right,
  back,
}: {
  crumbs?: { label: string; href?: string }[];
  right?: React.ReactNode;
  back?: { label: string; href: string };
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-5">
        <Logo />
        {back && (
          <Link
            href={back.href}
            className="ml-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <ArrowLeft className="size-4" />
            {back.label}
          </Link>
        )}
        {crumbs && crumbs.length > 0 && (
          <nav className="flex items-center gap-1.5 text-sm text-muted">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <ChevronRight className="size-3.5 text-faint" />}
                {c.href ? (
                  <Link
                    href={c.href}
                    className="transition-colors hover:text-fg"
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span className="font-mono text-fg">{c.label}</span>
                )}
              </span>
            ))}
          </nav>
        )}
        {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
      </div>
    </header>
  );
}

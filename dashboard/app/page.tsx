import Link from "next/link";
import {
  ArrowRight,
  GitBranch,
  ScanLine,
  SplitSquareHorizontal,
  Package,
} from "lucide-react";
import { Logo } from "@/components/TopBar";
import { Reveal } from "@/components/motion";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Landing page (U-001).
 *
 * Deliberately makes ZERO API calls, so Vercel serves it as static HTML from the
 * CDN. The traces list at /traces still hits the server, but a visitor's first
 * paint no longer waits on Render's free tier waking up (~15min idle sleep).
 * Keep it that way: adding a live stat here re-introduces the cold start.
 */

/** lucide dropped brand marks, so the GitHub glyph lives here. */
function GithubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

const GITHUB = "https://github.com/Adityachauhan12/Loupe";
const PYPI = "https://pypi.org/project/loupe-sdk/";

export default function LandingPage() {
  return (
    <div className="min-h-dvh">
      <LandingHeader />

      <main className="mx-auto w-full max-w-6xl px-5">
        <Hero />
        <DemoFrame />
        <KillerFlow />
      </main>

      <LandingFooter />
    </div>
  );
}

// ── Header ───────────────────────────────────────────────────────────────────

function LandingHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center px-5">
        <Logo href="/" />
        <nav className="ml-auto flex items-center gap-1 text-sm">
          <Link
            href="/traces"
            className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            Traces
          </Link>
          <Link
            href="/suites"
            className="rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            Suites
          </Link>
          <a
            href={GITHUB}
            target="_blank"
            rel="noreferrer"
            className="ml-1 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <GithubMark className="size-4" />
            <span className="hidden sm:inline">GitHub</span>
          </a>
        </nav>
      </div>
    </header>
  );
}

// ── Hero ─────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="pt-16 pb-12 sm:pt-24 sm:pb-16">
      <Reveal className="max-w-3xl">
        <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/60 px-3 py-1 text-xs text-muted">
          <span className="size-1.5 rounded-full bg-success" aria-hidden />
          Open source · Python SDK · self-hosted
        </span>

        <h1 className="mt-6 text-4xl font-bold leading-[1.1] tracking-tight sm:text-6xl">
          See what your agent did.
          <br />
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            Then change it and re-run.
          </span>
        </h1>

        <p className="mt-6 max-w-2xl text-base leading-relaxed text-muted sm:text-lg">
          Loupe traces every LLM call, tool call and nested span in your agent. When a
          run goes wrong, open it, edit the span that broke it, and re-run from that
          exact point — with your real tools — then diff the two runs side by side.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/traces"
            className={cn(buttonVariants({ variant: "primary", size: "lg" }))}
          >
            View live traces
            <ArrowRight className="size-4" />
          </Link>
          <a
            href={GITHUB}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "secondary", size: "lg" }))}
          >
            <GithubMark className="size-4" />
            GitHub
          </a>
          <a
            href={PYPI}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "ghost", size: "lg" }))}
          >
            <Package className="size-4" />
            loupe-sdk on PyPI
          </a>
        </div>
      </Reveal>

      <Reveal index={2} className="mt-12">
        <InstallSnippet />
      </Reveal>
    </section>
  );
}

function InstallSnippet() {
  return (
    <div className="max-w-2xl overflow-hidden rounded-xl border border-line bg-surface/60">
      <div className="flex items-center justify-between border-b border-line bg-surface-2/60 px-4 py-2">
        <span className="text-[10px] uppercase tracking-[0.12em] text-faint">
          Three lines to instrument
        </span>
        <span className="font-mono text-[10px] text-faint">python</span>
      </div>
      <pre className="overflow-x-auto px-4 py-4 font-mono text-[13px] leading-relaxed">
        <code>
          <span className="text-faint">$ pip install loupe-sdk</span>
          {"\n\n"}
          <span className="text-llm">import</span> <span className="text-fg">loupe</span>
          {"\n"}
          <span className="text-fg">loupe</span>.<span className="text-tool">init</span>
          <span className="text-faint">(</span>
          <span className="text-fg">api_key</span>=
          <span className="text-success">&quot;lp_...&quot;</span>
          <span className="text-faint">)</span>
          {"\n\n"}
          <span className="text-accent">@loupe.trace</span>
          {"\n"}
          <span className="text-llm">async def</span>{" "}
          <span className="text-tool">run_agent</span>
          <span className="text-faint">(</span>
          <span className="text-fg">query</span>
          <span className="text-faint">):</span>
          {"\n"}
          {"    "}
          <span className="text-faint">...</span>
        </code>
      </pre>
    </div>
  );
}

// ── Demo slot ────────────────────────────────────────────────────────────────

/** Framed slot for the killer-demo recording (Track D). Until that GIF exists
 *  this renders a static mock of the same flow, so the page never shows an
 *  empty "coming soon" box. Swap the inner div for <img>/<video> when ready. */
function DemoFrame() {
  return (
    <Reveal index={3} className="pb-16 sm:pb-24">
      <div className="overflow-hidden rounded-2xl border border-line bg-surface/40 shadow-[0_24px_80px_-32px_rgba(99,102,241,0.45)]">
        <div className="flex items-center gap-2 border-b border-line bg-surface-2/70 px-4 py-2.5">
          <span className="size-2.5 rounded-full bg-error/60" aria-hidden />
          <span className="size-2.5 rounded-full bg-warning/60" aria-hidden />
          <span className="size-2.5 rounded-full bg-success/60" aria-hidden />
          <span className="ml-3 truncate font-mono text-[11px] text-faint">
            loupe / traces / qa_a5_error / diff
          </span>
        </div>

        <div className="grid gap-px bg-line sm:grid-cols-2">
          <DiffPane
            label="Original"
            status="error"
            spans={[
              { name: "plan_query", type: "llm", ok: true },
              { name: "search_actors", type: "tool", ok: false },
              { name: "compose_answer", type: "llm", ok: false },
            ]}
            output="I couldn't find any movies matching that request."
          />
          <DiffPane
            label="Branched"
            status="success"
            spans={[
              { name: "plan_query", type: "llm", ok: true, frozen: true },
              { name: "search_movies", type: "tool", ok: true, edited: true },
              { name: "compose_answer", type: "llm", ok: true },
            ]}
            output="Interstellar (2014), directed by Christopher Nolan — 8.7/10."
          />
        </div>
      </div>
      <p className="mt-3 text-center text-xs text-faint">
        Edit one span&apos;s output, re-run from there, and compare the two runs.
      </p>
    </Reveal>
  );
}

function DiffPane({
  label,
  status,
  spans,
  output,
}: {
  label: string;
  status: "success" | "error";
  spans: { name: string; type: string; ok: boolean; frozen?: boolean; edited?: boolean }[];
  output: string;
}) {
  const ok = status === "success";
  return (
    <div className="bg-bg/60 p-4">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted">{label}</span>
        <span
          className={cn(
            "rounded-md px-1.5 py-0.5 text-[10px] font-medium",
            ok ? "bg-success-dim/60 text-success" : "bg-error-dim/60 text-error",
          )}
        >
          {status}
        </span>
      </div>

      <ul className="mt-3 space-y-1.5">
        {spans.map((s) => (
          <li key={s.name} className="flex items-center gap-2 font-mono text-[11px]">
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                s.ok ? "bg-success" : "bg-error",
              )}
              aria-hidden
            />
            <span className={s.ok ? "text-muted" : "text-error"}>{s.name}</span>
            <span className="text-faint">{s.type}</span>
            {s.frozen && (
              <span className="rounded bg-surface-2 px-1 text-[9px] text-faint">
                frozen
              </span>
            )}
            {s.edited && (
              <span className="rounded bg-primary-soft/60 px-1 text-[9px] text-primary">
                edited
              </span>
            )}
          </li>
        ))}
      </ul>

      <p
        className={cn(
          "mt-3 rounded-lg border px-3 py-2 text-[11px] leading-relaxed",
          ok
            ? "border-success/25 bg-success-dim/20 text-fg"
            : "border-error/25 bg-error-dim/20 text-muted",
        )}
      >
        {output}
      </p>
    </div>
  );
}

// ── Killer flow ──────────────────────────────────────────────────────────────

const STEPS = [
  {
    icon: ScanLine,
    title: "Trace",
    body:
      "One decorator. Every LLM call, tool call and nested span lands in a single timeline with latency, tokens and cost — including async agents and streaming responses.",
  },
  {
    icon: GitBranch,
    title: "Branch",
    body:
      "Open a failed run and edit any span's output. Loupe freezes everything before that point, applies your edit, and re-runs the rest live against your real tools.",
  },
  {
    icon: SplitSquareHorizontal,
    title: "Diff",
    body:
      "Compare the two runs side by side — what the agent said, what changed, and what it cost. The same view powers prompt regression suites in CI.",
  },
];

function KillerFlow() {
  return (
    <section className="border-t border-line py-16 sm:py-24">
      <Reveal>
        <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
          Observability is step one
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          Most tools stop at showing you the trace. Loupe lets you change it and find
          out what would have happened.
        </p>
      </Reveal>

      <div className="mt-10 grid gap-4 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <Reveal key={s.title} index={i + 1}>
            <div className="h-full rounded-xl border border-line bg-surface/50 p-5 transition-colors hover:border-line-strong">
              <div className="grid size-9 place-items-center rounded-lg bg-primary-soft/40 text-primary">
                <s.icon className="size-4.5" />
              </div>
              <h3 className="mt-4 font-semibold tracking-tight">
                <span className="mr-2 font-mono text-xs text-faint">
                  {String(i + 1).padStart(2, "0")}
                </span>
                {s.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ── Footer ───────────────────────────────────────────────────────────────────

function LandingFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-xs text-faint sm:flex-row sm:items-center">
        <span>Loupe — observability and replay for LLM agents.</span>
        <nav className="flex gap-4 sm:ml-auto">
          <Link href="/traces" className="transition-colors hover:text-muted">
            Traces
          </Link>
          <Link href="/suites" className="transition-colors hover:text-muted">
            Suites
          </Link>
          <a href={GITHUB} target="_blank" rel="noreferrer" className="transition-colors hover:text-muted">
            GitHub
          </a>
          <a href={PYPI} target="_blank" rel="noreferrer" className="transition-colors hover:text-muted">
            PyPI
          </a>
        </nav>
      </div>
    </footer>
  );
}

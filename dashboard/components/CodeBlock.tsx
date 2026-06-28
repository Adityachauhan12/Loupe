"use client";

import { useState } from "react";
import { Check, Copy, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** Pretty-prints JSON or shows raw text, with copy + expand/collapse.
 *  Replaces the bare <pre> dumps scattered across the old views. */
export function CodeBlock({
  data,
  text,
  isError,
  collapsedHeight = 256,
  className,
}: {
  data?: unknown;
  text?: string;
  isError?: boolean;
  collapsedHeight?: number;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const content =
    text ?? (typeof data === "string" ? data : JSON.stringify(data ?? null, null, 2));
  const lineCount = content.split("\n").length;
  const longContent = lineCount > 14 || content.length > 900;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked — no-op */
    }
  };

  return (
    <div
      className={cn(
        "group relative rounded-lg border text-xs",
        isError
          ? "border-error/30 bg-error-dim/30"
          : "border-line bg-surface-2/80",
        className,
      )}
    >
      <button
        type="button"
        onClick={copy}
        aria-label="Copy to clipboard"
        className={cn(
          "absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium",
          "opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-visible:opacity-100",
          "border-line-strong bg-elevated/90 text-muted hover:text-fg backdrop-blur-sm",
        )}
      >
        {copied ? (
          <>
            <Check className="size-3 text-success" /> Copied
          </>
        ) : (
          <>
            <Copy className="size-3" /> Copy
          </>
        )}
      </button>

      <pre
        style={{ maxHeight: expanded ? undefined : collapsedHeight }}
        className={cn(
          "overflow-auto whitespace-pre-wrap break-words p-3 font-mono leading-relaxed",
          isError ? "text-error" : "text-muted",
          !expanded && longContent && "[mask-image:linear-gradient(to_bottom,black_70%,transparent)]",
        )}
      >
        {content}
      </pre>

      {longContent && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex w-full items-center justify-center gap-1 border-t border-line/60 py-1.5 text-[11px] font-medium text-faint transition-colors hover:text-fg"
        >
          <ChevronDown
            className={cn("size-3.5 transition-transform", expanded && "rotate-180")}
          />
          {expanded ? "Show less" : `Show all ${lineCount} lines`}
        </button>
      )}
    </div>
  );
}

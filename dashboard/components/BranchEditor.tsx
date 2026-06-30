"use client";

import { useState, useActionState } from "react";
import { GitBranch, ArrowRight, Loader2, AlertCircle, X } from "lucide-react";
import { createBranch } from "@/app/traces/[id]/actions";
import type { SpanOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ActionState = { error: string } | null;

export function BranchEditor({
  traceId,
  span,
}: {
  traceId: string;
  span: SpanOut;
}) {
  const [open, setOpen] = useState(false);
  const initial = JSON.stringify(span.output ?? {}, null, 2);

  const boundAction = createBranch.bind(null, traceId, span.id);
  const [state, formAction, isPending] = useActionState<ActionState, FormData>(
    async (_prev: ActionState, formData: FormData) => {
      const raw = (formData.get("new_output") as string | null) ?? "";
      try {
        JSON.parse(raw);
      } catch {
        return { error: "Edited output is not valid JSON — fix and retry." };
      }
      try {
        await boundAction(formData);
        return null;
      } catch (err: unknown) {
        if (err instanceof Error && err.message.includes("NEXT_REDIRECT")) throw err;
        return { error: err instanceof Error ? err.message : String(err) };
      }
    },
    null,
  );

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
      >
        <GitBranch className="size-3.5" />
        Branch from here
      </Button>
    );
  }

  return (
    <form
      action={formAction}
      className="space-y-2.5 rounded-lg border border-primary-strong/30 bg-primary-soft/15 p-3.5"
    >
      <div className="flex items-start gap-2">
        <GitBranch className="mt-0.5 size-4 shrink-0 text-primary" />
        <p className="text-[11px] leading-relaxed text-muted">
          <span className="font-medium text-fg">Preview branch (LLM-only).</span>{" "}
          Spans <span className="font-medium text-fg">before</span> are frozen and
          LLM calls <span className="font-medium text-fg">after</span> re-run, but
          your tool functions can&apos;t run on the server — they show as dry-run
          ghosts, so the edit won&apos;t propagate through tools. For a true branch
          where the edit flows through real tools, run{" "}
          <code className="rounded bg-surface-2 px-1 font-mono text-[10px]">loupe replay</code>{" "}
          from your code.
        </p>
      </div>
      <textarea
        name="new_output"
        defaultValue={initial}
        rows={8}
        spellCheck={false}
        className={cn(
          "w-full resize-y rounded-lg border border-line bg-surface-2 p-2.5 font-mono text-xs text-fg",
          "placeholder:text-faint focus:outline-none focus:ring-2 focus:ring-primary/40",
        )}
      />
      {state?.error && (
        <p className="flex items-start gap-1.5 text-xs text-error">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          {state.error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={isPending}>
          {isPending ? (
            <>
              <Loader2 className="size-3.5 animate-spin" />
              Branching…
            </>
          ) : (
            <>
              Continue
              <ArrowRight className="size-3.5" />
            </>
          )}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen(false)}
          disabled={isPending}
        >
          <X className="size-3.5" />
          Cancel
        </Button>
      </div>
    </form>
  );
}

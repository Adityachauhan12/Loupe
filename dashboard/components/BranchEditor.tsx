"use client";

import { useState } from "react";
import { useActionState } from "react";
import { createBranch } from "@/app/traces/[id]/actions";
import type { SpanOut } from "@/lib/api";

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
      // Validate client-side first for instant feedback.
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
        // redirect() throws a special Next.js error — let it propagate.
        if (err instanceof Error && err.message.includes("NEXT_REDIRECT")) {
          throw err;
        }
        return { error: err instanceof Error ? err.message : String(err) };
      }
    },
    null,
  );

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-2 text-[11px] px-2 py-1 rounded border border-indigo-700/50 text-indigo-300 hover:bg-indigo-900/30 transition-colors font-medium"
      >
        ⑂ Branch from here
      </button>
    );
  }

  return (
    <form action={formAction} className="mt-2 space-y-2">
      <p className="text-[11px] text-gray-500 leading-relaxed">
        Edit this span&apos;s output and continue. Everything{" "}
        <span className="text-gray-400">before</span> this span is frozen;
        everything <span className="text-gray-400">after</span> re-runs — writes
        are dry-run, so no real-world actions fire.
      </p>
      <textarea
        name="new_output"
        defaultValue={initial}
        rows={8}
        spellCheck={false}
        className="w-full rounded border border-gray-700 bg-gray-900 text-xs text-gray-200 p-2 font-mono placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 resize-y"
      />
      {state?.error && <p className="text-red-400 text-xs">{state.error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={isPending}
          className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium transition-colors"
        >
          {isPending ? "Branching…" : "Continue →"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={isPending}
          className="px-3 py-1.5 rounded text-xs text-gray-400 hover:text-gray-200 transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

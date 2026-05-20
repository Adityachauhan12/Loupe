"use client";

import { useActionState } from "react";
import { createReplay } from "@/app/traces/[id]/actions";

const MODELS = [
  { value: "original", label: "Original model (no change)" },
  // Anthropic
  { value: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
  { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
  { value: "claude-opus-4-5", label: "Claude Opus 4.5" },
  // OpenAI
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o mini" },
  // Groq
  { value: "llama3-70b-8192", label: "Llama 3 70B (Groq)" },
  { value: "llama3-8b-8192", label: "Llama 3 8B (Groq)" },
];

type ActionState = { error: string } | null;

export function ReplayForm({ traceId }: { traceId: string }) {
  const boundAction = createReplay.bind(null, traceId);
  const [state, formAction, isPending] = useActionState<ActionState, FormData>(
    async (_prev: ActionState, formData: FormData) => {
      try {
        await boundAction(formData);
        return null;
      } catch (err: unknown) {
        // redirect() throws a special Next.js error — let it propagate
        if (
          err instanceof Error &&
          err.message.includes("NEXT_REDIRECT")
        ) {
          throw err;
        }
        return { error: err instanceof Error ? err.message : String(err) };
      }
    },
    null
  );

  return (
    <form action={formAction} className="space-y-4">
      <div>
        <label className="block text-xs text-gray-500 uppercase tracking-widest font-semibold mb-1">
          System prompt override
          <span className="ml-1 font-normal normal-case text-gray-600">
            (optional — replaces the system message)
          </span>
        </label>
        <textarea
          name="prompt_override"
          rows={4}
          placeholder="You are a helpful assistant specialised in..."
          className="w-full rounded border border-gray-700 bg-gray-900 text-sm text-gray-200 p-3 font-mono placeholder:text-gray-600 focus:outline-none focus:border-gray-500 resize-y"
        />
      </div>

      <div>
        <label className="block text-xs text-gray-500 uppercase tracking-widest font-semibold mb-1">
          Model override
          <span className="ml-1 font-normal normal-case text-gray-600">(optional)</span>
        </label>
        <select
          name="model_override"
          defaultValue="original"
          className="rounded border border-gray-700 bg-gray-900 text-sm text-gray-200 px-3 py-2 focus:outline-none focus:border-gray-500"
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      {state?.error && (
        <p className="text-red-400 text-sm">{state.error}</p>
      )}

      <button
        type="submit"
        disabled={isPending}
        className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium transition-colors"
      >
        {isPending ? "Running replay…" : "Run Replay →"}
      </button>
    </form>
  );
}

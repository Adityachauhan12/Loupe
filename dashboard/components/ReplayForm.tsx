"use client";

import { useActionState, useState } from "react";
import { Play, Loader2, Cpu, AlertCircle } from "lucide-react";
import { createReplay } from "@/app/traces/[id]/actions";
import { Button } from "@/components/ui/button";
import { SectionLabel } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const MODELS = [
  { value: "original", label: "Original model (no change)", group: "" },
  { value: "llama-3.3-70b-versatile", label: "Llama 3.3 70B · Groq (free)", group: "Groq" },
  { value: "llama-3.1-8b-instant", label: "Llama 3.1 8B Instant · Groq (free)", group: "Groq" },
  { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 · cheap", group: "Anthropic" },
  { value: "claude-sonnet-4-5", label: "Claude Sonnet 4.5", group: "Anthropic" },
  { value: "gpt-4o-mini", label: "GPT-4o mini", group: "OpenAI" },
  { value: "gpt-4o", label: "GPT-4o", group: "OpenAI" },
];

type ActionState = { error: string } | null;

export function ReplayForm({
  traceId,
  currentModel,
  currentPrompt,
}: {
  traceId: string;
  currentModel?: string | null;
  currentPrompt?: string | null;
}) {
  const boundAction = createReplay.bind(null, traceId);
  const [model, setModel] = useState("original");
  const [prompt, setPrompt] = useState("");

  const [state, formAction, isPending] = useActionState<ActionState, FormData>(
    async (_prev: ActionState, formData: FormData) => {
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

  const promptChanged = prompt.trim().length > 0;
  const modelChanged = model !== "original";

  return (
    <form action={formAction} className="space-y-5">
      {/* What you're working from */}
      {(currentModel || currentPrompt) && (
        <div className="rounded-lg border border-line bg-surface-2/60 px-3.5 py-3 text-xs">
          <div className="flex items-center gap-1.5 text-faint">
            <Cpu className="size-3.5" />
            <span className="font-semibold uppercase tracking-[0.12em]">Currently</span>
          </div>
          <div className="mt-2 space-y-1.5">
            {currentModel && (
              <p className="flex gap-2">
                <span className="w-14 shrink-0 text-faint">model</span>
                <span className="font-mono text-muted">{currentModel}</span>
              </p>
            )}
            {currentPrompt && (
              <p className="flex gap-2">
                <span className="w-14 shrink-0 text-faint">prompt</span>
                <span className="line-clamp-2 font-mono text-muted">{currentPrompt}</span>
              </p>
            )}
          </div>
        </div>
      )}

      {/* System prompt override */}
      <div className="space-y-1.5">
        <label htmlFor="prompt_override" className="block">
          <SectionLabel className="inline">System prompt override</SectionLabel>
          <span className="ml-2 text-xs font-normal text-faint">
            optional — replaces the system message
          </span>
        </label>
        <textarea
          id="prompt_override"
          name="prompt_override"
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={currentPrompt ?? "You are a helpful assistant specialised in…"}
          className={cn(
            "w-full resize-y rounded-lg border bg-surface-2 p-3 font-mono text-sm text-fg",
            "placeholder:text-faint transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40",
            promptChanged ? "border-primary-strong/50" : "border-line",
          )}
        />
      </div>

      {/* Model override */}
      <div className="space-y-1.5">
        <label htmlFor="model_override" className="block">
          <SectionLabel className="inline">Model override</SectionLabel>
          <span className="ml-2 text-xs font-normal text-faint">optional</span>
        </label>
        <select
          id="model_override"
          name="model_override"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className={cn(
            "w-full rounded-lg border bg-surface-2 px-3 py-2.5 text-sm text-fg",
            "transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40 sm:w-auto sm:min-w-80",
            modelChanged ? "border-primary-strong/50" : "border-line",
          )}
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      {state?.error && (
        <p className="flex items-start gap-2 rounded-lg border border-error/30 bg-error-dim/30 px-3 py-2 text-sm text-error">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          {state.error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={isPending}>
          {isPending ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Running replay…
            </>
          ) : (
            <>
              <Play className="size-4" />
              Run replay
            </>
          )}
        </Button>
        {!isPending && (promptChanged || modelChanged) && (
          <span className="text-xs text-faint">
            {[modelChanged && "new model", promptChanged && "new prompt"]
              .filter(Boolean)
              .join(" + ")}{" "}
            will be applied
          </span>
        )}
      </div>
    </form>
  );
}

"use server";

import { redirect } from "next/navigation";

const API_BASE = process.env.LOUPE_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.LOUPE_API_KEY ?? "";

export async function createReplay(traceId: string, formData: FormData) {
  const promptOverride = (formData.get("prompt_override") as string | null)?.trim() || null;
  const modelOverride = (formData.get("model_override") as string | null) || null;

  const res = await fetch(`${API_BASE}/v1/replays`, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      original_trace_id: traceId,
      prompt_override: promptOverride,
      model_override: modelOverride === "original" ? null : modelOverride,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to create replay: ${res.status} ${text}`);
  }

  const data = (await res.json()) as { replay_id: string; new_trace_id: string };
  redirect(`/replays/${data.replay_id}`);
}

export async function createBranch(
  traceId: string,
  spanId: string,
  formData: FormData,
) {
  const raw = (formData.get("new_output") as string | null) ?? "";

  let newOutput: unknown;
  try {
    newOutput = JSON.parse(raw);
  } catch {
    throw new Error("Edited output is not valid JSON");
  }

  const res = await fetch(`${API_BASE}/v1/traces/${traceId}/branch`, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ span_id: spanId, new_output: newOutput }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to create branch: ${res.status} ${text}`);
  }

  const data = (await res.json()) as { replay_id: string; new_trace_id: string };
  // Land on the new branched trace — it auto-refreshes until the engine finishes.
  redirect(`/traces/${data.new_trace_id}`);
}

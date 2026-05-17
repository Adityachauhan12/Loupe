const API_BASE = process.env.LOUPE_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.LOUPE_API_KEY ?? "";

const headers = { "X-API-Key": API_KEY };

export interface TraceListItem {
  id: string;
  name: string | null;
  status: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  total_tokens: number | null;
  total_cost_usd: string | null;
  is_replay: boolean;
  replay_of_trace_id: string | null;
}

export interface TraceList {
  items: TraceListItem[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export async function getTraces(params: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<TraceList> {
  const url = new URL(`${API_BASE}/v1/traces`);
  if (params.status) url.searchParams.set("status", params.status);
  if (params.limit != null) url.searchParams.set("limit", String(params.limit));
  if (params.offset != null) url.searchParams.set("offset", String(params.offset));

  const res = await fetch(url.toString(), {
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /v1/traces failed: ${res.status}`);
  return res.json() as Promise<TraceList>;
}

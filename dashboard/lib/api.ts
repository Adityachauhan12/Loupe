const API_BASE = process.env.LOUPE_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.LOUPE_API_KEY ?? "";

const headers = { "X-API-Key": API_KEY };

// ── Traces list ────────────────────────────────────────────────────────────

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

  const res = await fetch(url.toString(), { headers, cache: "no-store" });
  if (!res.ok) throw new Error(`GET /v1/traces failed: ${res.status}`);
  return res.json() as Promise<TraceList>;
}

// ── Trace detail ───────────────────────────────────────────────────────────

export interface SpanOut {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  type: string;
  name: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  model: string | null;
  provider: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: string | null;
  metadata: Record<string, unknown> | null;
}

export interface TraceDetail {
  id: string;
  name: string | null;
  status: string | null;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  total_tokens: number | null;
  total_cost_usd: string | null;
  metadata: Record<string, unknown> | null;
  is_replay: boolean;
  replay_of_trace_id: string | null;
  branched_from_trace_id: string | null;
  branched_from_span_id: string | null;
  replay_mode: string | null;
  created_at: string;
  spans: SpanOut[];
}

export async function getTrace(id: string): Promise<TraceDetail> {
  const res = await fetch(`${API_BASE}/v1/traces/${id}`, {
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /v1/traces/${id} failed: ${res.status}`);
  return res.json() as Promise<TraceDetail>;
}

// ── Replay detail ──────────────────────────────────────────────────────────

export interface ReplayDetail {
  replay_id: string;
  original_trace_id: string;
  new_trace_id: string | null;
  modifications: { prompt_override?: string | null; model_override?: string | null } | null;
  diff_summary: { token_delta?: number; latency_delta_ms?: number; status?: string } | null;
  created_at: string;
}

export async function getReplay(id: string): Promise<ReplayDetail> {
  const res = await fetch(`${API_BASE}/v1/replays/${id}`, {
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /v1/replays/${id} failed: ${res.status}`);
  return res.json() as Promise<ReplayDetail>;
}

// ── Suites (v2.2 Prompt CI/CD) ─────────────────────────────────────────────

export interface SuiteListItem {
  id: string;
  name: string;
  judge_rubric: string | null;
  trace_count: number;
  created_at: string;
}

/** A run without its payload — what GET /v1/suites/{id}/runs returns. */
export interface SuiteRunSummary {
  id: string;
  suite_id: string;
  status: string;
  model_override: string | null;
  judge_backend: string | null;
  total: number;
  passed: number;
  regressed: number;
  improved: number;
  errored: number;
  started_at: string;
  ended_at: string | null;
  created_at: string;
}

/** One trace's verdict inside a run. `error` and the verdict fields are
 *  mutually exclusive — a trace that threw has no verdict to report. */
export interface SuiteRunResult {
  trace_id: string;
  new_trace_id?: string;
  verdict?: "equivalent" | "improved" | "regressed";
  score_source?: string;
  reasoning?: string;
  confidence?: number;
  error?: string;
}

export interface SuiteRunDetail extends SuiteRunSummary {
  prompt_override: string | null;
  results: SuiteRunResult[] | null;
  error: Record<string, unknown> | null;
}

export async function getSuites(): Promise<SuiteListItem[]> {
  const res = await fetch(`${API_BASE}/v1/suites`, { headers, cache: "no-store" });
  if (!res.ok) throw new Error(`GET /v1/suites failed: ${res.status}`);
  return res.json() as Promise<SuiteListItem[]>;
}

export async function getSuite(id: string): Promise<SuiteListItem> {
  const res = await fetch(`${API_BASE}/v1/suites/${id}`, { headers, cache: "no-store" });
  if (!res.ok) throw new Error(`GET /v1/suites/${id} failed: ${res.status}`);
  return res.json() as Promise<SuiteListItem>;
}

export async function getSuiteRuns(
  suiteId: string,
  limit = 20,
): Promise<SuiteRunSummary[]> {
  const res = await fetch(`${API_BASE}/v1/suites/${suiteId}/runs?limit=${limit}`, {
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /v1/suites/${suiteId}/runs failed: ${res.status}`);
  return res.json() as Promise<SuiteRunSummary[]>;
}

export async function getSuiteRun(id: string): Promise<SuiteRunDetail> {
  const res = await fetch(`${API_BASE}/v1/suite_runs/${id}`, {
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /v1/suite_runs/${id} failed: ${res.status}`);
  return res.json() as Promise<SuiteRunDetail>;
}

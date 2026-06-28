"""
Benchmark: API ingestion + query latency against the live Loupe server.

Measures p50 / p95 / p99 for:
  - POST /v1/traces  (ingest a trace with 3 spans)
  - GET  /v1/traces  (list traces)

Also measures throughput: how many ingest requests/sec the server handles.

Usage:
    python3 benchmarks/api_latency.py
"""

import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx

HOST = "https://loupe-server.onrender.com"
API_KEY = "lp_W4UJ4t7NymBlVOxhTecvRjDfKXvaQ6k-r_UH_-O64GI"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

WARMUP = 5
SAMPLES = 100
CONCURRENCY = 10  # for throughput test


def make_trace_payload() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    trace_id = str(uuid.uuid4())
    return {
        "id": trace_id,
        "name": "benchmark_trace",
        "status": "success",
        "input": {"query": "benchmark"},
        "output": {"result": "ok"},
        "started_at": now,
        "ended_at": now,
        "duration_ms": 100,
        "total_tokens": 50,
        "spans": [
            {
                "id": str(uuid.uuid4()),
                "trace_id": trace_id,
                "type": "llm",
                "name": "groq.chat",
                "started_at": now,
                "ended_at": now,
                "duration_ms": 80,
                "model": "llama-3.3-70b-versatile",
                "provider": "groq",
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "total_tokens": 50,
            }
        ],
    }


def percentile(data: list[float], p: int) -> float:
    return round(statistics.quantiles(sorted(data), n=100)[p - 1], 1)


def print_stats(label: str, times_ms: list[float]) -> None:
    print(f"\n{label}")
    print(f"  samples : {len(times_ms)}")
    print(f"  p50     : {percentile(times_ms, 50)} ms")
    print(f"  p95     : {percentile(times_ms, 95)} ms")
    print(f"  p99     : {percentile(times_ms, 99)} ms")
    print(f"  min     : {round(min(times_ms), 1)} ms")
    print(f"  max     : {round(max(times_ms), 1)} ms")


def bench_ingest(client: httpx.Client) -> float:
    payload = make_trace_payload()
    t0 = time.perf_counter()
    r = client.post(f"{HOST}/v1/traces", json=payload, headers=HEADERS)
    ms = (time.perf_counter() - t0) * 1000
    assert r.status_code in (200, 201), f"ingest failed: {r.status_code} {r.text[:200]}"
    return ms


def bench_query(client: httpx.Client) -> float:
    t0 = time.perf_counter()
    r = client.get(f"{HOST}/v1/traces", headers=HEADERS)
    ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200, f"query failed: {r.status_code} {r.text}"
    return ms


def main() -> None:
    print("Loupe API Benchmark")
    print("===================")
    print(f"Host    : {HOST}")
    print(f"Samples : {SAMPLES}  (+ {WARMUP} warmup)")

    # warm-up uses a long timeout — Render free tier can take 60s+ to wake
    with httpx.Client(timeout=120) as warmup_client:
        print(f"\nWarming up ({WARMUP} requests, up to 120s per call for cold start)...", end="", flush=True)
        for _ in range(WARMUP):
            try:
                bench_ingest(warmup_client)
                print(".", end="", flush=True)
            except httpx.ReadTimeout:
                print("T", end="", flush=True)  # timed out, server still waking
        print(" done")

    with httpx.Client(timeout=30) as client:

        # --- ingest latency ---
        print(f"\nRunning {SAMPLES} POST /v1/traces...", end="", flush=True)
        ingest_times: list[float] = []
        for _ in range(SAMPLES):
            ingest_times.append(bench_ingest(client))
            print(".", end="", flush=True)
        print_stats("POST /v1/traces  (ingest)", ingest_times)

        # --- query latency ---
        print(f"\nRunning {SAMPLES} GET /v1/traces...", end="", flush=True)
        query_times: list[float] = []
        for _ in range(SAMPLES):
            query_times.append(bench_query(client))
            print(".", end="", flush=True)
        print_stats("GET /v1/traces  (query)", query_times)

    # --- throughput: concurrent ingests ---
    print(f"\nThroughput test: {SAMPLES} concurrent requests (concurrency={CONCURRENCY})...")
    t_start = time.perf_counter()
    errors = 0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        with httpx.Client(timeout=30) as client:
            futures = [pool.submit(bench_ingest, client) for _ in range(SAMPLES)]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    errors += 1
    elapsed = time.perf_counter() - t_start
    rps = round(SAMPLES / elapsed, 1)
    print(f"  {SAMPLES} requests in {round(elapsed, 2)}s → {rps} req/s  (errors: {errors})")

    print("\nDone. Copy the p95 numbers to your resume.")


if __name__ == "__main__":
    main()

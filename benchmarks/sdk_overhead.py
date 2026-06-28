"""
Benchmark: Loupe SDK instrumentation overhead.

Mocks the Groq HTTP response so calls return instantly — this isolates
the pure in-process cost of Loupe's wrapping: span object creation,
context-var reads, serialization, and queuing to the background flush thread.

No real LLM calls are made. No API credits are burned.

Usage:
    python3 benchmarks/sdk_overhead.py
"""

import os
import statistics
import sys
import time
import types
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../sdk"))

SAMPLES = 500
WARMUP = 50


def make_mock_groq_response() -> MagicMock:
    """Fake Groq ChatCompletion response that matches the shape Loupe reads."""
    choice = MagicMock()
    choice.message.content = "yes"
    choice.message.role = "assistant"

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 3
    usage.total_tokens = 13

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = "llama-3.3-70b-versatile"
    return resp


def percentile(data: list[float], p: int) -> float:
    return round(statistics.quantiles(sorted(data), n=100)[p - 1], 3)


def print_stats(label: str, times: list[float]) -> None:
    print(f"\n{label}  (n={len(times)})")
    print(f"  p50 : {percentile(times, 50)} ms")
    print(f"  p95 : {percentile(times, 95)} ms")
    print(f"  p99 : {percentile(times, 99)} ms")
    print(f"  min : {round(min(times), 3)} ms")
    print(f"  max : {round(max(times), 3)} ms")


def main() -> None:
    print("Loupe SDK Overhead Benchmark")
    print("============================")
    print(f"Method  : mocked Groq response (no network, no API calls)")
    print(f"Samples : {SAMPLES}  (+ {WARMUP} warmup per phase)\n")

    mock_resp = make_mock_groq_response()
    messages = [{"role": "user", "content": "Reply with one word: yes"}]

    # ── patch Groq's internal HTTP call so it returns instantly ───────────
    with patch(
        "groq._base_client.SyncAPIClient.request",
        return_value=mock_resp,
    ):
        from groq import Groq
        client = Groq(api_key="sk-fake")

        def call_baseline() -> float:
            t0 = time.perf_counter()
            client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=5,
            )
            return (time.perf_counter() - t0) * 1000

        # ── Phase 1: baseline ─────────────────────────────────────────────
        print(f"Baseline warmup ({WARMUP})...", end="", flush=True)
        for _ in range(WARMUP):
            call_baseline()
        print(" done")

        print(f"Baseline ({SAMPLES} calls)...", end="", flush=True)
        baseline: list[float] = []
        for _ in range(SAMPLES):
            baseline.append(call_baseline())
        print(" done")
        print_stats("Baseline (no Loupe)", baseline)

        # ── Phase 2: instrumented ─────────────────────────────────────────
        import loupe
        from loupe.integrations.groq import instrument_groq

        loupe.init(api_key="lp_benchmark", host="http://localhost:19999")
        instrument_groq(client)

        @loupe.trace(name="bench")
        def call_instrumented() -> float:
            t0 = time.perf_counter()
            client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=5,
            )
            return (time.perf_counter() - t0) * 1000

        print(f"\nInstrumented warmup ({WARMUP})...", end="", flush=True)
        for _ in range(WARMUP):
            call_instrumented()
        print(" done")

        print(f"Instrumented ({SAMPLES} calls)...", end="", flush=True)
        instrumented: list[float] = []
        for _ in range(SAMPLES):
            instrumented.append(call_instrumented())
        print(" done")
        print_stats("Instrumented (with Loupe)", instrumented)

    # ── Delta ─────────────────────────────────────────────────────────────
    p50_delta = round(percentile(instrumented, 50) - percentile(baseline, 50), 3)
    p95_delta = round(percentile(instrumented, 95) - percentile(baseline, 95), 3)
    print(f"\nOverhead added by Loupe instrumentation:")
    print(f"  p50 delta : {p50_delta:+.3f} ms")
    print(f"  p95 delta : {p95_delta:+.3f} ms")
    print("\nDone. (Connection refused errors below are expected — dummy flush host.)")


if __name__ == "__main__":
    main()

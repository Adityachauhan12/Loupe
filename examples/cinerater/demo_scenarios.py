"""Demo scenarios that *prove* Loupe's branch + replay re-execute correctly.

Each scenario lands two linked traces in the dashboard so you can open the diff
and watch an upstream change ripple downstream:

  BRANCH  (changing content) — edit an upstream span's output, then re-run
          everything after it for real. We branch the *parse* LLM span (the
          routing decision), so the live `search_movies` tool and the final
          recommendation genuinely re-execute with the new value.

  REPLAY  (changing the query/instruction) — override the system prompt and
          re-run the LLM steps, tools frozen, to see the answer change.

Why we branch the parse LLM span and not the search tool:
  Provider LLM spans short-circuit in replay (the edited output is returned and
  flows downstream). `loupe.span()` tool blocks still execute their body, so
  editing a tool span only changes what's *recorded*, not what flows on. The
  parse span is the real upstream lever here.

Run from the repo root (server + dashboard must be up):

    python -m examples.cinerater.demo_scenarios
"""

from __future__ import annotations

import json
import os
import time

import httpx

import loupe
from loupe import core

# Importing the agent runs loupe.init() + instrument_groq() for us.
from examples.cinerater.agent import recommend

HOST = os.getenv("LOUPE_HOST", "http://localhost:8000").rstrip("/")
DASHBOARD = os.getenv("LOUPE_DASHBOARD", "http://localhost:3000").rstrip("/")
HEADERS = {"X-API-Key": os.environ["LOUPE_API_KEY"]}


# ── Server helpers ───────────────────────────────────────────────────────────

def _cinerater_ids() -> set[str]:
    r = httpx.get(f"{HOST}/v1/traces", params={"limit": 50}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return {t["id"] for t in r.json()["items"] if t["name"] == "cinerater" and not t["is_replay"]}


def run_original(query: str) -> tuple[str, str]:
    """Run the agent for real and return (trace_id, recommendation)."""
    before = _cinerater_ids()
    print(f"  ▸ running agent for: {query!r}")
    rec = recommend(query)
    core._client._queue.join()  # wait for the background flush to land

    for _ in range(20):
        new = _cinerater_ids() - before
        if new:
            return new.pop(), rec
        time.sleep(0.3)
    raise RuntimeError("original trace never appeared on the server")


def parse_span(trace_id: str) -> dict:
    """The first LLM span = the parse/routing step we branch from."""
    r = httpx.get(f"{HOST}/v1/traces/{trace_id}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    spans = sorted(r.json()["spans"], key=lambda s: s["started_at"])
    for s in spans:
        if s["type"] == "llm":
            return s
    raise RuntimeError("no LLM span found to branch from")


# ── Scenarios ────────────────────────────────────────────────────────────────

BRANCH_SCENARIOS = [
    {
        "title": "A · Genre re-route",
        "query": "recommend a great sci-fi movie",
        "edit": {"genre": "Romance"},
        "expect": "parse said Sci-Fi → we force Romance → search re-runs for Romance "
        "→ the recommendation becomes a romance film.",
    },
    {
        "title": "B · Tighten the filter",
        "query": "recommend a thriller",
        "edit": {"genre": "Thriller", "min_rating": 8.5},
        "expect": "same genre, but we add a rating floor → search narrows to the "
        "top-rated thrillers → a different, higher-rated pick.",
    },
]


def run_branch(scenario: dict) -> str:
    print(f"\n=== BRANCH {scenario['title']} ===")
    orig_id, orig_rec = run_original(scenario["query"])
    span = parse_span(orig_id)
    old_filters = (span.get("output") or {}).get("content", "<unknown>")
    print(f"  original parse output : {old_filters}")
    print(f"  original recommendation: {orig_rec[:90]}…")

    new_output = {"content": json.dumps(scenario["edit"])}
    new_id = loupe.replay(
        recommend,
        trace_id=orig_id,
        branch_span_id=span["id"],
        new_output=new_output,
    )
    core._client._queue.join()
    print(f"  edited parse output    : {new_output['content']}")
    print(f"  → why it matters: {scenario['expect']}")
    print(f"  ORIGINAL : {DASHBOARD}/traces/{orig_id}")
    print(f"  BRANCH   : {DASHBOARD}/traces/{new_id}")
    print(f"  DIFF     : {DASHBOARD}/traces/{new_id}/diff")
    return orig_id


def run_replay(trace_id: str) -> None:
    print("\n=== REPLAY C · Change the instruction (system prompt) ===")
    body = {
        "original_trace_id": trace_id,
        "prompt_override": (
            "You are CineRater. Reply in ONE terse sentence: the title and year only, "
            "no plot, no justification."
        ),
        "model_override": None,
    }
    r = httpx.post(f"{HOST}/v1/replays", json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    d = r.json()
    print("  overrode the write prompt → the final LLM step re-runs with a terser style.")
    print(f"  DIFF     : {DASHBOARD}/replays/{d['replay_id']}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    print("Loupe demo scenarios — upstream edits, downstream effects\n")
    first_original: str | None = None
    for sc in BRANCH_SCENARIOS:
        orig = run_branch(sc)
        first_original = first_original or orig

    if first_original:
        run_replay(first_original)

    print("\nOpen the DIFF links above to see each change propagate.")


if __name__ == "__main__":
    main()

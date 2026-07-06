"""JudgeService — scores a replayed output against the original (v2.2, B8.4).

Hybrid, two stages:
  1. Deterministic pre-check (free, no LLM): if the new output is identical to the
     original (after canonicalising JSON), the verdict is `equivalent` immediately.
     This nips the common "the prompt change didn't affect this trace" case for $0.
  2. LLM-as-judge (only when they differ): a single call scores the semantic verdict
     against a rubric and returns guaranteed-valid JSON `{label, reasoning, confidence}`.

Pluggable backend (`"<provider>/<model>"`):
  - "groq/<model>"   — free, the default (zero-cost dev + self-host). OpenAI-compatible
                       JSON mode.
  - "claude/<model>" — opt-in quality upgrade; Anthropic structured output
                       (`output_config.format`) guarantees schema-valid JSON.

See ARCHITECTURE_DECISIONS.md B8.4. Provider-call code is deliberately kept local
(not imported from the router) — bounded duplication per B4.
"""
from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.config import settings

Verdict_Label = Literal["equivalent", "improved", "regressed"]

# B8.3: the global default rubric. A suite may override it (suites.judge_rubric).
DEFAULT_RUBRIC = """You are grading whether a prompt change improved, regressed, or left \
unchanged an LLM agent's answer, by comparing the NEW output against the ORIGINAL output \
for the same input.

Grade on these criteria:
- Correctness & intent: does the new output still correctly address the user's input?
- Usability: is it still valid/usable by downstream code (e.g. same JSON shape/keys when \
the original was structured)?
- Completeness: did it drop information the original had, or add useful information?

Return exactly one label:
- "equivalent" — same meaning and usability; differences are cosmetic.
- "improved"   — clearly better (more correct, more complete, or more usable).
- "regressed"  — clearly worse (wrong, broken shape, or lost important information).
"""

# JSON Schema for the verdict — used for Anthropic structured output and to validate
# whatever the Groq JSON-mode call returns.
_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["equivalent", "improved", "regressed"]},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["label", "reasoning", "confidence"],
    "additionalProperties": False,
}


class Verdict(BaseModel):
    label: Verdict_Label
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    # 'deterministic' (free pre-check) or 'judge' (LLM). Set by the service.
    score_source: str = "judge"


class JudgeError(RuntimeError):
    """Raised when the judge cannot produce a verdict (missing key, bad response)."""


# ── backend parsing ────────────────────────────────────────────────────────

def parse_backend(backend: str | None) -> tuple[str, str]:
    """'groq/llama-3.3-70b-versatile' -> ('groq', 'llama-3.3-70b-versatile').

    'claude/...' is normalised to provider 'anthropic'. Falls back to the
    configured default when `backend` is None/empty.
    """
    spec = (backend or settings.judge_backend).strip()
    provider, _, model = spec.partition("/")
    provider = provider.lower()
    if provider == "claude":
        provider = "anthropic"
    if not model:
        raise JudgeError(f"invalid judge backend {spec!r}; expected '<provider>/<model>'")
    return provider, model


# ── deterministic pre-check (free) ─────────────────────────────────────────

def _canonical(value: Any) -> str:
    """Stable string for equality comparison: JSON with sorted keys when possible,
    else the raw string. Handles the {output} dict our spans store."""
    if value is None:
        return ""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def deterministic_check(original_output: Any, new_output: Any) -> Verdict | None:
    """Return a free 'equivalent' verdict if the outputs are identical, else None
    (escalate to the LLM judge)."""
    if _canonical(original_output) == _canonical(new_output):
        return Verdict(
            label="equivalent",
            reasoning="New output is byte-for-byte identical to the original "
            "(no LLM judgment needed).",
            confidence=1.0,
            score_source="deterministic",
        )
    return None


# ── LLM judge ──────────────────────────────────────────────────────────────

def _build_user_message(
    original_input: Any, original_output: Any, new_output: Any
) -> str:
    return (
        "INPUT (same for both):\n"
        f"{_canonical(original_input)}\n\n"
        "ORIGINAL OUTPUT:\n"
        f"{_canonical(original_output)}\n\n"
        "NEW OUTPUT (after the prompt change):\n"
        f"{_canonical(new_output)}\n\n"
        "Respond with a JSON object matching: "
        '{"label": "equivalent|improved|regressed", "reasoning": "<one or two '
        'sentences>", "confidence": <0.0-1.0>}.'
    )


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating surrounding prose."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise JudgeError(f"judge returned non-JSON response: {text[:200]!r}")


async def _call_groq_json(model: str, system: str, user: str) -> str:
    if not settings.groq_api_key:
        raise JudgeError("GROQ_API_KEY not configured in server .env")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key.strip()}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_anthropic_json(model: str, system: str, user: str) -> str:
    if not settings.anthropic_api_key:
        raise JudgeError("ANTHROPIC_API_KEY not configured in server .env")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key.strip(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                # Guaranteed schema-valid JSON (claude-api: output_config.format).
                "output_config": {
                    "format": {"type": "json_schema", "schema": _VERDICT_SCHEMA}
                },
            },
        )
        resp.raise_for_status()
        blocks = resp.json()["content"]
        return next(b["text"] for b in blocks if b.get("type") == "text")


async def judge(
    *,
    original_input: Any,
    original_output: Any,
    new_output: Any,
    rubric: str | None = None,
    backend: str | None = None,
) -> Verdict:
    """Score `new_output` vs `original_output`. Deterministic pre-check first;
    on a difference, a single LLM judge call. Raises JudgeError on failure."""
    pre = deterministic_check(original_output, new_output)
    if pre is not None:
        return pre

    provider, model = parse_backend(backend)
    system = (rubric or DEFAULT_RUBRIC).strip()
    user = _build_user_message(original_input, original_output, new_output)

    if provider == "groq":
        raw = await _call_groq_json(model, system, user)
    elif provider == "anthropic":
        raw = await _call_anthropic_json(model, system, user)
    else:
        raise JudgeError(f"unsupported judge provider {provider!r}")

    data = _extract_json(raw)
    try:
        verdict = Verdict(**{**data, "score_source": "judge"})
    except Exception as exc:  # noqa: BLE001 — surface any validation failure uniformly
        raise JudgeError(f"judge returned an invalid verdict: {data!r} ({exc})") from exc
    return verdict

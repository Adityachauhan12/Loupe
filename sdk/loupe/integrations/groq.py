from __future__ import annotations

import functools
from decimal import Decimal
from typing import Any

from loupe.core import span

# Cost per 1M tokens (input, output). Groq pricing as of May 2026.
_COST_PER_M: dict[str, tuple[float, float]] = {
    "llama3-8b":               (0.05,  0.10),
    "llama3-70b":              (0.59,  0.79),
    "llama-3.1-8b":            (0.05,  0.08),
    "llama-3.1-70b":           (0.59,  0.79),
    "llama-3.3-70b":           (0.59,  0.79),
    "llama-3.2-1b":            (0.04,  0.04),
    "llama-3.2-3b":            (0.06,  0.06),
    "mixtral-8x7b":            (0.24,  0.24),
    "gemma-7b":                (0.07,  0.07),
    "gemma2-9b":               (0.20,  0.20),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    for prefix, (input_rate, output_rate) in _COST_PER_M.items():
        if model.startswith(prefix):
            cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
            return Decimal(str(round(cost, 6)))
    return None


def instrument_groq(client: Any) -> None:
    """
    Patch a Groq client instance so every chat completion is automatically
    recorded as a Loupe LLM span.

    Usage:
        from groq import Groq
        client = Groq()
        loupe.instrument_groq(client)
    """
    original_create = client.chat.completions.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        with span("groq.chat", type="llm") as s:
            s.provider = "groq"
            s.model = model
            s.input = {"messages": messages}

            response = original_create(*args, **kwargs)

            usage = getattr(response, "usage", None)
            if usage:
                s.prompt_tokens = getattr(usage, "prompt_tokens", None)
                s.completion_tokens = getattr(usage, "completion_tokens", None)
                s.total_tokens = getattr(usage, "total_tokens", None)
                if s.prompt_tokens and s.completion_tokens:
                    s.cost_usd = _estimate_cost(
                        model, s.prompt_tokens, s.completion_tokens
                    )

            choices = getattr(response, "choices", [])
            if choices:
                msg = getattr(choices[0], "message", None)
                s.output = {"content": getattr(msg, "content", None)}

        return response

    client.chat.completions.create = patched_create

from __future__ import annotations

import functools
from decimal import Decimal
from typing import Any

from loupe.core import span

# Cost per 1M tokens (input, output) for common models.
# These are approximate — update as pricing changes.
_COST_PER_M: dict[str, tuple[float, float]] = {
    "gpt-4o":            (2.50,  10.00),
    "gpt-4o-mini":       (0.15,   0.60),
    "gpt-4-turbo":      (10.00,  30.00),
    "gpt-4":            (30.00,  60.00),
    "gpt-3.5-turbo":     (0.50,   1.50),
    "o1":               (15.00,  60.00),
    "o1-mini":           (3.00,  12.00),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    for prefix, (input_rate, output_rate) in _COST_PER_M.items():
        if model.startswith(prefix):
            cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
            return Decimal(str(round(cost, 6)))
    return None


def instrument_openai(client: Any) -> None:
    """
    Patch an OpenAI client instance so every chat completion is
    automatically recorded as a Loupe LLM span.

    Usage:
        from openai import OpenAI
        client = OpenAI()
        loupe.instrument_openai(client)
    """
    original_create = client.chat.completions.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        with span(f"openai.chat", type="llm") as s:  # noqa: F541
            s.provider = "openai"
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

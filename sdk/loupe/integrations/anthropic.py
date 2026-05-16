from __future__ import annotations

import functools
from decimal import Decimal
from typing import Any

from loupe.core import span

_COST_PER_M: dict[str, tuple[float, float]] = {
    "claude-opus-4":     (15.00,  75.00),
    "claude-sonnet-4":    (3.00,  15.00),
    "claude-haiku-4":     (0.80,   4.00),
    "claude-3-5-sonnet": (3.00,  15.00),
    "claude-3-5-haiku":  (0.80,   4.00),
    "claude-3-opus":    (15.00,  75.00),
    "claude-3-sonnet":   (3.00,  15.00),
    "claude-3-haiku":    (0.25,   1.25),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    for prefix, (input_rate, output_rate) in _COST_PER_M.items():
        if model.startswith(prefix):
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
            return Decimal(str(round(cost, 6)))
    return None


def instrument_anthropic(client: Any) -> None:
    """
    Patch an Anthropic client instance so every messages.create call is
    automatically recorded as a Loupe LLM span.

    Usage:
        import anthropic
        client = anthropic.Anthropic()
        loupe.instrument_anthropic(client)
    """
    original_create = client.messages.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])
        system = kwargs.get("system")

        inp: dict[str, Any] = {"messages": messages}
        if system:
            inp["system"] = system

        with span("anthropic.messages", type="llm") as s:
            s.provider = "anthropic"
            s.model = model
            s.input = inp

            response = original_create(*args, **kwargs)

            usage = getattr(response, "usage", None)
            if usage:
                s.prompt_tokens = getattr(usage, "input_tokens", None)
                s.completion_tokens = getattr(usage, "output_tokens", None)
                s.total_tokens = (s.prompt_tokens or 0) + (s.completion_tokens or 0) or None
                if s.prompt_tokens and s.completion_tokens:
                    s.cost_usd = _estimate_cost(
                        model, s.prompt_tokens, s.completion_tokens
                    )

            content = getattr(response, "content", [])
            if content:
                s.output = {"content": getattr(content[0], "text", str(content[0]))}

        return response

    client.messages.create = patched_create

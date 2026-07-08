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
    # Groq-hosted open models (Groq's published per-1M-token rates).
    "llama-3.3-70b":     (0.59,   0.79),
    "llama-3.1-8b":      (0.05,   0.08),
    "llama-3.1-70b":     (0.59,   0.79),
    "llama3-70b":        (0.59,   0.79),
    "llama3-8b":         (0.05,   0.08),
    "mixtral-8x7b":      (0.24,   0.24),
    "gemma2-9b":         (0.20,   0.20),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    for prefix, (input_rate, output_rate) in _COST_PER_M.items():
        if model.startswith(prefix):
            cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
            return Decimal(str(round(cost, 6)))
    return None


def instrument_openai(client: Any, provider: str = "openai") -> None:
    """
    Patch an OpenAI client instance so every chat completion is
    automatically recorded as a Loupe LLM span.

    `provider` labels the span's provider field. Pass ``provider="groq"``
    when the OpenAI SDK is pointed at Groq's OpenAI-compatible endpoint,
    so traces report the real backend rather than "openai".

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

        with span(f"{provider}.chat", type="llm") as s:
            s.provider = provider
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
                output: dict[str, Any] = {"content": getattr(msg, "content", None)}
                # Capture tool calls too — for agentic loops the content is
                # often None and the useful signal is which tool was chosen.
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    output["tool_calls"] = [
                        {
                            "name": getattr(getattr(tc, "function", None), "name", None),
                            "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                        }
                        for tc in tool_calls
                    ]
                s.output = output

        return response

    client.chat.completions.create = patched_create

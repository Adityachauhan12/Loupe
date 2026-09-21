"""Why a completion ended, recorded alongside the span.

A span whose output is ``{"content": ""}`` tells you the model said nothing.
It does not tell you why, and the difference matters: a refusal, a content
filter and a truncation all look identical in the output field.

The case that produced this module: an app moved from a non-reasoning model to
``openai/gpt-oss-120b`` and kept its old ``max_tokens``. That model writes a
hidden reasoning pass before the answer, and both are paid from the same
budget, so the reasoning consumed all of it and the answer came back empty with
``finish_reason="length"``. Every caller fell back to a default and carried on,
no exception, clean logs. It took hours to find. The one word ``length`` on the
span would have made it obvious.

We record the reason and the size of the reasoning pass — never the reasoning
text itself, which is long, often not meant to be shown, and would bloat every
span for the one case where it matters.
"""

from typing import Any


def completion_metadata(
    choice: Any,
    content: Any,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return span metadata describing how a completion ended.

    `choice` is a provider's choice object (OpenAI-shaped) and `content` is
    whatever was extracted as the answer. Returns `existing` unchanged when
    there is nothing worth recording, so an ordinary completion does not carry
    metadata it does not need.
    """
    finish_reason = getattr(choice, "finish_reason", None)
    return _build(finish_reason, content, choice, existing)


def anthropic_completion_metadata(
    response: Any,
    content: Any,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Same, for Anthropic — which calls the field ``stop_reason``.

    Its value for a truncation is ``max_tokens`` rather than ``length``; the
    name is normalised so the dashboard and any query only deal with one
    vocabulary.
    """
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "max_tokens":
        stop_reason = "length"
    return _build(stop_reason, content, None, existing)


def _build(
    finish_reason: Any,
    content: Any,
    choice: Any,
    existing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(finish_reason, str):
        return existing

    # A turn that chose a tool returns no content on purpose — that is the
    # whole shape of an agentic step, not a failure. CineBot's tool loop would
    # otherwise flag every single hop.
    if finish_reason in ("tool_calls", "function_call"):
        return existing

    empty = not (content or "").strip() if isinstance(content, str) else not content
    truncated = finish_reason == "length"

    # A completion that stopped normally with an answer is the common case and
    # needs no metadata. Anything else is worth a line in the trace.
    if not truncated and not empty:
        return existing

    meta = dict(existing or {})
    meta["finish_reason"] = finish_reason
    if empty:
        meta["empty_answer"] = True
    if truncated and choice is not None:
        chars = _reasoning_chars(choice)
        if chars:
            # The smoking gun: a large reasoning pass next to an empty answer
            # means the budget went to reasoning, not that the model refused.
            meta["reasoning_chars"] = chars
    return meta


def _reasoning_chars(choice: Any) -> int | None:
    """Length of the reasoning pass, if the provider returned one.

    Reasoning models expose this under different names and the OpenAI SDK
    parks unknown fields in ``model_extra``, so check both.
    """
    message = getattr(choice, "message", None)
    if message is None:
        return None
    for source in (message, getattr(message, "model_extra", None) or {}):
        for key in ("reasoning", "reasoning_content"):
            value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
            if isinstance(value, str) and value:
                return len(value)
    return None

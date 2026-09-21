"""Tests for the finish-reason metadata recorded on LLM spans.

The scenario these exist for: an app moved to a reasoning model and kept its
old max_tokens, so the reasoning pass ate the whole budget and the answer came
back empty with finish_reason="length". Nothing raised; the span's only clue
was an empty content field. These tests pin the clue that was missing.
"""
from __future__ import annotations

from types import SimpleNamespace

from loupe.integrations._completion_meta import (
    anthropic_completion_metadata,
    completion_metadata,
)


def _choice(content, finish_reason="stop", reasoning=None, extra_style=False):
    """Build an OpenAI-shaped choice.

    `extra_style` puts the reasoning in `model_extra`, which is where the
    OpenAI SDK parks fields it does not know about — that is how Groq's
    gpt-oss responses actually arrive.
    """
    if extra_style:
        message = SimpleNamespace(content=content, model_extra={"reasoning": reasoning})
    else:
        message = SimpleNamespace(content=content, reasoning=reasoning, model_extra=None)
    return SimpleNamespace(message=message, finish_reason=finish_reason)


# ── the ordinary case stays clean ───────────────────────────────────────────

def test_normal_completion_records_nothing():
    """A completion that stopped with an answer needs no metadata at all —
    otherwise every span in every trace grows a field nobody reads."""
    assert completion_metadata(_choice("Paris."), "Paris.") is None


def test_normal_completion_leaves_existing_metadata_untouched():
    existing = {"replay": "stored_passthrough"}
    assert completion_metadata(_choice("Paris."), "Paris.", existing) == existing


# ── the case that cost hours ────────────────────────────────────────────────

def test_reasoning_model_ate_the_budget():
    """gpt-oss with max_tokens sized for a non-reasoning model: the reasoning
    pass consumes the budget and the answer is empty."""
    choice = _choice("", finish_reason="length", reasoning="x" * 1885, extra_style=True)
    meta = completion_metadata(choice, "")
    assert meta == {
        "finish_reason": "length",
        "empty_answer": True,
        "reasoning_chars": 1885,
    }


def test_truncated_but_non_empty_answer_is_still_flagged():
    """An answer cut mid-sentence is usually still parseable, but it is the
    reason JSON parsing fails two steps later — so it gets recorded too."""
    meta = completion_metadata(_choice('{"partial": tr', finish_reason="length"), '{"partial": tr')
    assert meta["finish_reason"] == "length"
    assert "empty_answer" not in meta


def test_empty_answer_without_truncation():
    """Empty for some other reason — a filter, a refusal — is recorded, but we
    do not invent a reasoning explanation for it."""
    meta = completion_metadata(_choice("", finish_reason="content_filter"), "")
    assert meta == {"finish_reason": "content_filter", "empty_answer": True}


def test_whitespace_only_answer_counts_as_empty():
    meta = completion_metadata(_choice("  \n ", finish_reason="length"), "  \n ")
    assert meta["empty_answer"] is True


def test_reasoning_read_from_a_plain_attribute_too():
    """Not every client parks unknown fields in model_extra."""
    choice = _choice("", finish_reason="length", reasoning="y" * 40)
    assert completion_metadata(choice, "")["reasoning_chars"] == 40


def test_missing_reasoning_is_simply_absent():
    choice = _choice("", finish_reason="length")
    meta = completion_metadata(choice, "")
    assert "reasoning_chars" not in meta


# ── shape tolerance ─────────────────────────────────────────────────────────

def test_provider_without_a_finish_reason_records_nothing():
    """Some OpenAI-compatible servers omit the field; recording None would be
    worse than recording nothing."""
    choice = SimpleNamespace(message=SimpleNamespace(content=""), finish_reason=None)
    assert completion_metadata(choice, "") is None


def test_tool_call_with_no_content_is_not_an_empty_answer():
    """An agentic turn returns tool_calls and no content on purpose. It stops
    with finish_reason='tool_calls', so it must not be flagged."""
    choice = _choice(None, finish_reason="tool_calls")
    assert completion_metadata(choice, None) is None


# ── anthropic speaks a different dialect ────────────────────────────────────

def test_anthropic_max_tokens_is_normalised_to_length():
    """Anthropic calls a truncation 'max_tokens'. One vocabulary downstream."""
    response = SimpleNamespace(stop_reason="max_tokens")
    meta = anthropic_completion_metadata(response, "")
    assert meta == {"finish_reason": "length", "empty_answer": True}


def test_anthropic_end_turn_records_nothing():
    response = SimpleNamespace(stop_reason="end_turn")
    assert anthropic_completion_metadata(response, "Here you go.") is None

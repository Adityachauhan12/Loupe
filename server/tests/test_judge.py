"""Tests for the JudgeService (v2.2, B8.4).

No network: the deterministic pre-check needs no LLM, and the LLM path is exercised
by monkeypatching the provider call. Covers the hybrid short-circuit, backend
parsing, JSON extraction, and verdict validation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services import judge as J


# ── deterministic pre-check ────────────────────────────────────────────────

def test_deterministic_identical_short_circuits():
    v = J.deterministic_check({"genre": "Sci-Fi"}, {"genre": "Sci-Fi"})
    assert v is not None
    assert v.label == "equivalent"
    assert v.score_source == "deterministic"
    assert v.confidence == 1.0


def test_deterministic_ignores_key_order():
    # Same content, different key order → still identical after canonicalisation.
    assert J.deterministic_check({"a": 1, "b": 2}, {"b": 2, "a": 1}) is not None


def test_deterministic_different_escalates():
    # Different content → None → caller must run the shape guard / LLM judge.
    assert J.deterministic_check({"genre": "Sci-Fi"}, {"genre": "Comedy"}) is None


# ── deterministic shape guard ──────────────────────────────────────────────

def test_shape_guard_json_to_prose_regresses():
    # The live-demo case: LLM span envelope {"content": <text>}; original text is
    # JSON, new text is prose → forced 'regressed', no LLM.
    v = J.shape_break_check(
        {"content": '{"genre": "Sci-Fi"}'},
        {"content": "Sounds like you're after a mind-bending sci-fi flick!"},
    )
    assert v is not None
    assert v.label == "regressed"
    assert v.score_source == "shape_guard"
    assert v.confidence == 1.0


def test_shape_guard_dropped_key_regresses():
    v = J.shape_break_check({"genre": "Sci-Fi", "year": 1982}, {"genre": "Sci-Fi"})
    assert v is not None
    assert v.label == "regressed"


def test_shape_guard_added_key_escalates():
    # Same shape preserved + an extra key → still valid JSON → let the LLM decide.
    assert J.shape_break_check(
        {"content": '{"genre": "Sci-Fi"}'},
        {"content": '{"genre": "Sci-Fi", "subgenre": "Cyberpunk"}'},
    ) is None


def test_shape_guard_value_change_escalates():
    # Both parse, same keys, different value → not a shape break → escalate.
    assert J.shape_break_check({"genre": "Sci-Fi"}, {"genre": "Comedy"}) is None


def test_shape_guard_object_to_array_regresses():
    # dict → list: key access on the original shape breaks → forced 'regressed'.
    v = J.shape_break_check({"content": '{"genre": "Sci-Fi"}'}, {"content": '["Sci-Fi"]'})
    assert v is not None and v.label == "regressed"


def test_shape_guard_list_to_list_escalates():
    # Same container type (array → array) → not a type break → escalate.
    assert J.shape_break_check({"content": "[1, 2]"}, {"content": "[1, 2, 3]"}) is None


def test_shape_guard_fenced_json_regresses_by_design():
    # Bare JSON → markdown-fenced JSON. Intentionally 'regressed': a downstream
    # json.loads(raw) on a ```json fence breaks. Strict-is-safer for a CI gate.
    v = J.shape_break_check(
        {"content": '{"genre": "Sci-Fi"}'},
        {"content": '```json\n{"genre": "Sci-Fi"}\n```'},
    )
    assert v is not None and v.label == "regressed"


def test_shape_guard_unstructured_original_escalates():
    # Original was already prose → nothing structured to protect → None.
    assert J.shape_break_check({"content": "just some prose"}, {"content": "other prose"}) is None


# ── backend parsing ────────────────────────────────────────────────────────

def test_parse_backend_groq():
    assert J.parse_backend("groq/llama-3.3-70b-versatile") == (
        "groq",
        "llama-3.3-70b-versatile",
    )


def test_parse_backend_claude_normalises_to_anthropic():
    assert J.parse_backend("claude/claude-sonnet-4-6") == (
        "anthropic",
        "claude-sonnet-4-6",
    )


def test_parse_backend_default_fallback():
    provider, model = J.parse_backend(None)
    assert provider == "groq"  # matches settings.judge_backend default


def test_parse_backend_invalid_raises():
    with pytest.raises(J.JudgeError):
        J.parse_backend("just-a-model-no-slash")


# ── JSON extraction ────────────────────────────────────────────────────────

def test_extract_json_plain():
    assert J._extract_json('{"label": "improved"}') == {"label": "improved"}


def test_extract_json_with_prose():
    text = 'Here is my verdict:\n{"label": "regressed", "confidence": 0.9}\nDone.'
    assert J._extract_json(text)["label"] == "regressed"


def test_extract_json_non_json_raises():
    with pytest.raises(J.JudgeError):
        J._extract_json("no json here")


# ── verdict validation ─────────────────────────────────────────────────────

def test_verdict_confidence_bounds():
    with pytest.raises(ValidationError):
        J.Verdict(label="improved", reasoning="x", confidence=1.5)


# ── judge() end-to-end ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_judge_deterministic_makes_no_llm_call():
    # Identical outputs → free verdict, provider call must NOT be invoked.
    with patch.object(J, "_call_groq_json", new=AsyncMock()) as mock_call:
        v = await J.judge(
            original_input={"q": "sci-fi movie"},
            original_output={"genre": "Sci-Fi"},
            new_output={"genre": "Sci-Fi"},
        )
    mock_call.assert_not_awaited()
    assert v.label == "equivalent"
    assert v.score_source == "deterministic"


@pytest.mark.asyncio
async def test_judge_shape_guard_makes_no_llm_call():
    # Structured original → prose new: the shape guard must catch it for free,
    # never reaching the LLM (this is the mis-grading the guard exists to prevent).
    with patch.object(J, "_call_groq_json", new=AsyncMock()) as mock_call:
        v = await J.judge(
            original_input={"q": "sci-fi movie"},
            original_output={"content": '{"genre": "Sci-Fi"}'},
            new_output={"content": "Oh, you want something mind-bending and sci-fi!"},
        )
    mock_call.assert_not_awaited()
    assert v.label == "regressed"
    assert v.score_source == "shape_guard"


@pytest.mark.asyncio
async def test_judge_llm_path_regressed():
    # Same JSON shape (guard doesn't fire), but a semantic regression only the LLM
    # can judge — so the provider IS called.
    canned = '{"label": "regressed", "reasoning": "Wrong genre for the query.", "confidence": 0.88}'
    with patch.object(J, "_call_groq_json", new=AsyncMock(return_value=canned)) as mock_call:
        v = await J.judge(
            original_input={"q": "sci-fi movie"},
            original_output={"content": '{"genre": "Sci-Fi"}'},
            new_output={"content": '{"genre": "Comedy"}'},
            backend="groq/llama-3.3-70b-versatile",
        )
    mock_call.assert_awaited_once()
    assert v.label == "regressed"
    assert v.score_source == "judge"
    assert 0.0 <= v.confidence <= 1.0


@pytest.mark.asyncio
async def test_judge_llm_path_anthropic_backend():
    canned = '{"label": "improved", "reasoning": "More complete.", "confidence": 0.7}'
    with patch.object(
        J, "_call_anthropic_json", new=AsyncMock(return_value=canned)
    ) as mock_call:
        v = await J.judge(
            original_input={"q": "x"},
            original_output={"a": 1},
            new_output={"a": 2},
            backend="claude/claude-sonnet-4-6",
        )
    mock_call.assert_awaited_once()
    assert v.label == "improved"


@pytest.mark.asyncio
async def test_judge_bad_verdict_raises():
    with patch.object(
        J, "_call_groq_json", new=AsyncMock(return_value='{"label": "nonsense"}')
    ):
        with pytest.raises(J.JudgeError):
            await J.judge(
                original_input={},
                original_output={"a": 1},
                new_output={"a": 2},
            )

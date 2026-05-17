"""
Smoke tests for instrument_groq — no real Groq API key required.
We mock client.chat.completions.create and verify Loupe records the span correctly.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import loupe
from loupe.integrations.groq import _estimate_cost, instrument_groq


# ---------------------------------------------------------------------------
# _estimate_cost
# ---------------------------------------------------------------------------

def test_estimate_cost_known_model():
    cost = _estimate_cost("llama3-70b-8192", 1_000_000, 1_000_000)
    assert cost == Decimal("1.380000")  # (0.59 + 0.79) / 1


def test_estimate_cost_unknown_model():
    assert _estimate_cost("some-future-model", 1000, 1000) is None


# ---------------------------------------------------------------------------
# instrument_groq — span capture
# ---------------------------------------------------------------------------

def _make_fake_response(model: str = "llama3-70b-8192") -> SimpleNamespace:
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    message = SimpleNamespace(content="The capital is Paris.")
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(usage=usage, choices=[choice], model=model)


def test_instrument_groq_records_span(tmp_path):
    """instrument_groq patches the client and a span is added to the active trace."""
    # Minimal Loupe init — point at a non-existent server; flush is sync so it'll
    # fail silently (no active trace in this unit test, flush is a no-op).
    loupe.init(api_key="test-key", host="http://localhost:19999")

    fake_client = MagicMock()
    fake_response = _make_fake_response()
    fake_client.chat.completions.create.return_value = fake_response

    instrument_groq(fake_client)

    # Capture spans flushed during the call.
    captured: list = []

    original_span = loupe.core.span  # type: ignore[attr-defined]

    with patch("loupe.integrations.groq.span") as mock_span_cls:
        mock_s = MagicMock()
        mock_span_cls.return_value.__enter__ = lambda *_: mock_s
        mock_span_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fake_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
        )

    mock_span_cls.assert_called_once_with("groq.chat", type="llm")
    assert mock_s.provider == "groq"
    assert mock_s.model == "llama3-70b-8192"
    assert mock_s.prompt_tokens == 100
    assert mock_s.completion_tokens == 50
    assert mock_s.total_tokens == 150
    assert mock_s.output == {"content": "The capital is Paris."}
    assert result is fake_response

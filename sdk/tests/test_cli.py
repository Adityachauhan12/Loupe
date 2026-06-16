"""Tests for the `loupe` CLI (loupe.cli)."""
from __future__ import annotations

import sys
import types

import pytest

from loupe import cli


def _install_fake_agent():
    mod = types.ModuleType("fake_agent_mod")

    def recommend(q):
        return q

    mod.recommend = recommend
    sys.modules["fake_agent_mod"] = mod
    return mod


def test_replay_cli_invokes_replay(monkeypatch, capsys):
    _install_fake_agent()
    captured: dict = {}

    def fake_replay(fn, *, trace_id, branch_span_id, new_output):
        captured.update(trace_id=trace_id, branch_span_id=branch_span_id, new_output=new_output)
        return "NEW-ID"

    import loupe
    from loupe import core

    monkeypatch.setattr(loupe, "replay", fake_replay)

    class FakeClient:
        def fetch_trace(self, tid):
            return {"status": "success", "spans": [1, 2, 3]}

    monkeypatch.setattr(core, "_client", FakeClient())

    cli.main([
        "replay", "--agent", "fake_agent_mod:recommend",
        "--trace", "T-123", "--span", "S-456", "--output", '{"content": "x"}',
    ])

    assert captured == {
        "trace_id": "T-123",
        "branch_span_id": "S-456",
        "new_output": {"content": "x"},
    }
    out = capsys.readouterr().out
    assert "branched trace created: NEW-ID" in out
    assert "status: success" in out


def test_replay_cli_rejects_bad_json(monkeypatch):
    _install_fake_agent()
    with pytest.raises(SystemExit, match="not valid JSON"):
        cli.main([
            "replay", "--agent", "fake_agent_mod:recommend",
            "--trace", "T", "--span", "S", "--output", "NOT-JSON",
        ])


def test_resolve_agent_requires_colon():
    with pytest.raises(SystemExit, match="package.module:function"):
        cli._resolve_agent("examples.cinerater.agent")

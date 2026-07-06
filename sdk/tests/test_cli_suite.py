"""Tests for the `loupe suite` CLI commands (v2.2).

No network: httpx.request is monkeypatched to a router that returns canned JSON per
(method, path). Covers create (trace selection + replay filtering), run (poll +
regression exit code), and diff.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from loupe import cli


class _Resp:
    def __init__(self, status: int, payload: Any):
        self.status_code = status
        self._payload = payload
        self.content = b"x" if payload is not None else b""
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> Any:
        return self._payload


def _router(routes: dict[tuple[str, str], Any], recorder: list[dict]):
    """Return an httpx.request replacement that dispatches on (method, path-substr)."""

    def _request(method: str, url: str, **kwargs: Any) -> _Resp:
        recorder.append({"method": method, "url": url, "json": kwargs.get("json")})
        for (m, sub), payload in routes.items():
            if m == method and sub in url:
                return _Resp(200, payload)
        return _Resp(404, {"detail": "not found"})

    return _request


def test_suite_create_filters_replays(monkeypatch, capsys):
    calls: list[dict] = []
    routes = {
        ("GET", "/v1/traces"): {
            "items": [
                {"id": "t1", "is_replay": False},
                {"id": "t2", "is_replay": True},   # replay → excluded
                {"id": "t3", "is_replay": False},
            ],
            "limit": 3, "offset": 0, "has_more": False,
        },
        ("POST", "/v1/suites"): {"suite_id": "sid-1"},
    }
    monkeypatch.setattr(cli.httpx, "request", _router(routes, calls))

    cli.main(["suite", "create", "--name", "g", "--from", "last:3",
              "--api-key", "k", "--host", "http://x"])

    post = next(c for c in calls if c["method"] == "POST")
    assert post["json"]["trace_ids"] == ["t1", "t3"]  # replay filtered out
    assert post["json"]["name"] == "g"
    assert "sid-1" in capsys.readouterr().out


def test_suite_create_requires_some_trace(monkeypatch):
    monkeypatch.setattr(cli.httpx, "request", _router({}, []))
    with pytest.raises(SystemExit, match="no traces selected"):
        cli.main(["suite", "create", "--name", "g", "--api-key", "k"])


def test_suite_run_exits_nonzero_on_regression(monkeypatch, tmp_path, capsys):
    prompt = tmp_path / "p.txt"
    prompt.write_text("new prompt")
    routes = {
        ("POST", "/run"): {"suite_run_id": "run-1"},
        ("GET", "/v1/suite_runs/"): {
            "status": "done", "total": 3, "passed": 2, "improved": 1,
            "regressed": 1, "errored": 0,
            "results": [
                {"trace_id": "t9", "new_trace_id": "n9", "verdict": "regressed",
                 "reasoning": "lost the genre field"},
            ],
        },
    }
    monkeypatch.setattr(cli.httpx, "request", _router(routes, []))

    with pytest.raises(SystemExit) as exc:
        cli.main(["suite", "run", "sid", "--prompt", str(prompt), "--api-key", "k"])
    assert exc.value.code == 1  # regression → non-zero for CI gating
    out = capsys.readouterr().out
    assert "2/3 passed" in out
    assert "regressed" in out and "t9" in out


def test_suite_run_exit_zero_when_clean(monkeypatch, tmp_path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("new prompt")
    routes = {
        ("POST", "/run"): {"suite_run_id": "run-2"},
        ("GET", "/v1/suite_runs/"): {
            "status": "done", "total": 2, "passed": 2, "improved": 0,
            "regressed": 0, "errored": 0, "results": [],
        },
    }
    monkeypatch.setattr(cli.httpx, "request", _router(routes, []))
    with pytest.raises(SystemExit) as exc:
        cli.main(["suite", "run", "sid", "--prompt", str(prompt), "--api-key", "k"])
    assert exc.value.code == 0


def test_suite_diff_shows_counts_and_changes(monkeypatch, capsys):
    routes = {
        ("GET", "/v1/suite_runs/runA"): {
            "total": 2, "passed": 2, "regressed": 0, "improved": 0, "errored": 0,
            "results": [{"trace_id": "t1", "verdict": "equivalent"}],
        },
        ("GET", "/v1/suite_runs/runB"): {
            "total": 2, "passed": 1, "regressed": 1, "improved": 0, "errored": 0,
            "results": [{"trace_id": "t1", "verdict": "regressed"}],
        },
    }
    monkeypatch.setattr(cli.httpx, "request", _router(routes, []))
    cli.main(["suite", "diff", "runA", "runB", "--api-key", "k"])
    out = capsys.readouterr().out
    assert "regressed" in out
    assert "equivalent → regressed" in out


def test_suite_missing_api_key(monkeypatch):
    monkeypatch.delenv("LOUPE_API_KEY", raising=False)
    monkeypatch.setattr(cli.httpx, "request", _router({("GET", "/v1/traces"): {}}, []))
    with pytest.raises(SystemExit, match="No API key"):
        cli.main(["suite", "create", "--name", "g", "--from", "last:1"])

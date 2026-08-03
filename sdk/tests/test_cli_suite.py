"""Tests for the `loupe suite` CLI commands (v2.2).

No network: httpx.request is monkeypatched to a router that returns canned JSON per
(method, path). Covers create (trace selection + replay filtering), run (poll +
regression exit code), and diff.
"""
from __future__ import annotations

import argparse
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


def test_host_and_key_strip_trailing_newline(monkeypatch, tmp_path):
    # Regression: a CI secret pasted with a trailing newline must not corrupt the
    # request URL (httpx.InvalidURL) or the X-API-Key header. Observed live in CI.
    prompt = tmp_path / "p.txt"
    prompt.write_text("new prompt")
    calls: list[dict] = []
    routes = {
        ("POST", "/run"): {"suite_run_id": "r"},
        ("GET", "/v1/suite_runs/"): {
            "status": "done", "total": 1, "passed": 1, "improved": 0,
            "regressed": 0, "errored": 0, "results": [],
        },
    }
    captured: list[dict] = []

    def _request(method, url, **kwargs):
        captured.append({"url": url, "headers": kwargs.get("headers")})
        return _router(routes, calls)(method, url, **kwargs)

    monkeypatch.setattr(cli.httpx, "request", _request)
    monkeypatch.setenv("LOUPE_HOST", "https://loupe-server.onrender.com\n")
    monkeypatch.setenv("LOUPE_API_KEY", "lp_secret\n")

    with pytest.raises(SystemExit):
        cli.main(["suite", "run", "sid", "--prompt", str(prompt)])

    assert all("\n" not in c["url"] for c in captured)
    assert all(c["headers"]["X-API-Key"] == "lp_secret" for c in captured)


@pytest.mark.parametrize(
    "env_var, broken",
    [
        ("LOUPE_API_KEY", "lp_bro\u2028ken"),
        ("LOUPE_HOST", "https://lou\u2028pe.example.com"),
    ],
)
def test_embedded_invisible_char_fails_with_a_readable_error(monkeypatch, env_var, broken):
    # U+2028 (LINE SEPARATOR) is what a browser inserts where a copied token
    # wraps. Without this guard it escapes as a UnicodeEncodeError from deep
    # inside the HTTP stack -- a traceback naming neither the value nor the cause.
    # Written as an escape on purpose: a literal U+2028 here would be invisible
    # to the next reader, which is the very bug under test.
    monkeypatch.setenv("LOUPE_API_KEY", "lp_secret")
    monkeypatch.setenv("LOUPE_HOST", "https://loupe.example.com")
    monkeypatch.setenv(env_var, broken)

    with pytest.raises(SystemExit) as exc:
        cli.main(["suite", "create", "--name", "g", "--from", "last:1"])

    message = str(exc.value)
    assert env_var in message
    assert "U+2028" in message
    # The value itself must never be echoed -- it may be a credential.
    assert "lp_bro" not in message


def test_surrounding_whitespace_is_stripped_not_rejected(monkeypatch):
    # The common, unambiguous case stays silent — only embedded junk errors.
    args = argparse.Namespace(host=" https://loupe.example.com/ \n", api_key="  lp_key\n")
    assert cli._host(args) == "https://loupe.example.com"
    assert cli._headers(args) == {"X-API-Key": "lp_key"}


def test_suite_missing_api_key(monkeypatch):
    monkeypatch.delenv("LOUPE_API_KEY", raising=False)
    monkeypatch.setattr(cli.httpx, "request", _router({("GET", "/v1/traces"): {}}, []))
    with pytest.raises(SystemExit, match="No API key"):
        cli.main(["suite", "create", "--name", "g", "--from", "last:1"])

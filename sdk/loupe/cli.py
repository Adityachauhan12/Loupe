"""Command-line interface for Loupe.

    loupe replay \
        --agent examples.cinerater.agent:recommend \
        --trace <trace_id> \
        --span <span_id> \
        --output '{"content": "{\"genre\": \"Romance\"}"}'

Re-runs a traced agent in-process from a branch point with an edited span
output, so the edit propagates through your real tools (see notes/25).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from typing import Any, Callable

import httpx


def _resolve_agent(target: str) -> Callable[..., Any]:
    """Import 'package.module:function' and return the function.

    Importing the module is intentional — it runs the agent's loupe.init() and
    instrument_* calls, wiring up the client and the LLM interception we need.
    """
    if ":" not in target:
        raise SystemExit("--agent must look like 'package.module:function'")
    module_name, fn_name = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise SystemExit(f"could not import '{module_name}': {exc}") from exc
    fn = getattr(module, fn_name, None)
    if not callable(fn):
        raise SystemExit(f"'{fn_name}' is not a callable in '{module_name}'")
    return fn


def _cmd_replay(args: argparse.Namespace) -> None:
    # Set env BEFORE importing the agent so its load_dotenv()/init() pick it up.
    if args.api_key:
        os.environ["LOUPE_API_KEY"] = args.api_key
    if args.host:
        os.environ["LOUPE_HOST"] = args.host

    try:
        new_output = json.loads(args.output)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--output is not valid JSON: {exc}") from exc

    agent_fn = _resolve_agent(args.agent)

    import loupe
    from loupe import core

    # Fallback: if the agent didn't call loupe.init(), do it from the env.
    if core._client is None:
        key = os.environ.get("LOUPE_API_KEY")
        if not key:
            raise SystemExit(
                "Loupe is not initialised. Either call loupe.init() in your agent "
                "module, or pass --api-key (and --host)."
            )
        loupe.init(api_key=key, host=os.environ.get("LOUPE_HOST", "http://localhost:8000"))

    new_id = loupe.replay(
        agent_fn,
        trace_id=args.trace,
        branch_span_id=args.span,
        new_output=new_output,
    )
    print(f"✓ branched trace created: {new_id}")

    # The trace is delivered by a background worker — poll until it lands so the
    # CLI exits with a confirmed result, not a maybe.
    host = os.environ.get("LOUPE_HOST", "http://localhost:8000").rstrip("/")
    for _ in range(20):
        try:
            detail = core._client.fetch_trace(str(new_id))
            print(f"  status: {detail.get('status')}  |  spans: {len(detail.get('spans', []))}")
            print(f"  view:   {host}/traces/{new_id}")
            return
        except Exception:
            time.sleep(0.5)
    print("  (still flushing in the background — check the dashboard shortly)")


# ── suite commands (v2.2 Prompt CI/CD) ─────────────────────────────────────
# Thin HTTP wrappers over the server's /v1/suites and /v1/suite_runs endpoints.


def _clean(value: str, label: str) -> str:
    """Strip surrounding whitespace, reject embedded invisible characters.

    Hosts and API keys are ASCII by spec, and header values get latin-1 encoded
    on the way out. So a stray U+2028 (browsers insert one where a copied token
    wraps) surfaces as a UnicodeEncodeError from deep inside the HTTP stack, or
    as an unexplained 403 — neither of which points at the real cause.

    Surrounding whitespace is stripped silently: a trailing newline on a secret
    pasted into a CI UI is common and unambiguous. An *embedded* odd character
    is not repairable — deleting it would silently send a different credential —
    so fail loudly instead, naming the character without echoing the value.
    """
    cleaned = value.strip()
    for i, ch in enumerate(cleaned):
        if not (32 <= ord(ch) < 127):
            raise SystemExit(
                f"{label} contains a non-printable character (U+{ord(ch):04X}) "
                f"at position {i}. This usually means it was copied from a "
                "browser and picked up an invisible line break. Re-copy the "
                "value and try again."
            )
    return cleaned


def _host(args: argparse.Namespace) -> str:
    host = args.host or os.environ.get("LOUPE_HOST", "http://localhost:8000")
    return _clean(host, "LOUPE_HOST").rstrip("/")


def _headers(args: argparse.Namespace) -> dict[str, str]:
    key = args.api_key or os.environ.get("LOUPE_API_KEY")
    if not key or not key.strip():
        raise SystemExit("No API key. Pass --api-key or set LOUPE_API_KEY.")
    return {"X-API-Key": _clean(key, "LOUPE_API_KEY")}


def _api(args: argparse.Namespace, method: str, path: str, body: Any = None) -> Any:
    url = f"{_host(args)}{path}"
    try:
        resp = httpx.request(method, url, headers=_headers(args), json=body, timeout=60.0)
    except httpx.HTTPError as exc:  # network / connection
        raise SystemExit(f"request to {url} failed: {exc}") from exc
    if resp.status_code >= 400:
        raise SystemExit(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else None


def _cmd_suite_create(args: argparse.Namespace) -> None:
    trace_ids: list[str] = list(args.trace or [])
    if args.from_:
        if not args.from_.startswith("last:"):
            raise SystemExit("--from must look like 'last:N' (e.g. last:100)")
        n = int(args.from_.split(":", 1)[1])
        data = _api(args, "GET", f"/v1/traces?limit={n}")
        # Golden suites should be real production traces, not prior replays.
        trace_ids += [t["id"] for t in data["items"] if not t.get("is_replay")]
    if not trace_ids:
        raise SystemExit("no traces selected — pass --from last:N and/or --trace <id>")

    rubric = None
    if args.rubric_file:
        with open(args.rubric_file, encoding="utf-8") as f:
            rubric = f.read()

    out = _api(
        args, "POST", "/v1/suites",
        {"name": args.name, "trace_ids": trace_ids, "judge_rubric": rubric},
    )
    print(f"✓ suite created: {out['suite_id']}  ({len(trace_ids)} traces)")


def _cmd_suite_run(args: argparse.Namespace) -> None:
    with open(args.prompt, encoding="utf-8") as f:
        prompt = f.read()
    body: dict[str, Any] = {"prompt_override": prompt}
    if args.model:
        body["model_override"] = args.model
    if args.backend:
        body["judge_backend"] = args.backend

    created = _api(args, "POST", f"/v1/suites/{args.suite_id}/run", body)
    run_id = created["suite_run_id"]
    print(f"▶ run started: {run_id}  (polling…)")

    # Async run (A5): poll the suite_run until it's done.
    for _ in range(600):  # ~10 min at 1s
        run = _api(args, "GET", f"/v1/suite_runs/{run_id}")
        if run["status"] != "running":
            break
        time.sleep(1)
    else:
        raise SystemExit("timed out waiting for the run to finish")

    if run["status"] == "error":
        raise SystemExit(f"run errored: {run.get('error')}")

    _print_run_summary(args, run)
    # Non-zero exit on any regression — lets CI/scripts gate on it.
    raise SystemExit(1 if run["regressed"] else 0)


def _print_run_summary(args: argparse.Namespace, run: dict[str, Any]) -> None:
    mark = "❌" if run["regressed"] else "✅"
    print(
        f"{mark} {run['passed']}/{run['total']} passed · "
        f"{run['improved']} improved · {run['regressed']} regressed · "
        f"{run['errored']} errored"
    )
    for r in run.get("results") or []:
        if r.get("verdict") == "regressed" or r.get("error"):
            tid = r["trace_id"]
            reason = r.get("reasoning") or r.get("error") or ""
            print(f"  - {r.get('verdict', 'error')}  trace {tid}  {reason[:80]}")
            if r.get("new_trace_id"):
                print(f"      diff: {_host(args)}/traces/{r['new_trace_id']}/diff")


def _cmd_suite_diff(args: argparse.Namespace) -> None:
    a = _api(args, "GET", f"/v1/suite_runs/{args.run_a}")
    b = _api(args, "GET", f"/v1/suite_runs/{args.run_b}")
    print(f"           run A ({args.run_a[:8]})   run B ({args.run_b[:8]})")
    for field in ("total", "passed", "regressed", "improved", "errored"):
        print(f"  {field:<10} {a[field]:<16} {b[field]}")

    # Per-trace verdict changes between the two runs.
    va = {r["trace_id"]: r.get("verdict") for r in (a.get("results") or [])}
    vb = {r["trace_id"]: r.get("verdict") for r in (b.get("results") or [])}
    changed = [(t, va[t], vb.get(t)) for t in va if t in vb and va[t] != vb.get(t)]
    if changed:
        print("\n  verdict changes:")
        for tid, x, y in changed:
            print(f"    trace {tid[:8]}: {x} → {y}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="loupe", description="Loupe CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser(
        "replay",
        help="Re-run a traced agent from a branch point with an edited span output",
    )
    replay.add_argument(
        "--agent", required=True,
        help="the @loupe.trace agent as 'package.module:function' "
             "(e.g. examples.cinerater.agent:recommend)",
    )
    replay.add_argument("--trace", required=True, help="original trace id to branch from")
    replay.add_argument("--span", required=True, help="span id to branch at (its output is replaced)")
    replay.add_argument("--output", required=True, help="new output for the branch span (JSON)")
    replay.add_argument("--api-key", default=None, help="LOUPE_API_KEY (default: from env)")
    replay.add_argument("--host", default=None, help="LOUPE_HOST (default: from env / localhost:8000)")
    replay.set_defaults(func=_cmd_replay)

    # ── suite (Prompt CI/CD) ──
    suite = sub.add_parser("suite", help="Golden-suite regression testing for prompts")
    suite_sub = suite.add_subparsers(dest="suite_command", required=True)

    def _add_conn(p: argparse.ArgumentParser) -> None:
        p.add_argument("--api-key", default=None, help="LOUPE_API_KEY (default: from env)")
        p.add_argument("--host", default=None, help="LOUPE_HOST (default: env / localhost:8000)")

    s_create = suite_sub.add_parser("create", help="Create a suite from traces")
    s_create.add_argument("--name", required=True, help="suite name")
    s_create.add_argument(
        "--from", dest="from_", default=None,
        help="snapshot recent traces, e.g. 'last:100' (excludes replays)",
    )
    s_create.add_argument(
        "--trace", action="append", default=None, help="explicit trace id (repeatable)"
    )
    s_create.add_argument("--rubric-file", default=None, help="optional per-suite rubric file")
    _add_conn(s_create)
    s_create.set_defaults(func=_cmd_suite_create)

    s_run = suite_sub.add_parser("run", help="Run a suite against a new prompt")
    s_run.add_argument("suite_id", help="suite id to run")
    s_run.add_argument("--prompt", required=True, help="file with the new prompt text")
    s_run.add_argument("--model", default=None, help="model override for the replay")
    s_run.add_argument(
        "--backend", default=None,
        help="judge backend override, e.g. 'claude/claude-sonnet-4-6'",
    )
    _add_conn(s_run)
    s_run.set_defaults(func=_cmd_suite_run)

    s_diff = suite_sub.add_parser("diff", help="Compare two suite runs")
    s_diff.add_argument("run_a", help="first suite_run id")
    s_diff.add_argument("run_b", help="second suite_run id")
    _add_conn(s_diff)
    s_diff.set_defaults(func=_cmd_suite_diff)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

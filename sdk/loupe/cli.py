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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

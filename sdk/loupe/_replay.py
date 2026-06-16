"""SDK-side deterministic replay.

Re-runs a traced agent *inside the user's own process* (where the real tool
functions live) so that an edit at a branch point actually propagates downstream.

The rule, applied span-by-span in execution order:

    before the branch point  → freeze  (return the stored output, don't execute)
    at the branch point       → edit    (return the user's edited output)
    after the branch point     → live    (execute for real)

The freeze/edit/live decision is made once per span as it *starts*, via a cursor
that walks the original trace's spans in order. core.span() and the provider
integrations consult these helpers at the single span chokepoint.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

FREEZE = "freeze"
EDIT = "edit"
LIVE = "live"


@dataclass
class _ReplayPlan:
    # Outputs of the original trace's spans, ordered by started_at.
    stored_outputs: list[dict[str, Any] | None]
    branch_index: int                       # index of the branch span in that order
    new_output: dict[str, Any]              # the user's edited output for the branch
    branched_from_trace_id: uuid.UUID
    branched_from_span_id: uuid.UUID
    cursor: int = 0                          # next span to classify
    new_trace_id: uuid.UUID | None = None    # set by the @trace wrapper on re-run
    # Stack of (mode, output) for currently-open spans so nested integrations
    # (e.g. an LLM call inside a span) can read the active decision.
    decision_stack: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)


_plan: ContextVar[_ReplayPlan | None] = ContextVar("_loupe_replay_plan", default=None)


def is_replaying() -> bool:
    return _plan.get() is not None


def set_plan(plan: _ReplayPlan) -> Token:
    return _plan.set(plan)


def reset_plan(token: Token) -> None:
    _plan.reset(token)


def get_plan() -> _ReplayPlan | None:
    return _plan.get()


def begin_span() -> tuple[str, dict[str, Any] | None]:
    """Classify the span that is just starting and advance the cursor.

    Returns (mode, output): mode is FREEZE/EDIT/LIVE; output is the value to use
    for FREEZE/EDIT (None for LIVE). Pushes the decision so current_frozen_output()
    can read it during the span body. No-op ('live', None) when not replaying.
    """
    plan = _plan.get()
    if plan is None:
        return (LIVE, None)

    i = plan.cursor
    plan.cursor += 1

    if i < plan.branch_index:
        out = plan.stored_outputs[i] if i < len(plan.stored_outputs) else None
        decision = (FREEZE, out)
    elif i == plan.branch_index:
        decision = (EDIT, plan.new_output)
    else:
        decision = (LIVE, None)

    plan.decision_stack.append(decision)
    return decision


def end_span() -> tuple[str, dict[str, Any] | None] | None:
    """Pop the decision for the span that is finishing."""
    plan = _plan.get()
    if plan is None or not plan.decision_stack:
        return None
    return plan.decision_stack.pop()


def current_frozen_output() -> dict[str, Any] | None:
    """For the span currently executing: the output to use instead of running it
    (FREEZE/EDIT), or None if it should run live. Read by provider integrations
    to decide whether to skip the real API call.
    """
    plan = _plan.get()
    if plan is None or not plan.decision_stack:
        return None
    mode, output = plan.decision_stack[-1]
    return output if mode in (FREEZE, EDIT) else None

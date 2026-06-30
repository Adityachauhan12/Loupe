"""
Tests for SDK-side deterministic replay (loupe.replay).

Sub-step 1: the freeze/edit/live decision core.
"""
from __future__ import annotations

import uuid

import types

import loupe
from loupe import _replay as replay
from loupe import core
from loupe._replay import _ReplayPlan


def _plan(branch_index: int) -> _ReplayPlan:
    return _ReplayPlan(
        stored_outputs=[{"content": "a"}, {"content": "b"}, {"r": 1}],
        branch_index=branch_index,
        new_output={"content": "EDIT"},
        branched_from_trace_id=uuid.uuid4(),
        branched_from_span_id=uuid.uuid4(),
    )


def test_not_replaying_by_default():
    assert replay.is_replaying() is False
    assert replay.begin_span() == ("live", None)
    assert replay.current_frozen_output() is None


def test_freeze_edit_live_sequence():
    token = replay.set_plan(_plan(branch_index=1))
    try:
        assert replay.is_replaying() is True
        # span 0: before branch → freeze with stored output
        assert replay.begin_span() == ("freeze", {"content": "a"})
        assert replay.current_frozen_output() == {"content": "a"}
        replay.end_span()
        # span 1: the branch → edited output
        assert replay.begin_span() == ("edit", {"content": "EDIT"})
        assert replay.current_frozen_output() == {"content": "EDIT"}
        replay.end_span()
        # span 2: after branch → live (run for real)
        assert replay.begin_span() == ("live", None)
        assert replay.current_frozen_output() is None
        replay.end_span()
        # span 3: still after branch → live
        assert replay.begin_span() == ("live", None)
    finally:
        replay.reset_plan(token)
    assert replay.is_replaying() is False


def test_branch_at_first_span_runs_rest_live():
    """cinerater case: branch the first LLM, everything after runs live."""
    token = replay.set_plan(_plan(branch_index=0))
    try:
        assert replay.begin_span() == ("edit", {"content": "EDIT"})
        replay.end_span()
        assert replay.begin_span() == ("live", None)
        replay.end_span()
        assert replay.begin_span() == ("live", None)
    finally:
        replay.reset_plan(token)


# ── Full-flow replay (fake client + fake Groq) ───────────────────────────────────

class _FakeGroq:
    """Mimics the bits of a Groq client that the integration touches."""

    def __init__(self):
        self.calls: list[dict] = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        msg = types.SimpleNamespace(content="LIVE-OUTPUT")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg)], usage=None
        )


class _FakeClient:
    def __init__(self, original):
        self._original = original
        self.sent = []

    def fetch_trace(self, trace_id):
        return self._original

    def enqueue(self, payload):
        self.sent.append(payload)


_TID = str(uuid.uuid4())
_S1, _S2, _S3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
_ORIGINAL = {
    "input": {"args": ["best crime thriller"]},
    "spans": [
        {"id": _S1, "type": "llm", "name": "groq.chat",
         "output": {"content": "OLD-parse"}, "started_at": "2026-01-01T00:00:00+00:00"},
        {"id": _S2, "type": "tool", "name": "search",
         "output": {"n": 1}, "started_at": "2026-01-01T00:00:01+00:00"},
        {"id": _S3, "type": "llm", "name": "groq.chat",
         "output": {"content": "OLD-write"}, "started_at": "2026-01-01T00:00:02+00:00"},
    ],
}


def _build_agent(groq, search_counter):
    @loupe.trace(name="agent")
    def agent(q):
        groq.chat.completions.create(model="llama-3.3-70b-versatile",
                                     messages=[{"role": "user", "content": q}])
        with loupe.span("search", type="tool") as s:
            search_counter.append(1)
            s.output = {"n": 99}
        b = groq.chat.completions.create(model="llama-3.3-70b-versatile",
                                         messages=[{"role": "user", "content": "write"}])
        return {"final": b.choices[0].message.content}
    return agent


def test_replay_branch_at_first_llm_propagates_downstream(monkeypatch):
    """The cinerater fix: edit the first LLM, everything after runs live so the
    edit actually reaches the final answer."""
    groq = _FakeGroq()
    loupe.instrument_groq(groq)
    fake = _FakeClient(_ORIGINAL)
    monkeypatch.setattr(core, "_client", fake)
    searches: list[int] = []
    agent = _build_agent(groq, searches)

    new_id = loupe.replay(agent, trace_id=_TID, branch_span_id=_S1,
                          new_output={"content": "EDITED-parse"})

    # Exactly one live LLM call — the *write* step (after branch). The parse
    # step was the branch point and was short-circuited.
    assert len(groq.calls) == 1
    # The tool ran live (after branch).
    assert searches == [1]
    # A new branched trace was produced and enqueued.
    assert new_id is not None
    assert len(fake.sent) == 1
    trace = fake.sent[0]
    assert trace.is_replay is True
    assert str(trace.branched_from_trace_id) == _TID
    assert str(trace.branched_from_span_id) == _S1
    assert trace.replay_mode == "sdk"  # B3: loupe.replay tags the trace
    # Final output reflects the LIVE re-run, not the stored OLD-write.
    assert trace.output == {"final": "LIVE-OUTPUT"}
    spans = {s.name: s for s in trace.spans}
    # branch span carries the edit + marker
    assert trace.spans[0].output == {"content": "EDITED-parse"}
    assert trace.spans[0].metadata["branch_point"] is True
    # tool ran live with its real new output
    assert spans["search"].output == {"n": 99}


def test_replay_branch_at_last_freezes_everything_before(monkeypatch):
    """Branch the final LLM: both earlier LLMs are frozen (no live API calls)."""
    groq = _FakeGroq()
    loupe.instrument_groq(groq)
    fake = _FakeClient(_ORIGINAL)
    monkeypatch.setattr(core, "_client", fake)
    searches: list[int] = []
    agent = _build_agent(groq, searches)

    loupe.replay(agent, trace_id=_TID, branch_span_id=_S3,
                 new_output={"content": "EDITED-write"})

    # No live LLM calls: parse is frozen, write is the (edited) branch point.
    assert groq.calls == []
    trace = fake.sent[0]
    # parse llm frozen to its stored output
    assert trace.spans[0].output == {"content": "OLD-parse"}
    assert trace.spans[0].metadata["replay"] == "frozen"
    # write llm is the branch point with the edit
    assert trace.spans[2].output == {"content": "EDITED-write"}
    assert trace.spans[2].metadata["branch_point"] is True


def test_decision_stack_nests():
    """A live span opened inside another keeps the parent's decision readable."""
    token = replay.set_plan(_plan(branch_index=2))
    try:
        replay.begin_span()  # span 0 → freeze
        assert replay.current_frozen_output() == {"content": "a"}
        # nested span 1 → freeze 'b'
        replay.begin_span()
        assert replay.current_frozen_output() == {"content": "b"}
        replay.end_span()  # pop nested
        # back to span 0's decision
        assert replay.current_frozen_output() == {"content": "a"}
        replay.end_span()
    finally:
        replay.reset_plan(token)

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpanIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    parent_span_id: uuid.UUID | None = None
    type: str = Field(..., max_length=32)
    name: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    model: str | None = None
    provider: str | None = Field(default=None, max_length=32)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: Decimal | None = None
    metadata: dict[str, Any] | None = None


class TraceIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str | None = None
    status: str | None = Field(default=None, max_length=16)
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    total_tokens: int | None = None
    total_cost_usd: Decimal | None = None
    metadata: dict[str, Any] | None = None
    is_replay: bool = False
    replay_of_trace_id: uuid.UUID | None = None
    branched_from_trace_id: uuid.UUID | None = None
    branched_from_span_id: uuid.UUID | None = None
    replay_mode: str | None = Field(default=None, max_length=16)
    spans: list[SpanIn] = Field(default_factory=list)


class TraceCreated(BaseModel):
    trace_id: uuid.UUID
    span_count: int


class TraceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    status: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    total_tokens: int | None
    total_cost_usd: Decimal | None
    is_replay: bool
    replay_of_trace_id: uuid.UUID | None


class TraceList(BaseModel):
    items: list[TraceListItem]
    limit: int
    offset: int
    has_more: bool


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trace_id: uuid.UUID
    parent_span_id: uuid.UUID | None
    type: str
    name: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    model: str | None
    provider: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="extra_metadata")


class TraceDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    status: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    total_tokens: int | None
    total_cost_usd: Decimal | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="extra_metadata")
    is_replay: bool
    replay_of_trace_id: uuid.UUID | None
    branched_from_trace_id: uuid.UUID | None
    branched_from_span_id: uuid.UUID | None
    replay_mode: str | None
    created_at: datetime
    spans: list[SpanOut]


class ReplayIn(BaseModel):
    original_trace_id: uuid.UUID
    prompt_override: str | None = None
    model_override: str | None = None


class ReplayCreated(BaseModel):
    replay_id: uuid.UUID
    new_trace_id: uuid.UUID


class ReplayDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    replay_id: uuid.UUID = Field(validation_alias="id")
    original_trace_id: uuid.UUID
    new_trace_id: uuid.UUID | None
    modifications: dict[str, Any] | None
    diff_summary: dict[str, Any] | None
    created_at: datetime


class BranchIn(BaseModel):
    """Request body for POST /v1/traces/{trace_id}/branch."""

    span_id: uuid.UUID
    new_output: dict[str, Any]


class BranchCreated(BaseModel):
    replay_id: uuid.UUID
    new_trace_id: uuid.UUID


# ── v2.2: suites (Prompt CI/CD) ────────────────────────────────────────────


class SuiteIn(BaseModel):
    name: str
    trace_ids: list[uuid.UUID] = Field(default_factory=list)
    judge_rubric: str | None = None


class SuiteCreated(BaseModel):
    suite_id: uuid.UUID


class SuiteOut(BaseModel):
    id: uuid.UUID
    name: str
    judge_rubric: str | None
    trace_count: int
    created_at: datetime


class SuiteRunIn(BaseModel):
    """Run a suite against a new prompt. `prompt_override` is the changed prompt
    text; `judge_backend` overrides the default ('groq/...' or 'claude/...')."""

    prompt_override: str | None = None
    model_override: str | None = None
    judge_backend: str | None = None


class SuiteRunCreated(BaseModel):
    suite_run_id: uuid.UUID


class SuiteRunSummary(BaseModel):
    """A suite run without its payload — for listing run history.

    Deliberately omits `results` (one JSONB row per trace, B8.2) and
    `prompt_override` (a whole prompt file). A suite with 50 runs of 100 traces
    would otherwise return megabytes to render a table of counts.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    status: str
    model_override: str | None
    judge_backend: str | None
    total: int
    passed: int
    regressed: int
    improved: int
    errored: int
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime


class SuiteRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    status: str
    prompt_override: str | None
    model_override: str | None
    judge_backend: str | None
    total: int
    passed: int
    regressed: int
    improved: int
    errored: int
    results: list[dict[str, Any]] | None
    error: dict[str, Any] | None
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime

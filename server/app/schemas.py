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

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class SpanPayload(BaseModel):
    id: uuid.UUID
    parent_span_id: uuid.UUID | None = None
    type: str
    name: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    model: str | None = None
    provider: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: Decimal | None = None
    metadata: dict[str, Any] | None = None


class TracePayload(BaseModel):
    id: uuid.UUID
    name: str | None = None
    status: str | None = None
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
    spans: list[SpanPayload] = Field(default_factory=list)

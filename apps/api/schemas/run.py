"""Run lifecycle and the SSE envelope."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import Field

from ._base import Contract
from .hypothesis import Hypothesis

RunState = Literal["queued", "running", "complete", "failed"]

EventType = Literal[
    "run.started",
    "camera.started",
    "camera.frames.sampled",
    "camera.observation",
    "camera.complete",
    "fusion.started",
    "evidence.linked",
    "triangulation.updated",
    "orchestrator.started",
    "tool.started",
    "tool.completed",
    "hypothesis.updated",
    "run.complete",
    "run.failed",
]
EVENT_TYPES: tuple[str, ...] = get_args(EventType)
TERMINAL_EVENT_TYPES = frozenset({"run.complete", "run.failed"})


class RunRequest(Contract):
    scenario_id: str = Field(min_length=1)
    profile: str | None = None
    pace_s: float | None = Field(default=None, ge=0, le=5)


class RunRecord(Contract):
    run_id: str = Field(min_length=1)
    scenario_id: str
    profile: str
    state: RunState
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    hypothesis: Hypothesis | None = None
    error: str | None = None
    last_seq: int = Field(default=0, ge=0)


class SseEnvelope(Contract):
    run_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    ts: datetime
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)

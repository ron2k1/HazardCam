"""Adapter interfaces, per-call options, the telemetry side channel and adapter factories.

Callers (tools, harness, event-day agent) depend only on the Protocols here; whether a
profile is backed by fixtures or a live OpenAI-compatible server is invisible to them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from functools import cache
from typing import Any, Literal, Protocol, runtime_checkable

from apps.api.schemas import (
    REPO_ROOT,
    EvidenceBundle,
    Hypothesis,
    MediaManifest,
    ModelScenarioView,
    ObservationBatch,
)

from .profiles import ModelProfile

PROMPTS_DIR = REPO_ROOT / "prompts"


@dataclass
class CallInfo:
    """Side-channel record of one adapter call. Never part of the returned contract."""

    role: Literal["perception", "reasoning"]
    adapter: str
    model: str | None
    ok: bool = True
    error: str | None = None
    latency_s: float = 0.0
    attempts: int = 0
    repaired: bool = False
    camera_id: str | None = None
    scenario_id: str | None = None
    frames_sent: list[int] = field(default_factory=list)
    frames_skipped: list[int] = field(default_factory=list)
    dropped_items: int = 0
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    prompt_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Telemetry = Callable[[CallInfo], None]


class AdapterError(RuntimeError):
    """Raised instead of degrading to an empty/abstain result when ``strict=True``."""

    def __init__(self, info: CallInfo) -> None:
        super().__init__(f"{info.role} adapter {info.adapter} failed: {info.error}")
        self.info = info


@dataclass(frozen=True, kw_only=True)
class PerceptionOptions:
    scenario_id: str | None = None
    scenario_view: ModelScenarioView | None = None
    max_frames: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    telemetry: Telemetry | None = None
    strict: bool = False

    @property
    def effective_scenario_id(self) -> str | None:
        if self.scenario_id:
            return self.scenario_id
        return self.scenario_view.id if self.scenario_view else None


@dataclass(frozen=True, kw_only=True)
class ReasoningOptions:
    max_tokens: int | None = None
    temperature: float | None = None
    telemetry: Telemetry | None = None
    strict: bool = False


@runtime_checkable
class PerceptionAdapter(Protocol):
    name: str

    def inspect(
        self, camera_id: str, media: MediaManifest, options: PerceptionOptions
    ) -> ObservationBatch: ...


@runtime_checkable
class ReasoningAdapter(Protocol):
    name: str

    def reason(self, bundle: EvidenceBundle, options: ReasoningOptions) -> Hypothesis: ...


def report(info: CallInfo, telemetry: Telemetry | None, strict: bool) -> None:
    """Deliver ``info`` to the caller's telemetry hook; raise if strict and failed."""
    if telemetry is not None:
        telemetry(info)
    if strict and not info.ok:
        raise AdapterError(info)


@cache
def load_prompt(filename: str) -> tuple[str, str]:
    """``(text, version)`` for ``prompts/<filename>``; version = sha256 prefix."""
    text = (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def get_perception_adapter(profile: ModelProfile) -> PerceptionAdapter:
    from .perception import FixturePerceptionAdapter, OpenAICompatPerceptionAdapter

    if profile.perception.backend == "fixture":
        return FixturePerceptionAdapter(profile)
    return OpenAICompatPerceptionAdapter(profile)


def get_reasoning_adapter(profile: ModelProfile) -> ReasoningAdapter:
    from .reasoning import FixtureReasoningAdapter, OpenAICompatReasoningAdapter

    if profile.reasoning.backend == "fixture":
        return FixtureReasoningAdapter(profile)
    return OpenAICompatReasoningAdapter(profile)

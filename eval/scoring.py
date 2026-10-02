"""Score one harness run against its judge-only ``expected.json``.

The rules are pre-registered in ``eval/SCORING.md``; this module implements them and
nothing else. It compares categorical fields, ids and numbers only, never free text.
The harness never sees ``expected``: the caller loads it after the run has returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jsonschema.exceptions import best_match

from apps.api.schemas import UNKNOWN, EvidenceBundle, Hypothesis
from apps.api.schemas.contracts import validator
from harness.dev_sequence import DevSequenceResult
from inference.vocab import NO_EVENT

NON_EVENTS = frozenset({UNKNOWN, NO_EVENT})
RUN_FAILED = "run_failed"
# The outcome labels that count as correct, per scenario category.
CORRECT_OUTCOMES: dict[str, frozenset[str]] = {
    "positive": frozenset({"hit"}),
    "negative": frozenset({"correct_reject"}),
    "ambiguous": frozenset({"hit", "abstain_ok"}),
}


@dataclass(frozen=True)
class ScenarioScore:
    scenario_id: str
    category: str
    completed: bool
    error: str | None
    gt_leaks: int
    replay_match: bool | None
    # event class
    event_type: str | None
    raw_event_type: str | None
    region: str | None
    confidence: float | None
    class_ok: bool
    raw_class_ok: bool
    outcome: str
    gate_changed: bool | None
    # region
    region_scored: bool
    region_ok: bool | None
    localization_error_m: float | None
    full_hit: bool | None
    fusion_region_hit: bool | None
    best_candidate_error_m: float | None
    # time, evidence, validity
    best_cluster_iou: float | None
    evidence_count: int
    evidence_cameras: list[str]
    unsupported_claim: bool | None
    schema_errors: list[str]
    # system
    duration_ms: float | None
    perception_latency_s: list[float] = field(default_factory=list)
    reasoning_latency_s: float | None = None
    failed_calls: int = 0
    tool_latency_ms: dict[str, list[float]] = field(default_factory=dict)

    @property
    def schema_valid(self) -> bool:
        return self.completed and not self.schema_errors

    @property
    def names_event(self) -> bool:
        return self.event_type is not None and self.event_type not in NON_EVENTS


def class_ok(event_type: str | None, expected: dict[str, Any]) -> bool:
    if event_type is None:
        return False
    if event_type in expected["accepted_event_types"]:
        return True
    return event_type == UNKNOWN and bool(expected["abstention_acceptable"])


def outcome(event_type: str | None, expected: dict[str, Any]) -> str:
    """One failure-capture label; correct iff it is in ``CORRECT_OUTCOMES[category]``."""
    if event_type is None:
        return RUN_FAILED
    accepted = event_type in expected["accepted_event_types"]
    if expected["category"] == "negative":
        return "correct_reject" if accepted else "false_alarm"
    if event_type == UNKNOWN:
        return "abstain_ok" if expected["abstention_acceptable"] else "miss_abstain"
    if event_type == NO_EVENT:
        return "miss_no_event"
    return "hit" if accepted else "wrong_class"


def temporal_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    union = max(a[1], b[1]) - min(a[0], b[0])
    return max(overlap, 0.0) / union if union > 0 else 0.0


def _dist(a: list[float] | None, b: list[float] | None) -> float | None:
    return round(math.dist(a, b), 2) if a and b else None


def _region(
    expected: dict[str, Any], hypothesis: Hypothesis | None, bundle: EvidenceBundle | None
) -> dict[str, Any]:
    region = expected.get("region") or {}
    accepted = region.get("accepted_zone_ids") or []
    point = region.get("event_point_local_m")
    candidates = bundle.region_candidates if bundle else []
    scored = bool(accepted) and hypothesis is not None and hypothesis.event_type not in NON_EVENTS
    named = next((c for c in candidates if hypothesis and c.id == hypothesis.region), None)
    errors = [d for d in (_dist(c.center, point) for c in candidates) if d is not None]
    return {
        "region_scored": scored,
        "region_ok": (hypothesis.region in accepted) if scored else None,
        "localization_error_m": _dist(named.center, point) if scored and named else None,
        "fusion_region_hit": any(c.id in accepted for c in candidates) if accepted else None,
        "best_candidate_error_m": min(errors) if errors else None,
    }


def _best_cluster_iou(expected: dict[str, Any], bundle: EvidenceBundle | None) -> float | None:
    window = expected.get("time_window")
    if not window or bundle is None:
        return None
    span = (window["start_s"], window["end_s"])
    return max((temporal_iou((c.t_start, c.t_end), span) for c in bundle.clusters), default=0.0)


def schema_errors(result: DevSequenceResult) -> list[str]:
    """Each run document checked against ``contracts/``; empty when all are valid."""
    docs: list[tuple[str, str, Any]] = [
        (f"observations[{b.camera_id}]", "observation_batch", b.model_dump(mode="json"))
        for b in result.batches
    ]
    docs += [
        ("bundle", "evidence_bundle", result.bundle.model_dump(mode="json")),
        ("raw_hypothesis", "hypothesis", result.raw_hypothesis.model_dump(mode="json")),
        ("hypothesis", "hypothesis", result.hypothesis.model_dump(mode="json")),
    ]
    errors = []
    for label, contract, doc in docs:
        error = best_match(validator(contract).iter_errors(doc))
        if error is not None:
            errors.append(f"{label}: {error.message}"[:240])
    return errors


def score_run(
    expected: dict[str, Any],
    result: DevSequenceResult | None,
    *,
    error: str | None = None,
    gt_leaks: int = 0,
    replay_match: bool | None = None,
) -> ScenarioScore:
    """Score one scenario. ``result`` is ``None`` when the run failed (``error`` says why)."""
    category = expected["category"]
    h = result.hypothesis if result else None
    raw = result.raw_hypothesis if result else None
    bundle = result.bundle if result else None
    event_type = h.event_type if h else None
    ok = class_ok(event_type, expected)
    region = _region(expected, h, bundle)
    cited = set(h.evidence_ids) if h else set()
    calls = result.adapter_calls if result else []
    reasoning = [c.get("latency_s", 0.0) for c in calls if c.get("role") == "reasoning"]
    return ScenarioScore(
        scenario_id=expected["scenario_id"],
        category=category,
        completed=result is not None,
        error=error,
        gt_leaks=gt_leaks,
        replay_match=replay_match,
        event_type=event_type,
        raw_event_type=raw.event_type if raw else None,
        region=h.region if h else None,
        confidence=h.confidence if h else None,
        class_ok=ok,
        raw_class_ok=class_ok(raw.event_type if raw else None, expected),
        outcome=outcome(event_type, expected),
        gate_changed=(
            (raw.event_type, raw.region, raw.confidence) != (h.event_type, h.region, h.confidence)
            if raw and h
            else None
        ),
        full_hit=(ok and bool(region["region_ok"])) if category == "positive" else None,
        best_cluster_iou=_best_cluster_iou(expected, bundle),
        evidence_count=len(cited),
        evidence_cameras=sorted({e.camera_id for e in bundle.evidence if e.id in cited})
        if bundle
        else [],
        unsupported_claim=(not cited) if h and h.event_type not in NON_EVENTS else None,
        schema_errors=schema_errors(result) if result else [],
        duration_ms=result.duration_ms if result else None,
        perception_latency_s=[
            round(c.get("latency_s", 0.0), 3) for c in calls if c.get("role") == "perception"
        ],
        reasoning_latency_s=round(sum(reasoning), 3) if reasoning else None,
        failed_calls=sum(not c.get("ok", True) for c in calls),
        tool_latency_ms=dict(result.tool_latency_ms) if result else {},
        **region,
    )

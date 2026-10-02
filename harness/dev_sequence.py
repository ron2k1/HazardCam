"""NON-AGENT development harness ("dev-sequence").

This module is deliberately NOT an agent. It has no planner, no policy, no tool
registry, no system prompt, and no model choosing what to call next. It calls the
run-scoped tools in ``tools/session.py`` in ONE fixed order so the whole product can
be built, demoed and evaluated before event day. On event day a freshly written
OpenClaw agent (built at the venue, see docs/COMPLIANCE.md) replaces this module and
calls the same ``ToolSession`` tools, which emit the same events, so the UI does not
change.

Ground-truth rule: the full ``Scenario`` is reduced to ``scenario.model_view()`` on
the first line and dropped. Nothing below can reach the withheld camera.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.api.schemas import (
    REPO_ROOT,
    EvidenceBundle,
    FrameRef,
    Hypothesis,
    MediaManifest,
    ObservationBatch,
    Scenario,
)
from inference.base import PerceptionAdapter, ReasoningAdapter
from inference.profiles import ModelProfile
from tools.session import Emit, FrameUrl, ToolSession

HARNESS_ID = "dev-sequence"
SEQUENCE = (
    "sample_video",
    "inspect_camera",
    "correlate_observations",
    "triangulate_region",
    "reason_hypothesis",
    "get_supporting_frames",
    "submit_hypothesis",
)


@dataclass
class DevSequenceResult:
    """Everything one run produced. ``hypothesis`` is the submitted (final) one."""

    scenario_id: str
    profile: str
    manifests: dict[str, MediaManifest]
    batches: list[ObservationBatch]
    bundle: EvidenceBundle
    raw_hypothesis: Hypothesis
    hypothesis: Hypothesis
    supporting_frames: dict[str, list[FrameRef]]
    adapter_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_latency_ms: dict[str, list[float]] = field(default_factory=dict)
    duration_ms: float = 0.0


def cited_frames(
    bundle: EvidenceBundle, hypothesis: Hypothesis, manifests: dict[str, MediaManifest]
) -> dict[str, list[int]]:
    """Valid frame indices of the evidence ``hypothesis`` cites, grouped by camera.

    Each camera's indices are sorted and listed once, however many cited items share them.
    """
    cited: dict[str, set[int]] = {}
    for e in bundle.evidence:
        if e.id in hypothesis.evidence_ids and e.camera_id in manifests:
            frames = len(manifests[e.camera_id].frames)
            indices = {i for i in e.supporting_frames if 0 <= i < frames}
            if indices:
                cited.setdefault(e.camera_id, set()).update(indices)
    return {camera_id: sorted(indices) for camera_id, indices in cited.items()}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_dev_sequence(
    scenario: Scenario,
    profile: ModelProfile,
    emit: Emit,
    *,
    run_dir: Path,
    pace_s: float = 0.0,
    frame_url: FrameUrl | None = None,
    media_root: Path = REPO_ROOT,
) -> Hypothesis:
    """Run the fixed tool sequence and return the submitted hypothesis."""
    return run_dev_sequence_detailed(
        scenario,
        profile,
        emit,
        run_dir=run_dir,
        pace_s=pace_s,
        frame_url=frame_url,
        media_root=media_root,
    ).hypothesis


def run_dev_sequence_detailed(
    scenario: Scenario,
    profile: ModelProfile,
    emit: Emit,
    *,
    run_dir: Path,
    pace_s: float = 0.0,
    frame_url: FrameUrl | None = None,
    media_root: Path = REPO_ROOT,
    perception: PerceptionAdapter | None = None,
    reasoning: ReasoningAdapter | None = None,
) -> DevSequenceResult:
    view = scenario.model_view()
    del scenario  # nothing below may touch the full scenario (ground-truth camera)

    started = time.perf_counter()
    session = ToolSession(
        view,
        profile,
        emit,
        run_dir=run_dir,
        frame_url=frame_url,
        media_root=media_root,
        perception=perception,
        reasoning=reasoning,
    )

    def pace() -> None:
        if pace_s > 0:
            time.sleep(pace_s)

    emit(
        "run.started",
        {
            "scenario_id": view.id,
            "profile": profile.profile,
            "camera_ids": session.camera_ids,
            "harness": HARNESS_ID,
        },
    )
    emit(
        "orchestrator.started", {"harness": HARNESS_ID, "agent": False, "sequence": list(SEQUENCE)}
    )
    pace()

    for camera_id in session.camera_ids:
        session.sample_video(camera_id)
        pace()
        session.inspect_camera(camera_id)
        pace()
    session.correlate_observations()
    pace()
    bundle = session.triangulate_region()
    pace()
    raw = session.reason_hypothesis()
    pace()
    for camera_id, indices in cited_frames(bundle, raw, session.manifests).items():
        session.get_supporting_frames(camera_id, indices)
    final = session.submit_hypothesis()

    result = DevSequenceResult(
        scenario_id=view.id,
        profile=profile.profile,
        manifests=session.manifests,
        batches=session.ordered_batches(),
        bundle=bundle,
        raw_hypothesis=raw,
        hypothesis=final,
        supporting_frames=session.supporting_frames,
        adapter_calls=session.adapter_calls,
        tool_latency_ms=session.tool_latency_ms,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    _write_artifacts(Path(run_dir), result)
    return result


def _write_artifacts(run_dir: Path, result: DevSequenceResult) -> None:
    _write_json(
        run_dir / "observations.json",
        {b.camera_id: b.model_dump(mode="json") for b in result.batches},
    )
    _write_json(run_dir / "evidence_bundle.json", result.bundle.model_dump(mode="json"))
    _write_json(run_dir / "hypothesis.raw.json", result.raw_hypothesis.model_dump(mode="json"))
    _write_json(run_dir / "hypothesis.json", result.hypothesis.model_dump(mode="json"))
    _write_json(
        run_dir / "telemetry.json",
        {
            "profile": result.profile,
            "duration_ms": result.duration_ms,
            "tool_latency_ms": result.tool_latency_ms,
            "adapter_calls": result.adapter_calls,
        },
    )


__all__ = [
    "HARNESS_ID",
    "SEQUENCE",
    "DevSequenceResult",
    "cited_frames",
    "run_dev_sequence",
    "run_dev_sequence_detailed",
]

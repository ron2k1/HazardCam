"""Deterministic temporal correlation of per-camera observations (P08, no LLM).

Pipeline: ground-truth guard -> scenario-time alignment -> confidence filter ->
evidence ids -> world bearings -> single-linkage interval clustering.

Scenario time = media time + ``camera.time_offset_s`` (rounded to 1 us).

Bearing table. Output is a compass bearing (0 = north/+y, 90 = east/+x, clockwise);
``h`` = camera ``heading_deg``, ``f`` = camera ``fov_deg``:

    left            h - 0.4 f      centres of five equal 0.2 f bands across the
    center_left     h - 0.2 f      field of view (linear-in-angle approximation)
    center          h
    center_right    h + 0.2 f
    right           h + 0.4 f
    toward_camera   h              the cue lies along the optical axis; depth is
    away_from_camera h             ambiguous, so triangulation down-weights it
    north .. northwest  0, 45, .., 315   world-absolute; needs no camera geometry

Image-relative words need both ``heading_deg`` and ``fov_deg``; a null or unknown
direction gives ``None``. Matching ignores case and treats ``-``/space as ``_``.

Evidence ids are the observation ids, verbatim. When one id is emitted by two or
more cameras, every copy becomes ``<camera_id>:<id>``. A repeat within one camera
gets ``#2``, ``#3``... in canonical content order. Each rename is reported in
``Correlation.renamed`` as ``(camera_id, original_id, new_id)``.

Clusters: two items link when the gap between their scenario-time intervals is
``<= tolerance_s`` (each interval widened by ``tolerance_s / 2`` on both sides
overlaps). Clusters are the connected components. Ids are ``clu_01``... in order
of ``t_start``. Score, rounded to 4 dp:

    score = 0.5 * cameras/visible_cameras + 0.3 * mean_confidence + 0.2 * tightness
    tightness = 1 / (1 + onset_spread_s / max(tolerance_s, 0.1))

``onset_spread_s`` is the latest member ``t_start`` minus the earliest. Every item
belongs to exactly one cluster. All outputs are canonically sorted, so they do
not depend on batch or observation order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from apps.api.schemas import (
    COMPASS_DIRECTIONS,
    EvidenceCluster,
    EvidenceItem,
    GroundTruthAccessError,
    ModelCamera,
    ModelScenarioView,
    Observation,
    ObservationBatch,
    Scenario,
)

IMAGE_OFFSET_FRACTION = {
    "left": -0.4,
    "center_left": -0.2,
    "center": 0.0,
    "center_right": 0.2,
    "right": 0.4,
    "toward_camera": 0.0,
    "away_from_camera": 0.0,
}
AXIAL_DIRECTIONS = frozenset({"toward_camera", "away_from_camera"})
COMPASS_BEARING = {name: 45.0 * i for i, name in enumerate(COMPASS_DIRECTIONS)}

W_CAMERAS = 0.5
W_CONFIDENCE = 0.3
W_TIGHTNESS = 0.2
MIN_TIGHTNESS_SCALE_S = 0.1
TIME_DECIMALS = 6
_LINK_EPS_S = 1e-9


@dataclass(frozen=True)
class Correlation:
    """Full correlation result; ``correlate_observations`` returns only the first two."""

    evidence: list[EvidenceItem]
    clusters: list[EvidenceCluster]
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (camera_id, obs id)
    renamed: list[tuple[str, str, str]] = field(default_factory=list)
    batch_count: int = 0
    min_confidence: float = 0.3

    def notes(self) -> list[str]:
        """Input-side notes (no batches, dropped, renamed): facts only the batches know."""
        notes = []
        if self.batch_count == 0:
            notes.append("No observation batches were supplied.")
        if self.dropped:
            listed = ", ".join(f"{cam}/{obs}" for cam, obs in self.dropped)
            notes.append(
                f"Dropped {len(self.dropped)} observation(s) below "
                f"min_confidence={self.min_confidence:g}: {listed}."
            )
        for cam, original, new in self.renamed:
            notes.append(f"Evidence id {original!r} from {cam} renamed to {new!r} (id collision).")
        return notes


def require_view(view: object) -> ModelScenarioView:
    """Fail closed unless ``view`` is the ground-truth-free model view."""
    if isinstance(view, Scenario):
        raise GroundTruthAccessError(
            "fusion tools take Scenario.model_view(), never the raw Scenario"
        )
    if not isinstance(view, ModelScenarioView):
        raise TypeError(f"expected ModelScenarioView, got {type(view).__name__}")
    return view


def normalize_direction(direction: str | None) -> str | None:
    """Canonical direction word, or ``None`` when null or not in the vocabulary."""
    if direction is None:
        return None
    key = direction.strip().lower().replace("-", "_").replace(" ", "_")
    if key in IMAGE_OFFSET_FRACTION:
        return key
    compact = key.replace("_", "")
    return compact if compact in COMPASS_BEARING else None


def wrap_bearing(deg: float) -> float:
    """Normalize to [0, 360), rounded to 6 dp, with no ``-0.0``."""
    return round(deg % 360.0, 6) % 360.0 + 0.0


def direction_to_bearing(
    direction: str | None, heading_deg: float | None, fov_deg: float | None
) -> float | None:
    """World compass bearing for an observation direction (see the module table)."""
    key = normalize_direction(direction)
    if key is None:
        return None
    if key in COMPASS_BEARING:
        return COMPASS_BEARING[key]
    if heading_deg is None or fov_deg is None:
        return None
    return wrap_bearing(heading_deg + IMAGE_OFFSET_FRACTION[key] * fov_deg)


def correlate_observations(
    batches: list[ObservationBatch],
    view: ModelScenarioView,
    *,
    tolerance_s: float = 1.5,
    min_confidence: float = 0.3,
) -> tuple[list[EvidenceItem], list[EvidenceCluster]]:
    result = correlate(batches, view, tolerance_s=tolerance_s, min_confidence=min_confidence)
    return result.evidence, result.clusters


def correlate(
    batches: list[ObservationBatch],
    view: ModelScenarioView,
    *,
    tolerance_s: float = 1.5,
    min_confidence: float = 0.3,
) -> Correlation:
    """Like ``correlate_observations`` but also reports dropped and renamed ids."""
    view = require_view(view)
    if tolerance_s < 0:
        raise ValueError(f"tolerance_s must be >= 0, got {tolerance_s}")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be in [0, 1], got {min_confidence}")

    # Guard every batch before reading any of them, including empty ones.
    cameras = {batch.camera_id: view.camera(batch.camera_id) for batch in batches}

    rows: list[tuple[ModelCamera, Observation]] = []
    dropped: list[tuple[str, str]] = []
    for batch in batches:
        cam = cameras[batch.camera_id]
        for obs in batch.observations:
            if obs.confidence < min_confidence:
                dropped.append((cam.id, obs.id))
            else:
                rows.append((cam, obs))
    rows.sort(key=lambda row: _row_key(*row))

    ids, renamed = _assign_ids(rows)
    evidence = sorted(
        (_to_evidence(new_id, cam, obs) for new_id, (cam, obs) in zip(ids, rows, strict=True)),
        key=_evidence_key,
    )
    clusters = _cluster(evidence, tolerance_s, visible_cameras=len(view.cameras))
    return Correlation(evidence, clusters, sorted(dropped), renamed, len(batches), min_confidence)


def fusion_notes(
    batches: list[ObservationBatch],
    view: ModelScenarioView,
    *,
    min_confidence: float = 0.3,
) -> list[str]:
    """The input-side notes ``correlate_observations`` cannot return (its tuple is fixed).

    For callers that run correlate and triangulate as separate tool calls; pass the
    result as ``assemble_evidence_bundle(..., notes=...)``. Drops and renames do not
    depend on ``tolerance_s``.
    """
    return correlate(batches, view, min_confidence=min_confidence).notes()


def _row_key(cam: ModelCamera, obs: Observation) -> tuple:
    return (
        cam.id,
        obs.id,
        obs.t_start,
        obs.t_end,
        obs.cue_type,
        obs.description,
        obs.direction is None,
        obs.direction or "",
        obs.confidence,
        tuple(obs.supporting_frames),
    )


def _evidence_key(e: EvidenceItem) -> tuple:
    return (e.t_start, e.t_end, e.camera_id, e.id)


def _assign_ids(
    rows: list[tuple[ModelCamera, Observation]],
) -> tuple[list[str], list[tuple[str, str, str]]]:
    cameras_per_id: dict[str, set[str]] = defaultdict(set)
    for cam, obs in rows:
        cameras_per_id[obs.id].add(cam.id)
    used: set[str] = set()
    ids: list[str] = []
    renamed: list[tuple[str, str, str]] = []
    for cam, obs in rows:
        base = f"{cam.id}:{obs.id}" if len(cameras_per_id[obs.id]) > 1 else obs.id
        new_id, n = base, 1
        while new_id in used:
            n += 1
            new_id = f"{base}#{n}"
        used.add(new_id)
        ids.append(new_id)
        if new_id != obs.id:
            renamed.append((cam.id, obs.id, new_id))
    return ids, renamed


def _scenario_time(media_t: float, offset_s: float) -> float:
    return round(media_t + offset_s, TIME_DECIMALS) + 0.0


def _to_evidence(evidence_id: str, cam: ModelCamera, obs: Observation) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        camera_id=cam.id,
        t_start=_scenario_time(obs.t_start, cam.time_offset_s),
        t_end=_scenario_time(obs.t_end, cam.time_offset_s),
        cue_type=obs.cue_type,
        description=obs.description,
        direction=obs.direction,
        bearing_deg=direction_to_bearing(obs.direction, cam.heading_deg, cam.fov_deg),
        confidence=obs.confidence,
        supporting_frames=list(obs.supporting_frames),
    )


def _cluster(
    evidence: list[EvidenceItem], tolerance_s: float, *, visible_cameras: int
) -> list[EvidenceCluster]:
    # Sorted by t_start, an item links to the open group iff its start is within
    # tolerance of the group's furthest end; no later item can bridge closed groups.
    groups: list[list[EvidenceItem]] = []
    reach = 0.0
    for item in sorted(evidence, key=_evidence_key):
        if groups and item.t_start - reach <= tolerance_s + _LINK_EPS_S:
            groups[-1].append(item)
            reach = max(reach, item.t_end)
        else:
            groups.append([item])
            reach = item.t_end
    return [
        _make_cluster(f"clu_{i:02d}", members, tolerance_s, visible_cameras)
        for i, members in enumerate(groups, start=1)
    ]


def _make_cluster(
    cluster_id: str, members: list[EvidenceItem], tolerance_s: float, visible_cameras: int
) -> EvidenceCluster:
    cameras = sorted({e.camera_id for e in members})
    starts = [e.t_start for e in members]
    mean_confidence = sum(e.confidence for e in members) / len(members)
    tightness = 1.0 / (1.0 + (max(starts) - min(starts)) / max(tolerance_s, MIN_TIGHTNESS_SCALE_S))
    score = (
        W_CAMERAS * len(cameras) / max(visible_cameras, 1)
        + W_CONFIDENCE * mean_confidence
        + W_TIGHTNESS * tightness
    )
    return EvidenceCluster(
        id=cluster_id,
        t_start=min(starts),
        t_end=max(e.t_end for e in members),
        evidence_ids=[e.id for e in members],
        camera_ids=cameras,
        score=round(min(1.0, max(0.0, score)), 4),
    )

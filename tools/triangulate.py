"""Deterministic coarse triangulation and evidence-bundle assembly (P08, no LLM).

Rays. Each evidence item with a ``bearing_deg`` from a camera with a ``position``
casts a ray from the camera's ``[x_east_m, y_north_m]`` along that bearing. Ray
weight = confidence, times 0.5 for ``toward_camera`` / ``away_from_camera``
(axial cues are depth-ambiguous). Angular half-uncertainty ``sigma``, capped at
45 deg: 0.1 * fov for left..right (half a 0.2 * fov band), 0.5 * fov for axial
cues, 22.5 deg for compass words (half a 45 deg sector), and 22.5 deg when the
direction word or fov is unknown.

Per cluster, the 3 best clusters by score that have at least one ray:

* ``ray_intersection``: every pair of rays from different cameras is intersected.
  A pair is skipped when it crosses at less than 5 deg (near-parallel) or when the
  crossing is behind either camera. The center is the mean of the crossing points,
  weighted by ``w_a * w_b``. The radius is
  ``max(3 m, hypot(spread, angular))``. ``spread`` is the weighted RMS distance of
  the crossings from the center. ``angular`` is the weighted mean of
  ``hypot(r_a tan sigma_a, r_b tan sigma_b) / sin(crossing angle)``, where ``r``
  is the range along each ray.
  ``score = cluster.score * (0.5 * agreement + 0.5 * 3 m / radius)``, where
  agreement = cameras in a valid crossing / cameras with rays.
* no valid crossing: fall back to the strongest ray (highest weight, then
  evidence id). If that ray passes through a zone (within the radius of a zone
  whose center lies ahead of the camera), the result is ``zone_prior``: the zone's center,
  radius, id and label, with ``score = cluster.score * 0.5``. Otherwise it is
  ``single_ray``: a point 15 m along the ray with a 15 m radius and
  ``score = cluster.score * 0.25``.

A ``ray_intersection`` center inside a zone takes that zone's id and label and
keeps its computed center and radius. When zones overlap, the smallest
distance/radius wins. Other candidates get ids ``region_01``... in final order,
skipping any id that is already a zone id in the view.
Candidates are sorted by score (desc), then by source cluster id. When two share a
zone id, only the higher-scoring one is kept. No ray at all gives an empty list.

Bundle. ``assemble_evidence_bundle`` holds the single status rule and builds the
cameras and notes from outputs that have already been computed. There are two
equivalent ways to call it:

* one call: ``build_evidence_bundle(batches, view)``
* separate tool calls (P10 harness / event-day agent): ``correlate_observations``,
  then ``triangulate_region``, then ``assemble_evidence_bundle(..., notes=fusion_notes(...))``

The drop and rename notes come from the batches, so they reach the bundle only
through ``build_evidence_bundle`` or ``fusion_notes``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from apps.api.schemas import (
    BundleCamera,
    EvidenceBundle,
    EvidenceCluster,
    EvidenceItem,
    ModelScenarioView,
    ObservationBatch,
    RegionCandidate,
    Zone,
    validate_json,
)
from tools.correlate import (
    AXIAL_DIRECTIONS,
    COMPASS_BEARING,
    correlate,
    normalize_direction,
    require_view,
)

MAX_REGION_CLUSTERS = 3
MIN_CROSSING_DEG = 5.0
RADIUS_FLOOR_M = 3.0
NOMINAL_RANGE_M = 15.0
NOMINAL_RADIUS_M = 15.0
AXIAL_RAY_WEIGHT = 0.5
LATERAL_SIGMA_FOV_FRACTION = 0.1
AXIAL_SIGMA_FOV_FRACTION = 0.5
COARSE_SIGMA_DEG = 22.5
MAX_SIGMA_DEG = 45.0
W_AGREEMENT = 0.5
W_COMPACTNESS = 0.5
ZONE_PRIOR_FACTOR = 0.5
SINGLE_RAY_FACTOR = 0.25
_MIN_FORWARD_M = 1e-6
_ZONE_EPS_M = 1e-9


@dataclass(frozen=True)
class Ray:
    evidence_id: str
    camera_id: str
    origin: tuple[float, float]
    bearing_deg: float
    weight: float
    sigma_deg: float

    @property
    def unit(self) -> tuple[float, float]:
        rad = math.radians(self.bearing_deg)
        return math.sin(rad), math.cos(rad)

    def to_dict(self) -> dict:
        """Shape of one entry in the ``triangulation.updated`` SSE payload's ``rays``."""
        return {
            "camera_id": self.camera_id,
            "evidence_id": self.evidence_id,
            "origin": list(self.origin),
            "bearing_deg": self.bearing_deg,
        }


@dataclass(frozen=True)
class Crossing:
    point: tuple[float, float]
    range_a: float
    range_b: float
    sin_angle: float


def evidence_rays(evidence: list[EvidenceItem], view: ModelScenarioView) -> list[Ray]:
    """Rays for every evidence item with a bearing and a positioned camera.

    Every item's camera is checked against the view (ground-truth guard), even items
    that cast no ray. Rays are sorted by (camera_id, evidence_id).
    """
    view = require_view(view)
    rays = []
    for e in evidence:
        cam = view.camera(e.camera_id)
        if e.bearing_deg is None or cam.position is None:
            continue
        weight, sigma = _ray_terms(e.direction, cam.fov_deg)
        rays.append(
            Ray(
                evidence_id=e.id,
                camera_id=cam.id,
                origin=(float(cam.position[0]), float(cam.position[1])),
                bearing_deg=e.bearing_deg,
                weight=e.confidence * weight,
                sigma_deg=sigma,
            )
        )
    return sorted(rays, key=lambda r: (r.camera_id, r.evidence_id))


def _ray_terms(direction: str | None, fov_deg: float | None) -> tuple[float, float]:
    key = normalize_direction(direction)
    if key is None or key in COMPASS_BEARING or fov_deg is None:
        return 1.0, COARSE_SIGMA_DEG
    if key in AXIAL_DIRECTIONS:
        return AXIAL_RAY_WEIGHT, min(AXIAL_SIGMA_FOV_FRACTION * fov_deg, MAX_SIGMA_DEG)
    return 1.0, min(LATERAL_SIGMA_FOV_FRACTION * fov_deg, MAX_SIGMA_DEG)


def intersect_rays(a: Ray, b: Ray) -> Crossing | None:
    """Forward-only crossing of two rays, or ``None`` if near-parallel or behind."""
    (ax, ay), (bx, by) = a.origin, b.origin
    (dax, day), (dbx, dby) = a.unit, b.unit
    cross = dax * dby - day * dbx
    if abs(cross) < math.sin(math.radians(MIN_CROSSING_DEG)):
        return None
    rx, ry = bx - ax, by - ay
    range_a = (rx * dby - ry * dbx) / cross
    range_b = (rx * day - ry * dax) / cross
    if range_a <= _MIN_FORWARD_M or range_b <= _MIN_FORWARD_M:
        return None
    return Crossing((ax + range_a * dax, ay + range_a * day), range_a, range_b, abs(cross))


def triangulate_region(
    evidence: list[EvidenceItem],
    clusters: list[EvidenceCluster],
    view: ModelScenarioView,
) -> list[RegionCandidate]:
    view = require_view(view)
    known = {e.id for e in evidence}
    for cluster in clusters:
        missing = sorted(set(cluster.evidence_ids) - known)
        if missing:
            raise ValueError(f"cluster {cluster.id!r} references unknown evidence {missing}")
    rays_by_id = {r.evidence_id: r for r in evidence_rays(evidence, view)}

    drafts: list[tuple[RegionCandidate, str]] = []
    for cluster in sorted(clusters, key=lambda c: (-c.score, c.t_start, c.id)):
        # Rays stay in (camera_id, evidence_id) order so float sums are order-independent.
        member_ids = set(cluster.evidence_ids)
        rays = [r for r in rays_by_id.values() if r.evidence_id in member_ids]
        if not rays:
            continue
        drafts.append((_cluster_candidate(cluster, rays, view.zones), cluster.id))
        if len(drafts) == MAX_REGION_CLUSTERS:
            break
    return _finalize(drafts, reserved_ids={z.id for z in view.zones})


def _cluster_candidate(
    cluster: EvidenceCluster, rays: list[Ray], zones: list[Zone]
) -> RegionCandidate:
    crossings = [
        (a, b, c)
        for i, a in enumerate(rays)
        for b in rays[i + 1 :]
        if a.camera_id != b.camera_id and (c := intersect_rays(a, b)) is not None
    ]
    if crossings:
        return _intersection_candidate(cluster, rays, crossings, zones)
    best = min(rays, key=lambda r: (-r.weight, r.evidence_id))
    zone = _zone_on_ray(best, zones)
    if zone is not None:
        return RegionCandidate(
            id=zone.id,
            label=zone.label,
            center=list(zone.center),
            radius_m=zone.radius_m,
            score=_score(cluster.score * ZONE_PRIOR_FACTOR),
            camera_ids=[best.camera_id],
            evidence_ids=[best.evidence_id],
            method="zone_prior",
        )
    (ox, oy), (dx, dy) = best.origin, best.unit
    return RegionCandidate(
        id="",
        center=[_m(ox + NOMINAL_RANGE_M * dx), _m(oy + NOMINAL_RANGE_M * dy)],
        radius_m=NOMINAL_RADIUS_M,
        score=_score(cluster.score * SINGLE_RAY_FACTOR),
        camera_ids=[best.camera_id],
        evidence_ids=[best.evidence_id],
        method="single_ray",
    )


def _intersection_candidate(
    cluster: EvidenceCluster,
    rays: list[Ray],
    crossings: list[tuple[Ray, Ray, Crossing]],
    zones: list[Zone],
) -> RegionCandidate:
    weights = [a.weight * b.weight for a, b, _ in crossings]
    if sum(weights) <= 0:
        weights = [1.0] * len(crossings)
    total = sum(weights)
    cx = sum(w * c.point[0] for w, (_, _, c) in zip(weights, crossings, strict=True)) / total
    cy = sum(w * c.point[1] for w, (_, _, c) in zip(weights, crossings, strict=True)) / total
    spread = math.sqrt(
        sum(
            w * ((c.point[0] - cx) ** 2 + (c.point[1] - cy) ** 2)
            for w, (_, _, c) in zip(weights, crossings, strict=True)
        )
        / total
    )
    angular = (
        sum(
            w
            * math.hypot(
                c.range_a * math.tan(math.radians(a.sigma_deg)),
                c.range_b * math.tan(math.radians(b.sigma_deg)),
            )
            / c.sin_angle
            for w, (a, b, c) in zip(weights, crossings, strict=True)
        )
        / total
    )
    radius = max(RADIUS_FLOOR_M, math.hypot(spread, angular))
    used_ids = {r.evidence_id for a, b, _ in crossings for r in (a, b)}
    used_cameras = sorted({r.camera_id for a, b, _ in crossings for r in (a, b)})
    agreement = len(used_cameras) / len({r.camera_id for r in rays})
    zone = _zone_containing((cx, cy), zones)
    return RegionCandidate(
        id=zone.id if zone else "",
        label=zone.label if zone else None,
        center=[_m(cx), _m(cy)],
        radius_m=_m(radius),
        score=_score(
            cluster.score * (W_AGREEMENT * agreement + W_COMPACTNESS * RADIUS_FLOOR_M / radius)
        ),
        camera_ids=used_cameras,
        evidence_ids=[e for e in cluster.evidence_ids if e in used_ids],
        method="ray_intersection",
    )


def _zone_containing(point: tuple[float, float], zones: list[Zone]) -> Zone | None:
    inside = [
        (math.dist(point, z.center) / z.radius_m, z.id, z)
        for z in zones
        if math.dist(point, z.center) <= z.radius_m + _ZONE_EPS_M
    ]
    return min(inside, key=lambda t: t[:2])[2] if inside else None


def _zone_on_ray(ray: Ray, zones: list[Zone]) -> Zone | None:
    """The zone whose center the forward ray passes closest to, if within its radius.

    Only zones whose center lies ahead of the camera qualify, so a zone the camera
    merely stands in, centered behind it, is never the prior.
    """
    (ox, oy), (dx, dy) = ray.origin, ray.unit
    hits = []
    for z in zones:
        along = (z.center[0] - ox) * dx + (z.center[1] - oy) * dy
        if along <= 0:
            continue
        miss = math.dist(z.center, (ox + along * dx, oy + along * dy))
        if miss <= z.radius_m + _ZONE_EPS_M:
            hits.append((miss, along, z.id, z))
    return min(hits, key=lambda t: t[:3])[3] if hits else None


def _finalize(
    drafts: list[tuple[RegionCandidate, str]], *, reserved_ids: set[str]
) -> list[RegionCandidate]:
    """Sort, keep the best candidate per zone id, number the rest around zone ids."""
    ordered = sorted(drafts, key=lambda d: (-d[0].score, d[1]))
    seen: set[str] = set()
    out: list[RegionCandidate] = []
    n = 0
    for cand, _ in ordered:
        if cand.id:
            if cand.id in seen:
                continue
            seen.add(cand.id)
            out.append(cand)
            continue
        n += 1
        while f"region_{n:02d}" in reserved_ids:
            n += 1
        out.append(cand.model_copy(update={"id": f"region_{n:02d}"}))
    return out


def _m(x: float) -> float:
    return round(x, 3) + 0.0


def _score(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 4)


def build_evidence_bundle(
    batches: list[ObservationBatch],
    view: ModelScenarioView,
    *,
    tolerance_s: float = 1.5,
    min_confidence: float = 0.3,
    min_cameras: int = 2,
) -> EvidenceBundle:
    """Correlate, triangulate, then ``assemble_evidence_bundle``, in one call.

    Equivalent to the split tool-call path with ``notes=fusion_notes(...)``.
    """
    result = correlate(batches, view, tolerance_s=tolerance_s, min_confidence=min_confidence)
    return assemble_evidence_bundle(
        view,
        result.evidence,
        result.clusters,
        triangulate_region(result.evidence, result.clusters, view),
        min_cameras=min_cameras,
        notes=result.notes(),
    )


def assemble_evidence_bundle(
    view: ModelScenarioView,
    evidence: list[EvidenceItem],
    clusters: list[EvidenceCluster],
    candidates: list[RegionCandidate],
    *,
    min_cameras: int = 2,
    notes: list[str] | None = None,
) -> EvidenceBundle:
    """Assemble a schema-valid bundle from fusion outputs without recomputing them.

    This is the only place the status rule lives: ``"ok"`` iff some cluster's evidence
    spans at least ``min_cameras`` distinct cameras. Cameras are counted from the
    cited evidence items, not from the cluster's own ``camera_ids``. ``notes`` (from
    ``fusion_notes``) come first, then the notes derived here. Every camera id cited
    anywhere must be in the view (ground-truth guard). Inputs may be models or their
    JSON dicts, since the event-day agent passes tool results as JSON.
    """
    view = require_view(view)
    if min_cameras < 1:
        raise ValueError(f"min_cameras must be >= 1, got {min_cameras}")
    evidence = [EvidenceItem.model_validate(e) for e in evidence]
    clusters = [EvidenceCluster.model_validate(c) for c in clusters]
    candidates = [RegionCandidate.model_validate(c) for c in candidates]

    cited = {e.camera_id for e in evidence}
    cited |= {cam for group in (*clusters, *candidates) for cam in group.camera_ids}
    for camera_id in sorted(cited):
        view.camera(camera_id)
    camera_of = {e.id: e.camera_id for e in evidence}
    for cluster in clusters:
        missing = sorted(set(cluster.evidence_ids) - camera_of.keys())
        if missing:
            raise ValueError(f"cluster {cluster.id!r} references unknown evidence {missing}")
    widest = max((len({camera_of[eid] for eid in c.evidence_ids}) for c in clusters), default=0)
    status = "ok" if widest >= min_cameras else "insufficient"

    bundle = EvidenceBundle(
        scenario_id=view.id,
        status=status,
        cameras=[
            BundleCamera(
                id=cam.id,
                label=cam.label,
                position=cam.position,
                heading_deg=cam.heading_deg,
                fov_deg=cam.fov_deg,
            )
            for cam in view.cameras
        ],
        evidence=evidence,
        clusters=clusters,
        region_candidates=candidates,
        notes=[
            *(notes or []),
            *_output_notes(view, evidence, candidates, status, min_cameras),
        ],
    )
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    return bundle


def _output_notes(
    view: ModelScenarioView,
    evidence: list[EvidenceItem],
    candidates: list[RegionCandidate],
    status: str,
    min_cameras: int,
) -> list[str]:
    notes = []
    silent = sorted({c.id for c in view.cameras} - {e.camera_id for e in evidence})
    if silent:
        notes.append(f"No usable observations from camera(s): {', '.join(silent)}.")
    no_bearing = sum(e.bearing_deg is None for e in evidence)
    if no_bearing:
        notes.append(
            f"{no_bearing} evidence item(s) have no bearing (null/unknown direction "
            "or missing camera heading/fov)."
        )
    if status == "insufficient":
        notes.append(
            f"Insufficient: no temporal cluster spans >= {min_cameras} cameras; "
            "cross-camera corroboration is missing."
        )
    if not candidates:
        notes.append("No region candidate: no evidence ray could be cast.")
    elif all(c.method != "ray_intersection" for c in candidates):
        notes.append(
            "No forward ray intersection between cameras; region candidates come from "
            "a single ray (low confidence)."
        )
    return notes

"""Deterministic fusion output: the only thing the reasoning model sees."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import Contract


class BundleCamera(Contract):
    id: str
    label: str | None = None
    model_access: Literal[True] = True
    position: list[float] | None = None
    heading_deg: float | None = None
    fov_deg: float | None = None


class EvidenceItem(Contract):
    id: str = Field(min_length=1)
    camera_id: str
    t_start: float
    t_end: float
    cue_type: str
    description: str
    direction: str | None = None
    bearing_deg: float | None = None
    confidence: float = Field(ge=0, le=1)
    supporting_frames: list[int] = Field(default_factory=list)


class EvidenceCluster(Contract):
    id: str
    t_start: float
    t_end: float
    evidence_ids: list[str] = Field(min_length=1)
    camera_ids: list[str] = Field(min_length=1)
    score: float = Field(ge=0, le=1)


RegionMethod = Literal["ray_intersection", "single_ray", "zone_prior", "none"]


class RegionCandidate(Contract):
    id: str
    label: str | None = None
    center: list[float] | None = None
    radius_m: float | None = None
    score: float = Field(ge=0, le=1)
    camera_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    method: RegionMethod


class EvidenceBundle(Contract):
    scenario_id: str = Field(min_length=1)
    status: Literal["ok", "insufficient"]
    cameras: list[BundleCamera]
    evidence: list[EvidenceItem]
    clusters: list[EvidenceCluster]
    region_candidates: list[RegionCandidate]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _referential_integrity(self) -> EvidenceBundle:
        ids = [e.id for e in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("evidence ids must be unique within a bundle")
        known_ids, known_cams = set(ids), {c.id for c in self.cameras}
        for e in self.evidence:
            if e.camera_id not in known_cams:
                raise ValueError(f"evidence {e.id!r} cites unknown/withheld camera {e.camera_id!r}")
        for group in (*self.clusters, *self.region_candidates):
            missing = set(group.evidence_ids) - known_ids
            if missing:
                raise ValueError(f"{group.id!r} references unknown evidence {sorted(missing)}")
        return self

    def evidence_ids(self) -> set[str]:
        return {e.id for e in self.evidence}

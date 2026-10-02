"""Scenario contract and the ground-truth access invariant.

Invariant (enforced here, in the JSON Schema, in the scenario service and in the
tool surface): the ground-truth camera has ``model_access=False`` and nothing a
model or harness receives may contain its id or file path. Callers that feed
models must go through :meth:`Scenario.model_view`, never the raw ``Scenario``.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from ._base import ClosedContract, Contract


class GroundTruthAccessError(PermissionError):
    """Raised when model-facing code asks for the withheld ground-truth camera."""


class Camera(Contract):
    id: str = Field(min_length=1)
    file: str = Field(min_length=1)
    model_access: bool
    label: str | None = None
    position: list[float] | None = Field(default=None, min_length=2, max_length=3)
    heading_deg: float | None = None
    fov_deg: float | None = Field(default=None, gt=0, le=360)
    time_offset_s: float = 0.0


class Zone(Contract):
    id: str = Field(min_length=1)
    label: str | None = None
    center: list[float] = Field(min_length=2, max_length=2)
    radius_m: float = Field(gt=0)


class ModelCamera(ClosedContract):
    """A camera as seen by model-facing code. Only model-accessible cameras exist here."""

    id: str
    file: str
    model_access: bool = True
    label: str | None = None
    position: list[float] | None = None
    heading_deg: float | None = None
    fov_deg: float | None = None
    time_offset_s: float = 0.0

    @model_validator(mode="after")
    def _must_be_accessible(self) -> ModelCamera:
        if not self.model_access:
            raise ValueError(f"camera {self.id!r} is not model-accessible")
        return self


class ModelScenarioView(ClosedContract):
    """Everything model-facing code may know about a scenario. Has no ground-truth field."""

    id: str
    title: str | None = None
    duration_seconds: float | None = None
    coordinate_frame: str | None = None
    cameras: list[ModelCamera] = Field(min_length=1)
    zones: list[Zone] = Field(default_factory=list)

    def camera(self, camera_id: str) -> ModelCamera:
        for cam in self.cameras:
            if cam.id == camera_id:
                return cam
        raise GroundTruthAccessError(
            f"camera {camera_id!r} is not an allowed input camera for scenario {self.id!r}"
        )


class Scenario(Contract):
    id: str = Field(min_length=1)
    title: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    coordinate_frame: str | None = None
    visible_cameras: list[Camera] = Field(min_length=1)
    ground_truth_camera: Camera
    zones: list[Zone] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _access_invariants(self) -> Scenario:
        gt = self.ground_truth_camera
        if gt.model_access:
            raise ValueError("ground_truth_camera.model_access must be false")
        ids = [c.id for c in self.visible_cameras]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate visible camera ids: {ids}")
        for cam in self.visible_cameras:
            if not cam.model_access:
                raise ValueError(f"visible camera {cam.id!r} must have model_access=true")
            if cam.file == gt.file:
                raise ValueError(f"visible camera {cam.id!r} shares the ground-truth file")
        if gt.id in ids:
            raise ValueError(f"ground-truth camera id {gt.id!r} collides with a visible camera")
        return self

    def model_view(self) -> ModelScenarioView:
        """The only scenario representation allowed to reach models, tools and the harness."""
        return ModelScenarioView(
            id=self.id,
            title=self.title,
            duration_seconds=self.duration_seconds,
            coordinate_frame=self.coordinate_frame,
            cameras=[
                ModelCamera(**cam.model_dump(include=set(ModelCamera.model_fields)))
                for cam in self.visible_cameras
                if cam.model_access
            ],
            zones=[z.model_copy() for z in self.zones],
        )

    def require_model_camera(self, camera_id: str) -> Camera:
        """Return a visible camera, refusing the ground-truth camera loudly."""
        if camera_id == self.ground_truth_camera.id:
            raise GroundTruthAccessError(
                f"camera {camera_id!r} is the withheld ground-truth camera (model_access=false)"
            )
        for cam in self.visible_cameras:
            if cam.id == camera_id:
                return cam
        raise GroundTruthAccessError(f"unknown camera {camera_id!r} for scenario {self.id!r}")

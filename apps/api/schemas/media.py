"""Deterministic frame-sample manifest for one camera video (seek metadata)."""

from __future__ import annotations

from pydantic import Field, model_validator

from ._base import Contract


class FrameRef(Contract):
    index: int = Field(
        ge=0, description="Position in MediaManifest.frames; what observations cite."
    )
    frame_id: int = Field(ge=0, description="Source video frame number.")
    t: float = Field(ge=0, description="Seconds on the camera media clock; UI seek target.")
    path: str | None = None


class MediaManifest(Contract):
    camera_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_sha256: str | None = None
    duration_s: float = Field(ge=0)
    src_fps: float = Field(gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sample_fps: float = Field(gt=0)
    start_s: float = Field(default=0.0, ge=0)
    end_s: float | None = None
    clip_path: str | None = None
    frames: list[FrameRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _indices_contiguous(self) -> MediaManifest:
        for i, frame in enumerate(self.frames):
            if frame.index != i:
                raise ValueError(f"frames[{i}].index is {frame.index}; indices must be 0..n-1")
        return self

    def frame(self, index: int) -> FrameRef:
        if not 0 <= index < len(self.frames):
            raise IndexError(f"frame index {index} out of range for camera {self.camera_id!r}")
        return self.frames[index]

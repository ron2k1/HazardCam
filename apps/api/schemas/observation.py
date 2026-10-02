"""Perception (Qwen) output: observation-only cues for one camera."""

from __future__ import annotations

from pydantic import Field, model_validator

from ._base import Contract

IMAGE_DIRECTIONS = (
    "left",
    "center_left",
    "center",
    "center_right",
    "right",
    "toward_camera",
    "away_from_camera",
)
COMPASS_DIRECTIONS = (
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
)


class Observation(Contract):
    id: str = Field(min_length=1)
    t_start: float = Field(ge=0)
    t_end: float = Field(ge=0)
    cue_type: str = Field(min_length=1)
    description: str
    direction: str | None = None
    confidence: float = Field(ge=0, le=1)
    supporting_frames: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered(self) -> Observation:
        if self.t_end < self.t_start:
            raise ValueError(f"observation {self.id!r}: t_end < t_start")
        if any(f < 0 for f in self.supporting_frames):
            raise ValueError(f"observation {self.id!r}: negative frame index")
        return self


class ObservationBatch(Contract):
    camera_id: str = Field(min_length=1)
    observations: list[Observation] = Field(default_factory=list)

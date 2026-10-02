"""Reasoning (Mistral) output: a bounded hypothesis with an explicit abstain path."""

from __future__ import annotations

from pydantic import Field

from ._base import Contract

UNKNOWN = "unknown"


class Alternative(Contract):
    event_type: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Hypothesis(Contract):
    event_type: str = Field(min_length=1)
    region: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str
    alternatives: list[Alternative] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @property
    def abstained(self) -> bool:
        return self.event_type == UNKNOWN

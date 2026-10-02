"""Builders shared by the P08 fusion tests."""

from __future__ import annotations

import json

import pytest

from apps.api.schemas import (
    REPO_ROOT,
    ModelCamera,
    ModelScenarioView,
    ObservationBatch,
    Scenario,
    Zone,
)


@pytest.fixture
def scenario() -> Scenario:
    path = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"
    return Scenario.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def fixture_batches() -> list[ObservationBatch]:
    path = REPO_ROOT / "data" / "fixtures" / "qwen_observations.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [ObservationBatch.model_validate(batch) for batch in doc.values()]


@pytest.fixture
def make_view():
    """``make_view({"id": "cam_a", "position": [0, 0], ...}, ..., zones=[...])``."""

    def make(*cameras: dict, zones: tuple[dict, ...] | list[dict] = ()) -> ModelScenarioView:
        return ModelScenarioView(
            id="scn_test",
            cameras=[ModelCamera(file=f"{cam['id']}.mp4", **cam) for cam in cameras],
            zones=[Zone(**z) for z in zones],
        )

    return make


@pytest.fixture
def obs():
    """``obs(id, t_start, t_end, direction=None, confidence=0.8)`` -> observation dict."""

    def make(
        obs_id: str,
        t_start: float,
        t_end: float,
        direction: str | None = None,
        confidence: float = 0.8,
        cue_type: str = "traffic_reaction",
    ) -> dict:
        return {
            "id": obs_id,
            "t_start": t_start,
            "t_end": t_end,
            "cue_type": cue_type,
            "description": f"{cue_type} seen as {obs_id}",
            "direction": direction,
            "confidence": confidence,
            "supporting_frames": [int(t_start)],
        }

    return make


@pytest.fixture
def make_batch():
    def make(camera_id: str, *observations: dict) -> ObservationBatch:
        return ObservationBatch(camera_id=camera_id, observations=list(observations))

    return make

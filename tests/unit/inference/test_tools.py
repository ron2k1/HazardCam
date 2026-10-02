"""P07/P09 tool wrappers: ground-truth refusal, manifest checks, default profile wiring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.schemas import (
    REPO_ROOT,
    GroundTruthAccessError,
    Hypothesis,
    ObservationBatch,
    Scenario,
)
from inference.base import PerceptionOptions, ReasoningOptions
from tools.inspect_camera import inspect_camera
from tools.reason_hypothesis import reason_hypothesis


@pytest.fixture
def scenario() -> Scenario:
    path = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


class RecordingAdapter:
    name = "recording"

    def __init__(self, camera_override: str | None = None) -> None:
        self.calls: list[str] = []
        self.camera_override = camera_override

    def inspect(self, camera_id, media, options) -> ObservationBatch:
        self.calls.append(camera_id)
        return ObservationBatch(camera_id=self.camera_override or camera_id, observations=[])


def _as(manifest, camera_id):
    return manifest.model_copy(update={"camera_id": camera_id})


def test_withheld_camera_is_refused_before_any_model_call(manifest, scenario):
    adapter = RecordingAdapter()
    options = PerceptionOptions(scenario_view=scenario.model_view())
    with pytest.raises(GroundTruthAccessError):
        inspect_camera("cam_gt", _as(manifest, "cam_gt"), options, adapter=adapter)
    assert adapter.calls == []


def test_raw_scenario_cannot_stand_in_for_the_model_view(manifest, scenario):
    adapter = RecordingAdapter()
    with pytest.raises(GroundTruthAccessError, match="model_view"):
        inspect_camera(
            "cam_01", manifest, PerceptionOptions(scenario_view=scenario), adapter=adapter
        )
    assert adapter.calls == []


def test_view_must_be_a_model_scenario_view(manifest):
    with pytest.raises(TypeError):
        inspect_camera(
            "cam_01",
            manifest,
            PerceptionOptions(scenario_view={"id": "x"}),
            adapter=RecordingAdapter(),
        )


def test_visible_camera_is_inspected(manifest, scenario):
    adapter = RecordingAdapter()
    options = PerceptionOptions(scenario_view=scenario.model_view())
    batch = inspect_camera("cam_01", manifest.model_dump(), options, adapter=adapter)
    assert batch.camera_id == "cam_01" and adapter.calls == ["cam_01"]


def test_manifest_for_another_camera_is_rejected(manifest):
    with pytest.raises(ValueError, match="belongs to camera"):
        inspect_camera("cam_02", manifest, adapter=RecordingAdapter())


def test_adapter_returning_another_camera_is_an_error(manifest):
    with pytest.raises(RuntimeError, match="returned camera"):
        inspect_camera("cam_01", manifest, adapter=RecordingAdapter(camera_override="cam_02"))


def test_default_adapter_comes_from_model_profile(manifest, monkeypatch):
    monkeypatch.setenv("MODEL_PROFILE", "fixture")
    batch = inspect_camera("cam_01", manifest)
    assert batch.camera_id == "cam_01" and batch.observations  # shared fixture has cam_01


def test_reason_hypothesis_accepts_plain_json_and_uses_the_profile(
    bundle, monkeypatch, example_fixture_profile
):
    monkeypatch.setattr("tools.reason_hypothesis.load_profile", lambda: example_fixture_profile)
    hyp = reason_hypothesis(bundle.model_dump(mode="json"), ReasoningOptions())
    assert isinstance(hyp, Hypothesis) and set(hyp.evidence_ids) <= bundle.evidence_ids()


def test_reason_hypothesis_revalidates_copied_bundles(bundle):
    broken = bundle.model_copy(update={"evidence": bundle.evidence[:1]})  # clusters now dangle
    with pytest.raises(ValidationError, match="unknown evidence"):
        reason_hypothesis(broken, adapter=object())

"""P01: contracts validate, pydantic mirrors agree with JSON Schema, GT invariant holds."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticError

from apps.api.schemas import (
    REPO_ROOT,
    EvidenceBundle,
    GroundTruthAccessError,
    Hypothesis,
    MediaManifest,
    ModelScenarioView,
    ObservationBatch,
    RunRecord,
    Scenario,
    SseEnvelope,
    is_valid,
    validate_json,
)

EXAMPLES = REPO_ROOT / "contracts" / "examples"

EXAMPLE_CONTRACTS = {
    "scenario_001.json": ("scenario", Scenario),
    "observation_batch.json": ("observation_batch", ObservationBatch),
    "media_manifest.json": ("media_manifest", MediaManifest),
    "evidence_bundle.json": ("evidence_bundle", EvidenceBundle),
    "hypothesis.json": ("hypothesis", Hypothesis),
    "hypothesis_abstain.json": ("hypothesis", Hypothesis),
    "run.json": ("run", RunRecord),
    "sse_event.json": ("sse_envelope", SseEnvelope),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def scenario_doc() -> dict:
    return _load(EXAMPLES / "scenario_001.json")


def test_every_example_is_covered():
    assert {p.name for p in EXAMPLES.glob("*.json")} == set(EXAMPLE_CONTRACTS)


@pytest.mark.parametrize("filename", sorted(EXAMPLE_CONTRACTS))
def test_example_validates_and_round_trips(filename):
    contract, model = EXAMPLE_CONTRACTS[filename]
    doc = _load(EXAMPLES / filename)
    validate_json(contract, doc)
    parsed = model.model_validate(doc)
    # What Python emits must still satisfy the JSON Schema (the cross-language contract).
    validate_json(contract, parsed.model_dump(mode="json", exclude_none=False))


def test_fixture_files_validate():
    fixtures = REPO_ROOT / "data" / "fixtures"
    for cam_id, batch in _load(fixtures / "qwen_observations.json").items():
        validate_json("observation_batch", batch)
        assert ObservationBatch.model_validate(batch).camera_id == cam_id
    validate_json("hypothesis", _load(fixtures / "final_hypothesis.json"))


# --- ground-truth access invariant -------------------------------------------------


def test_schema_rejects_model_accessible_ground_truth(scenario_doc):
    scenario_doc["ground_truth_camera"]["model_access"] = True
    with pytest.raises(ValidationError):
        validate_json("scenario", scenario_doc)
    with pytest.raises(PydanticError):
        Scenario.model_validate(scenario_doc)


def test_schema_rejects_ground_truth_missing_model_access(scenario_doc):
    del scenario_doc["ground_truth_camera"]["model_access"]
    assert not is_valid("scenario", scenario_doc)
    with pytest.raises(PydanticError):
        Scenario.model_validate(scenario_doc)


def test_schema_rejects_visible_camera_without_access(scenario_doc):
    scenario_doc["visible_cameras"][1]["model_access"] = False
    assert not is_valid("scenario", scenario_doc)
    with pytest.raises(PydanticError):
        Scenario.model_validate(scenario_doc)


@pytest.mark.parametrize("field", ["id", "file"])
def test_ground_truth_cannot_alias_a_visible_camera(scenario_doc, field):
    scenario_doc["ground_truth_camera"][field] = scenario_doc["visible_cameras"][0][field]
    with pytest.raises(PydanticError):
        Scenario.model_validate(scenario_doc)


def test_duplicate_visible_ids_rejected(scenario_doc):
    scenario_doc["visible_cameras"][1]["id"] = scenario_doc["visible_cameras"][0]["id"]
    with pytest.raises(PydanticError):
        Scenario.model_validate(scenario_doc)


def test_assignment_cannot_flip_ground_truth_access(scenario_doc):
    scenario = Scenario.model_validate(scenario_doc)
    leaked = scenario.ground_truth_camera.model_copy(update={"model_access": True})
    with pytest.raises(PydanticError):
        scenario.ground_truth_camera = leaked


def test_model_view_contains_no_trace_of_ground_truth(scenario_doc):
    scenario = Scenario.model_validate(scenario_doc)
    gt = scenario.ground_truth_camera
    dumped = scenario.model_view().model_dump_json()
    assert gt.id not in dumped
    assert gt.file not in dumped
    assert Path(gt.file).name not in dumped
    assert "ground_truth" not in dumped
    assert "provenance" not in dumped
    assert [c.id for c in scenario.model_view().cameras] == [c.id for c in scenario.visible_cameras]


def test_model_view_is_closed_to_extra_fields(scenario_doc):
    view = Scenario.model_validate(scenario_doc).model_view().model_dump()
    view["ground_truth_camera"] = scenario_doc["ground_truth_camera"]
    with pytest.raises(PydanticError):
        ModelScenarioView.model_validate(view)


def test_model_view_refuses_inaccessible_camera(scenario_doc):
    view = Scenario.model_validate(scenario_doc).model_view().model_dump()
    view["cameras"].append({**copy.deepcopy(scenario_doc["ground_truth_camera"])})
    with pytest.raises(PydanticError):
        ModelScenarioView.model_validate(view)


def test_require_model_camera_blocks_ground_truth(scenario_doc):
    scenario = Scenario.model_validate(scenario_doc)
    assert scenario.require_model_camera("cam_01").id == "cam_01"
    with pytest.raises(GroundTruthAccessError):
        scenario.require_model_camera(scenario.ground_truth_camera.id)
    with pytest.raises(GroundTruthAccessError):
        scenario.require_model_camera("cam_nope")
    with pytest.raises(GroundTruthAccessError):
        scenario.model_view().camera(scenario.ground_truth_camera.id)


def test_evidence_bundle_rejects_ground_truth_camera_evidence():
    doc = _load(EXAMPLES / "evidence_bundle.json")
    doc["evidence"][0]["camera_id"] = "cam_gt"
    with pytest.raises(PydanticError):
        EvidenceBundle.model_validate(doc)
    doc = _load(EXAMPLES / "evidence_bundle.json")
    doc["cameras"][0]["model_access"] = False
    assert not is_valid("evidence_bundle", doc)
    with pytest.raises(PydanticError):
        EvidenceBundle.model_validate(doc)


# --- other structural invariants -----------------------------------------------------


def test_observation_time_order_enforced():
    batch = _load(EXAMPLES / "observation_batch.json")
    batch["observations"][0]["t_end"] = batch["observations"][0]["t_start"] - 1
    with pytest.raises(PydanticError):
        ObservationBatch.model_validate(batch)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_bounds(confidence):
    hyp = _load(EXAMPLES / "hypothesis.json")
    hyp["confidence"] = confidence
    assert not is_valid("hypothesis", hyp)
    with pytest.raises(PydanticError):
        Hypothesis.model_validate(hyp)


def test_abstain_is_first_class():
    assert Hypothesis.model_validate(_load(EXAMPLES / "hypothesis_abstain.json")).abstained


def test_bundle_rejects_dangling_evidence_reference():
    doc = _load(EXAMPLES / "evidence_bundle.json")
    doc["clusters"][0]["evidence_ids"].append("obs_missing")
    with pytest.raises(PydanticError):
        EvidenceBundle.model_validate(doc)


def test_media_manifest_indices_contiguous():
    doc = _load(EXAMPLES / "media_manifest.json")
    doc["frames"][1]["index"] = 5
    with pytest.raises(PydanticError):
        MediaManifest.model_validate(doc)


def test_sse_envelope_rejects_unknown_type_and_zero_seq():
    doc = _load(EXAMPLES / "sse_event.json")
    assert not is_valid("sse_envelope", {**doc, "type": "agent.thought"})
    assert not is_valid("sse_envelope", {**doc, "seq": 0})
    with pytest.raises(PydanticError):
        SseEnvelope.model_validate({**doc, "type": "agent.thought"})

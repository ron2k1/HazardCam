"""P01: contracts validate, pydantic mirrors agree with JSON Schema, GT invariant holds."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticError

from apps.api.schemas import (
    LINE_LABELS,
    REPO_ROOT,
    AlertDelivery,
    AlertMessage,
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
    load_schema,
    validate_json,
)
from apps.api.schemas.contracts import def_validator
from apps.api.services.alert_messages import load_alert_config, render_text

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
# Alert payload examples: ``$defs`` of the SSE envelope contract (the web mock imports them).
ALERT_EXAMPLES = {
    "alert_message.json": ("alert_message", AlertMessage),
    "alert_message_ping.json": ("alert_message", AlertMessage),
    "alert_message_unconfirmed.json": ("alert_message", AlertMessage),
    "alert_delivery.json": ("alert_delivery", AlertDelivery),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def scenario_doc() -> dict:
    return _load(EXAMPLES / "scenario_001.json")


def test_every_example_is_covered():
    assert {p.name for p in EXAMPLES.glob("*.json")} == set(EXAMPLE_CONTRACTS) | set(ALERT_EXAMPLES)


@pytest.mark.parametrize("filename", sorted(ALERT_EXAMPLES))
def test_alert_example_validates_and_round_trips(filename):
    def_name, model = ALERT_EXAMPLES[filename]
    doc = _load(EXAMPLES / filename)
    def_validator("sse_envelope", def_name).validate(doc)
    parsed = model.model_validate(doc)
    def_validator("sse_envelope", def_name).validate(parsed.model_dump(mode="json"))
    if model is AlertMessage:
        envelope = {
            "run_id": "run_example",
            "seq": 1,
            "ts": "2026-10-02T12:00:00.000Z",
            "type": "alert.message",
            "payload": {"message": doc},
        }
        validate_json("sse_envelope", envelope)
        SseEnvelope.model_validate(envelope)
        # text = "<URGENCY> — <headline>" (the headline alone when calm), "What to do", the
        # other "<label>: <value>" rows in order, then "— <product>"
        config = load_alert_config()
        rows = doc["text"].split("\n")
        urgent = doc["kind"] in ("ping", "alert")
        level_word = config.level_word(doc["level"])
        assert rows[0] == (f"{level_word} — {doc['headline']}" if urgent else doc["headline"])
        todo = [line for line in doc["lines"] if line["key"] == "what_to_do"]
        rest = [line for line in doc["lines"] if line["key"] != "what_to_do"]
        assert rows[1:-1] == [f"{line['label']}: {line['value']}" for line in [*todo, *rest]]
        assert rows[-1] == f"— {config.product}"
        assert doc["text"] == render_text(doc, config)


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


# --- alert payloads ---------------------------------------------------------------------


def _alert_envelope(event_type: str, payload: dict) -> dict:
    return {
        "run_id": "run_example",
        "seq": 3,
        "ts": "2026-10-02T12:00:00.000Z",
        "type": event_type,
        "payload": payload,
    }


def _bad_messages() -> dict[str, dict]:
    good = _load(EXAMPLES / "alert_message.json")
    cases = {
        "unknown kind": {**good, "kind": "panic"},
        "unknown level": {**good, "level": "critical"},
        "bad id": {**good, "id": "message-2"},
        "extra field": {**good, "reason": "cam_b.o1 bearing 350.3"},
        "missing text": {k: v for k, v in good.items() if k != "text"},
        "no lines": {**good, "lines": []},
        "label mismatch": {**good, "lines": [{**good["lines"][0], "label": "Where"}]},
        "unknown line key": {**good, "lines": [{"key": "score", "label": "Score", "value": "1"}]},
        "local timestamp": {**good, "created_at": "2026-10-02T12:00:07+02:00"},
    }
    return cases


@pytest.mark.parametrize("case", sorted(_bad_messages()))
def test_alert_message_violations_rejected_by_schema_and_model(case):
    bad = _bad_messages()[case]
    assert not is_valid("sse_envelope", _alert_envelope("alert.message", {"message": bad}))
    with pytest.raises(PydanticError):
        AlertMessage.model_validate(bad)
    with pytest.raises(PydanticError):
        SseEnvelope.model_validate(_alert_envelope("alert.message", {"message": bad}))


def test_alert_message_duplicate_line_keys_and_time_order_rejected():
    good = _load(EXAMPLES / "alert_message.json")
    with pytest.raises(PydanticError):
        AlertMessage.model_validate({**good, "lines": [good["lines"][0], good["lines"][0]]})
    with pytest.raises(PydanticError):
        AlertMessage.model_validate({**good, "t_start": 9.0, "t_end": 8.0})


@pytest.mark.parametrize(
    "bad",
    [
        {"message_id": "msg_02", "channel": "sms", "status": "sent", "detail": None},
        {"message_id": "msg_02", "channel": "telegram", "status": "delivered", "detail": None},
        {"message_id": "msg_02", "channel": "telegram", "status": "sent"},
        {"message_id": "msg_02", "channel": "telegram", "status": "failed", "detail": "x" * 201},
    ],
)
def test_alert_delivery_violations_rejected(bad):
    assert not is_valid("sse_envelope", _alert_envelope("alert.delivery", bad))
    if "detail" in bad:  # pydantic defaults a missing detail to null
        with pytest.raises(PydanticError):
            AlertDelivery.model_validate(bad)


def test_alert_payload_checks_apply_only_to_alert_types():
    doc = _load(EXAMPLES / "sse_event.json")
    assert is_valid("sse_envelope", doc)
    assert not is_valid("sse_envelope", {**doc, "type": "alert.message"})
    with pytest.raises(PydanticError):
        SseEnvelope.model_validate({**doc, "type": "alert.delivery"})


def test_line_labels_match_the_schema():
    one_of = load_schema("sse_envelope")["$defs"]["alert_line"]["oneOf"]
    pairs = {o["properties"]["key"]["const"]: o["properties"]["label"]["const"] for o in one_of}
    assert pairs == LINE_LABELS

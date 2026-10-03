"""Model step: upstream validation rules, the vLLM payload, caching, repair and audit."""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from hazards import review
from hazards.review import HazardReviewer, run_review
from inference.profiles import load_profile
from tests.unit.hazards._helpers import (
    STUB_MODEL,
    StubVLLM,
    evidence_from_payload,
    load_fixture,
    valid_report_for,
)
from tests.unit.hazards.conftest import gb10_like_endpoint

EXAMPLE = load_fixture("example_hazard_report.json")
MODEL_REPORT = load_fixture("example_model_report.json")
ZONES = EXAMPLE["zones"]
EVIDENCE_BY_ID = {e["evidence_id"]: e for e in EXAMPLE["evidence"]}
GB10_ENV = {"QWEN_MODEL": STUB_MODEL, "MISTRAL_MODEL": "nvidia/Cosmos-Reason2-8B"}


def _validate(report: dict[str, Any]) -> review.ModelReport:
    return review.validate_model_report(json.dumps(report), ZONES, EVIDENCE_BY_ID)


# --- validate_model_report (upstream rules) --------------------------------------------------


def test_the_teammate_model_report_validates():
    result = _validate(MODEL_REPORT)
    assert len(result.findings) == 2 and len(result.zone_reviews) == 10
    assert [f.title for f in result.findings] == [f["title"] for f in EXAMPLE["findings"]]


def _finding_evidence(r: dict) -> None:
    r["findings"][0]["evidence_ids"].append("E099")


def _drop_zone_review(r: dict) -> None:
    r["zone_reviews"].pop()


def _duplicate_zone_review(r: dict) -> None:
    r["zone_reviews"][-1] = copy.deepcopy(r["zone_reviews"][0])


def _full_scene_only(r: dict) -> None:
    r["zone_reviews"][0]["evidence_ids"] = ["E001"]


def _other_zones_crop(r: dict) -> None:
    other = next(e for e in EVIDENCE_BY_ID.values() if e["zone_id"] == "Z02")
    r["zone_reviews"][0]["evidence_ids"] = [other["evidence_id"]]


def _unknown_zone(r: dict) -> None:
    r["findings"][0]["zone_ids"] = ["Z99"]


def _bad_standard(r: dict) -> None:
    r["findings"][0]["standards"] = ["1910.999(z)"]


def _dismissed_evidence(r: dict) -> None:
    r["dismissed"] = [{"concern": "x", "reason": "y", "evidence_ids": ["E777"]}]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_finding_evidence, "Model referenced evidence not supplied"),
        (_dismissed_evidence, "Model referenced evidence not supplied"),
        (_drop_zone_review, "Model must review every proposed zone exactly once"),
        (_duplicate_zone_review, "Model must review every proposed zone exactly once"),
        (_full_scene_only, "Zone Z01 review must cite its own labeled crop"),
        (_other_zones_crop, "Zone Z01 review must cite its own labeled crop"),
        (_unknown_zone, "Unknown zone in finding"),
        (_bad_standard, "Citation outside verified reference set"),
    ],
)
def test_validation_rejects(mutate: Callable[[dict], None], message: str):
    report = copy.deepcopy(MODEL_REPORT)
    mutate(report)
    with pytest.raises(ValueError, match=message):
        _validate(report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(extra="x"),
        lambda r: r["findings"][0].update(severity="extreme"),
        lambda r: r["findings"][0].update(evidence_ids=[]),
        lambda r: r["zone_reviews"][0].update(disposition="fine"),
        lambda r: r.pop("limitations"),
    ],
)
def test_schema_violations_are_rejected(mutate):
    report = copy.deepcopy(MODEL_REPORT)
    mutate(report)
    with pytest.raises(ValueError):
        _validate(report)


def test_invalid_json_is_rejected():
    with pytest.raises(ValueError):
        review.validate_model_report("{not json", ZONES, EVIDENCE_BY_ID)


# --- request payload --------------------------------------------------------------------------


@pytest.fixture
def small_case(tmp_path: Path) -> dict[str, Any]:
    """Two zones, five evidence JPEGs on disk."""
    (tmp_path / "evidence").mkdir()
    records = [
        ("E001", "full scene", None),
        ("E002", "zone crop", "Z01"),
        ("E003", "zone crop", "Z01"),
        ("E004", "zone crop", "Z02"),
        ("E005", "scene tile", None),
    ]
    evidence = []
    for i, (eid, kind, zone_id) in enumerate(records):
        path = tmp_path / "evidence" / f"{eid}.jpg"
        cv2.imwrite(str(path), np.full((40, 60, 3), 30 * i, np.uint8))
        evidence.append(
            {
                "evidence_id": eid,
                "frame_index": i,
                "timestamp_s": i / 10,
                "kind": kind,
                "zone_id": zone_id,
                "bbox_source": [0, 0, 60, 40],
                "path": f"evidence/{eid}.jpg",
                "sha256": "0" * 64,
            }
        )
    zones = [dict(ZONES[0], zone_id="Z01"), dict(ZONES[5], zone_id="Z02")]
    meta = {"source_name": "hz_42", "fps": 10.0, "decoded_frames": 5}
    return {
        "out": tmp_path,
        "meta": meta,
        "zones": zones,
        "evidence": evidence,
        "quality_warnings": ["Q1"],
    }


def _gb10_reviewer(stub: StubVLLM) -> HazardReviewer:
    profile = load_profile("gb10", env=GB10_ENV)
    return HazardReviewer.from_profile(profile, transport=stub.transport, env=GB10_ENV)


def test_payload_matches_the_upstream_request_on_vllm(small_case):
    stub = StubVLLM()
    reviewer = _gb10_reviewer(stub)
    assert reviewer.model == STUB_MODEL and reviewer.base_url == "http://127.0.0.1:8000/v1"
    assert reviewer.profile_name == "gb10"
    schema = review.build_schema([e["evidence_id"] for e in small_case["evidence"]], ["Z01", "Z02"])
    messages = review.build_messages(
        small_case["out"],
        meta=small_case["meta"],
        zones=small_case["zones"],
        evidence=small_case["evidence"],
        quality_warnings=small_case["quality_warnings"],
        schema=schema,
    )
    payload = reviewer.build_payload(messages, schema)

    assert payload["model"] == STUB_MODEL
    assert payload["temperature"] == 0.0 and payload["seed"] == 42
    assert payload["max_tokens"] == 6000 and payload["stream"] is False
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in payload
    fmt = payload["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "hazard_report" and fmt["json_schema"]["strict"] is True
    defs = fmt["json_schema"]["schema"]["$defs"]
    assert defs["Finding"]["properties"]["evidence_ids"]["items"]["enum"] == [
        "E001",
        "E002",
        "E003",
        "E004",
        "E005",
    ]
    assert defs["ZoneReview"]["properties"]["zone_id"]["enum"] == ["Z01", "Z02"]
    assert defs["Finding"]["properties"]["standards"]["items"]["enum"] == list(review.STANDARDS)

    msgs = payload["messages"]
    assert msgs[0] == {"role": "system", "content": review.HAZARD_MODE.system_prompt}
    assert msgs[1]["content"].startswith(review.INTRO_PREFIX)
    intro = json.loads(msgs[1]["content"][len(review.INTRO_PREFIX) :])
    assert list(intro) == [
        "video",
        "zones",
        "evidence",
        "references",
        "quality_warnings",
        "response_schema",
    ]
    assert intro["references"] == review.STANDARDS and intro["quality_warnings"] == ["Q1"]
    assert msgs[-1] == {"role": "user", "content": review.FINAL_INSTRUCTION}
    image_messages = msgs[2:-1]
    assert len(image_messages) == len(small_case["evidence"])
    for message, record in zip(image_messages, small_case["evidence"], strict=True):
        text, image = message["content"]
        assert message["role"] == "user"
        assert text == {"type": "text", "text": json.dumps(record)}
        assert image["type"] == "image_url"
        url = image["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        raw = base64.b64decode(url.split(",", 1)[1])
        assert raw == (small_case["out"] / record["path"]).read_bytes()
    image_parts = [
        p
        for m in msgs
        if isinstance(m["content"], list)
        for p in m["content"]
        if p["type"] == "image_url"
    ]
    assert len(image_parts) == len(small_case["evidence"])


def test_review_endpoint_pins_upstream_limits():
    endpoint = review.review_endpoint(gb10_like_endpoint())
    assert endpoint.timeout_seconds == 900 and endpoint.max_tokens == 6000
    assert endpoint.temperature == 0.0 and endpoint.retries == 0
    assert endpoint.think is False and endpoint.structured_output == "json_schema"


def test_fixture_profile_has_no_model_for_the_review():
    with pytest.raises(ValueError, match="no model endpoint"):
        HazardReviewer.from_profile(load_profile("fixture", env={}))


@pytest.mark.parametrize(
    "url",
    ["http://8.8.8.8:8000/v1", "https://api.example.com/v1", "http://[2001:4860::1]:80/v1"],
)
def test_public_model_urls_are_rejected(url):
    with pytest.raises(ValueError, match="local-only"):
        HazardReviewer(gb10_like_endpoint(base_url=url), env={})


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000/v1", "http://localhost:8000/v1", "http://172.18.0.1:8000/v1"]
)
def test_local_model_urls_are_accepted(url):
    assert HazardReviewer(gb10_like_endpoint(base_url=url), env={}).base_url == url


# --- run_review -------------------------------------------------------------------------------


def _run(reviewer: HazardReviewer, case: dict[str, Any], refresh: bool = False):
    return run_review(
        reviewer,
        case["out"],
        meta=case["meta"],
        zones=case["zones"],
        evidence=case["evidence"],
        quality_warnings=case["quality_warnings"],
        refresh=refresh,
    )


def test_review_and_audit_complete_with_a_stub_server(small_case):
    stub = StubVLLM()
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.status == review.STATUS_COMPLETE and outcome.error is None
    assert outcome.result is not None and len(outcome.result.zone_reviews) == 2
    assert outcome.images_sent == 5 and outcome.payload_bytes
    meta = outcome.metadata
    assert meta["name"] == STUB_MODEL and meta["profile"] == "gb10"
    assert meta["inference_source"] == "fresh" and meta["audit_source"] == "fresh"
    assert meta["calls"] == 1 and meta["finish_reason"] == "stop"
    assert (meta["prompt_tokens"], meta["completion_tokens"]) == (1234, 321)
    assert meta["audit"]["prompt_tokens"] == 1234
    assert meta["thinking"] is False and meta["max_model_len"] == 262144
    assert len(stub.chat_payloads) == 2 and stub.model_calls == 1
    key = outcome.request_sha256[:16]
    out = small_case["out"]
    assert (out / f"qwen_{key}.json").is_file()
    assert (out / f"qwen_raw_{key}_1.json").is_file()
    assert (out / f"qwen_audited_{meta['audit_sha256'][:16]}.json").is_file()
    assert (out / f"qwen_audit_raw_{meta['audit_sha256'][:16]}.json").is_file()
    review_request, audit_request = stub.chat_payloads
    n = len(small_case["evidence"])
    assert audit_request["messages"][: 2 + n + 1] == review_request["messages"][: 2 + n + 1]
    assert audit_request["messages"][-2]["role"] == "assistant"
    assert audit_request["messages"][-1] == {"role": "user", "content": review.HAZARD_MODE.audit_prompt}


def test_second_run_uses_the_sha256_caches(small_case):
    stub = StubVLLM()
    first = _run(_gb10_reviewer(stub), small_case)
    again = StubVLLM()
    second = _run(_gb10_reviewer(again), small_case)
    assert second.status == review.STATUS_COMPLETE
    assert again.chat_payloads == [] and again.model_calls == 1
    assert second.metadata["inference_source"] == "cache"
    assert second.metadata["audit_source"] == "cache"
    assert second.request_sha256 == first.request_sha256
    refreshed = StubVLLM()
    third = _run(_gb10_reviewer(refreshed), small_case, refresh=True)
    assert len(refreshed.chat_payloads) == 2 and third.metadata["inference_source"] == "fresh"


def test_changed_served_model_misses_the_cache(small_case):
    """The served id/root/max_model_len fingerprint replaces the Ollama digest in the key."""
    first = _run(_gb10_reviewer(StubVLLM()), small_case)
    other = StubVLLM(max_model_len=131072)
    outcome = _run(_gb10_reviewer(other), small_case)
    assert outcome.metadata["inference_source"] == "fresh" and len(other.chat_payloads) == 2
    assert outcome.request_sha256 != first.request_sha256
    assert outcome.metadata["fingerprint"] != first.metadata["fingerprint"]


def test_one_repair_turn(small_case):
    def responder(payload: dict, call: int) -> tuple[str, str]:
        report = valid_report_for(payload)
        if call == 0:
            report["zone_reviews"].pop()  # invalid: a zone is not reviewed
        return json.dumps(report), "stop"

    stub = StubVLLM(responder=responder)
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.status == review.STATUS_COMPLETE and outcome.metadata["calls"] == 2
    repair = stub.chat_payloads[1]["messages"]
    assert repair[-2]["role"] == "assistant"
    assert repair[-1]["content"].startswith("Repair the JSON. Validation error: Model must review")
    assert repair[-1]["content"].endswith(
        "Preserve evidence grounding and review all zones exactly once."
    )
    assert len(stub.chat_payloads) == 3  # review, repair, audit


def test_truncated_output_fails_after_the_repair(small_case):
    stub = StubVLLM(responder=lambda payload, call: ("{}", "length"))
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.status == review.STATUS_FAILED and outcome.result is None
    assert outcome.error == "ValueError: Model response was truncated; increase num_predict"
    assert len(stub.chat_payloads) == 2


def test_http_errors_fail_without_retry(small_case):
    stub = StubVLLM(status=400)
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.status == review.STATUS_FAILED
    assert outcome.error.startswith("ModelCallError:") and "HTTP 400" in outcome.error
    assert len(stub.chat_payloads) == 1


def test_model_not_served(small_case):
    stub = StubVLLM(served=["some/other-model"])
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.status == review.STATUS_FAILED
    assert outcome.error == (
        f"RuntimeError: {STUB_MODEL} is not served at http://127.0.0.1:8000/v1"
    )
    assert stub.chat_payloads == []


def test_audit_failure_marks_the_review_failed(small_case):
    def responder(payload: dict, call: int) -> tuple[str, str]:
        if call == 1:
            return json.dumps({"scene_summary": "x"}), "stop"
        return json.dumps(valid_report_for(payload)), "stop"

    outcome = _run(_gb10_reviewer(StubVLLM(responder=responder)), small_case)
    assert outcome.status == review.STATUS_FAILED and outcome.result is None
    assert outcome.error.startswith("Review pass failed: ValidationError")


def test_payload_size_limit(small_case, monkeypatch):
    monkeypatch.setitem(review.CFG, "max_payload_mb", 0.001)
    stub = StubVLLM()
    outcome = _run(_gb10_reviewer(stub), small_case)
    assert outcome.error == "ValueError: Evidence payload exceeds configured size limit"
    assert stub.chat_payloads == []


def test_evidence_text_parts_round_trip(small_case):
    stub = StubVLLM()
    _run(_gb10_reviewer(stub), small_case)
    assert evidence_from_payload(stub.chat_payloads[0]) == small_case["evidence"]

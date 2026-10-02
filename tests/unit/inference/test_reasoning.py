"""P09: hypothesis post-validation, bundle-only input, repair/abstain paths, fixtures."""

from __future__ import annotations

import json

import pytest

from apps.api.schemas import UNKNOWN, EvidenceBundle, Hypothesis, validate_json
from inference.base import AdapterError, CallInfo, ReasoningAdapter, ReasoningOptions
from inference.profiles import EndpointConfig, ModelProfile
from inference.reasoning import (
    MAX_ALTERNATIVES,
    FixtureReasoningAdapter,
    OpenAICompatReasoningAdapter,
    OutputFormatError,
    abstain,
    allowed_regions,
    bundle_message,
    hypothesis_schema,
    postprocess_hypothesis,
)
from inference.vocab import HYPOTHESIS_EVENT_TYPES, NOT_DIRECTLY_VISIBLE
from tools.submit import INSUFFICIENT_CONFIDENCE_CAP, submit_hypothesis

IDS = ["obs_a_001", "obs_b_001", "obs_c_001"]


def _claim(**kw):
    base = {
        "reason": "Braking and head turns on two cameras precede a downstream queue.",
        "evidence_ids": IDS,
        "event_type": "passenger_dropoff_pickup",
        "region": "blind_zone_02",
        "confidence": 0.72,
        "alternatives": [{"event_type": "vehicle_stop", "confidence": 0.3}],
        "limitations": ["Coarse region only."],
    }
    return {**base, **kw}


def _insufficient(bundle: EvidenceBundle) -> EvidenceBundle:
    """One weak cue from one camera; fusion found no cluster and no region candidate."""
    data = bundle.model_dump(mode="json")
    data.update(
        status="insufficient", evidence=data["evidence"][:1], clusters=[], region_candidates=[]
    )
    return EvidenceBundle.model_validate(data)


# --- post-processing ----------------------------------------------------------------------


def test_valid_claim_passes_through_and_satisfies_the_contract(bundle):
    hyp, warnings, dropped = postprocess_hypothesis(_claim(), bundle)
    assert (hyp.event_type, hyp.region, hyp.confidence) == (
        "passenger_dropoff_pickup",
        "blind_zone_02",
        0.72,
    )
    assert hyp.evidence_ids == IDS and warnings == [] and dropped == 0
    validate_json("hypothesis", hyp.model_dump(mode="json"))


def test_wrapped_hypothesis_object_is_unwrapped(bundle):
    hyp, _, _ = postprocess_hypothesis({"hypothesis": _claim()}, bundle)
    assert hyp.region == "blind_zone_02"


def test_unknown_and_malformed_evidence_ids_are_dropped(bundle):
    raw = _claim(evidence_ids=["obs_a_001", "obs_zz_404", 7, "obs_a_001", "obs_b_001"])
    hyp, _, dropped = postprocess_hypothesis(raw, bundle)
    assert hyp.evidence_ids == ["obs_a_001", "obs_b_001"] and dropped == 2
    assert "Dropped 2 evidence reference(s) not in the bundle." in hyp.limitations


@pytest.mark.parametrize(
    "region, expected",
    [("intersection core", "blind_zone_02"), ("BLIND_ZONE_02", "blind_zone_02"), (None, UNKNOWN)],
)
def test_region_maps_by_label_or_case(bundle, region, expected):
    hyp, warnings, _ = postprocess_hypothesis(_claim(region=region), bundle)
    assert hyp.region == expected and warnings == []


def test_invented_region_becomes_unknown_with_a_limitation(bundle):
    hyp, warnings, _ = postprocess_hypothesis(_claim(region="the bakery on 5th"), bundle)
    assert hyp.region == UNKNOWN
    assert any("not a fusion candidate" in lim for lim in hyp.limitations)
    assert warnings == ["region 'the bakery on 5th' replaced by unknown"]


def test_event_type_synonym_is_normalized(bundle):
    hyp, _, _ = postprocess_hypothesis(_claim(event_type="Vehicle drops off person"), bundle)
    assert hyp.event_type == "passenger_dropoff_pickup"


def test_event_type_outside_vocabulary_becomes_unknown(bundle):
    hyp, _, _ = postprocess_hypothesis(_claim(event_type="alien landing"), bundle)
    assert hyp.event_type == UNKNOWN and hyp.abstained
    assert any("outside the allowed vocabulary" in lim for lim in hyp.limitations)


@pytest.mark.parametrize(
    "raw, expected", [(92, 0.92), ("80%", 0.8), ("high", 0.8), (-1, 0.0), (None, 0.0), (0.5, 0.5)]
)
def test_confidence_is_rescaled_and_clamped(bundle, raw, expected):
    hyp, _, _ = postprocess_hypothesis(_claim(confidence=raw), bundle)
    assert hyp.confidence == pytest.approx(expected)


def test_alternatives_are_deduped_sorted_capped_and_exclude_the_main_claim(bundle):
    alts = [
        {"event_type": "vehicle_stop", "confidence": 0.2},
        {"event_type": "vehicle_stop", "confidence": 0.4},
        {"event_type": "passenger_dropoff_pickup", "confidence": 0.9},
        {"event_type": "vehicle_departure", "confidence": 0.1},
        {"event_type": "no_event", "confidence": 0.3},
        {"event_type": "U-turn", "confidence": 0.35},
        {"event_type": "time travel", "confidence": 0.9},
        "cyclist_movement",
    ]
    hyp, _, dropped = postprocess_hypothesis(_claim(alternatives=alts), bundle)
    assert [(a.event_type, a.confidence) for a in hyp.alternatives] == [
        ("vehicle_stop", 0.4),
        ("vehicle_turnaround", 0.35),
        ("no_event", 0.3),
    ]
    assert len(hyp.alternatives) == MAX_ALTERNATIVES and dropped == 1  # "time travel"


def test_limitations_always_present_and_cleaned(bundle):
    hyp, _, _ = postprocess_hypothesis(
        _claim(limitations="**Only** `coarse`   region", reason="Cars **brake** at `obs_a_001`."),
        bundle,
    )
    assert hyp.limitations == ["Only coarse region", NOT_DIRECTLY_VISIBLE]
    assert hyp.reason == "Cars brake at obs_a_001."


def test_missing_limitations_still_yields_one(bundle):
    raw = {k: v for k, v in _claim().items() if k != "limitations"}
    hyp, _, _ = postprocess_hypothesis(raw, bundle)
    assert hyp.limitations == [NOT_DIRECTLY_VISIBLE]


@pytest.mark.parametrize("raw", [{"answer": "collision"}, [_claim()], "collision", None])
def test_unusable_output_raises_output_format_error(bundle, raw):
    with pytest.raises(OutputFormatError):
        postprocess_hypothesis(raw, bundle)


def test_well_formed_output_is_a_fixed_point_of_the_submit_gate(bundle):
    hyp, _, _ = postprocess_hypothesis(_claim(), bundle)
    assert submit_hypothesis(hyp, bundle) == hyp


def test_abstain_is_schema_valid_and_keeps_the_visibility_limitation():
    hyp = abstain("nothing to go on", ["No evidence."])
    assert hyp.abstained and hyp.region == UNKNOWN and hyp.confidence == 0.0
    assert hyp.limitations == ["No evidence.", NOT_DIRECTLY_VISIBLE]
    validate_json("hypothesis", hyp.model_dump(mode="json"))


def test_schema_enumerates_bundle_ids_regions_and_event_vocab(bundle):
    props = hypothesis_schema(bundle)["properties"]
    assert next(iter(props)) == "reason"  # justification is generated before the label
    assert props["evidence_ids"]["items"]["enum"] == IDS
    assert props["region"]["enum"] == ["blind_zone_02", UNKNOWN] == allowed_regions(bundle)
    assert props["event_type"]["enum"] == list(HYPOTHESIS_EVENT_TYPES)
    assert props["limitations"]["minItems"] == 1


def test_schema_for_an_empty_bundle_forbids_citations(bundle):
    empty = bundle.model_copy(update={"evidence": [], "clusters": [], "region_candidates": []})
    props = hypothesis_schema(empty)["properties"]
    assert props["evidence_ids"]["maxItems"] == 0 and props["region"]["enum"] == [UNKNOWN]


def test_bundle_message_is_only_the_bundle_and_derived_lists(bundle):
    msg = bundle_message(bundle)
    head, _, tail = msg.partition("\n\n")
    assert head.startswith("EVIDENCE_BUNDLE:\n")
    assert json.loads(head.split("\n", 1)[1]) == bundle.model_dump(mode="json", exclude_none=True)
    assert tail.splitlines() == [
        "Bundle status: ok",
        f"Valid evidence_ids: {json.dumps(IDS)}",
        'Valid region values: ["blind_zone_02", "unknown"]',
        "Return only the JSON object.",
    ]


# --- live adapter over a mock OpenAI-compatible server ------------------------------------


def _adapter(profile, server, **endpoint) -> OpenAICompatReasoningAdapter:
    if endpoint:
        profile = profile.model_copy(
            update={"reasoning": profile.reasoning.model_copy(update=endpoint)}
        )
    return OpenAICompatReasoningAdapter(profile, transport=server.transport, sleep=lambda s: None)


def test_request_contains_only_the_bundle(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply(_claim()))
    _adapter(lite_profile, server).reason(bundle, ReasoningOptions())
    (req,) = server.requests
    assert req["model"] == "ministral-3:3b" and req["reasoning_effort"] == "none"
    system, user = req["messages"]
    assert system["role"] == "system" and "event_type" in system["content"]
    assert user == {"role": "user", "content": bundle_message(bundle)}
    schema = req["response_format"]["json_schema"]
    assert schema["name"] == "hypothesis"
    assert schema["schema"]["properties"]["region"]["enum"] == ["blind_zone_02", UNKNOWN]


def test_happy_path_records_side_channel(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply("```json\n" + json.dumps(_claim()) + "\n```", model="ministral"))
    infos: list[CallInfo] = []
    adapter = _adapter(lite_profile, server)
    hyp = adapter.reason(bundle, ReasoningOptions(telemetry=infos.append))
    assert hyp.region == "blind_zone_02" and not hyp.abstained
    (info,) = infos
    assert info.ok and info.model == "ministral" and info.latency_s > 0 and not info.repaired
    assert info.scenario_id == "scenario_001" and info.usage["total_tokens"] == 120


def test_invalid_output_gets_one_conversational_repair(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply("It was probably a crash."), reply(_claim()))
    adapter = _adapter(lite_profile, server)
    hyp = adapter.reason(bundle, ReasoningOptions())
    assert hyp.event_type == "passenger_dropoff_pickup" and adapter.last_call.repaired
    roles = [m["role"] for m in server.requests[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert server.requests[1]["messages"][2]["content"] == "It was probably a crash."
    assert "could not be used" in server.requests[1]["messages"][3]["content"]


def test_invalid_twice_abstains_and_surfaces_failure(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply("no"), reply('{"answer": 1}'))
    adapter = _adapter(lite_profile, server)
    hyp = adapter.reason(bundle, ReasoningOptions())
    assert hyp.abstained and hyp.region == UNKNOWN and hyp.confidence == 0.0
    assert any("invalid after one repair" in lim for lim in hyp.limitations)
    assert not adapter.last_call.ok and "after repair" in adapter.last_call.error
    validate_json("hypothesis", hyp.model_dump(mode="json"))


def test_endpoint_failure_abstains(lite_profile, bundle, mock_server):
    adapter = _adapter(lite_profile, mock_server(503))
    hyp = adapter.reason(bundle, ReasoningOptions())
    assert hyp.abstained and any("Reasoning model failed" in lim for lim in hyp.limitations)
    assert adapter.last_call.attempts == lite_profile.reasoning.retries + 1


def test_strict_mode_raises(lite_profile, bundle, mock_server):
    with pytest.raises(AdapterError, match="HTTP 503"):
        _adapter(lite_profile, mock_server(503)).reason(bundle, ReasoningOptions(strict=True))


def test_empty_evidence_abstains_without_a_model_call(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply(_claim()))
    empty = bundle.model_copy(update={"evidence": [], "clusters": [], "region_candidates": []})
    adapter = _adapter(lite_profile, server)
    hyp = adapter.reason(empty, ReasoningOptions())
    assert hyp.abstained and server.requests == [] and adapter.last_call.ok
    assert "No evidence from any model input camera." in hyp.limitations


def test_insufficient_bundle_abstention_survives_the_gate(lite_profile, bundle, mock_server, reply):
    weak = _insufficient(bundle)
    abstention = _claim(
        event_type="unknown",
        region="unknown",
        confidence=0.15,
        evidence_ids=["obs_a_001"],
        alternatives=[{"event_type": "no_event", "confidence": 0.5}],
        limitations=["Single weak cue from one camera."],
    )
    server = mock_server(reply(abstention))
    hyp = _adapter(lite_profile, server).reason(weak, ReasoningOptions())
    assert hyp.abstained and hyp.region == UNKNOWN and hyp.confidence <= INSUFFICIENT_CONFIDENCE_CAP
    assert "Bundle status: insufficient" in server.requests[0]["messages"][1]["content"]
    assert server.requests[0]["response_format"]["json_schema"]["schema"]["properties"]["region"][
        "enum"
    ] == [UNKNOWN]
    assert submit_hypothesis(hyp, weak) == hyp


def test_overconfident_claim_on_insufficient_bundle_is_capped_by_the_gate(
    lite_profile, bundle, mock_server, reply
):
    weak = _insufficient(bundle)
    server = mock_server(reply(_claim(evidence_ids=["obs_a_001"], confidence=0.95)))
    hyp = _adapter(lite_profile, server).reason(weak, ReasoningOptions())
    assert hyp.region == UNKNOWN  # no candidate exists to name
    gated = submit_hypothesis(hyp, weak)
    assert gated.confidence == INSUFFICIENT_CONFIDENCE_CAP


def test_context_overflow_is_flagged(lite_profile, bundle, mock_server, reply):
    server = mock_server(reply(_claim()))
    adapter = _adapter(lite_profile, server, context_tokens=800, max_tokens=256)
    hyp = adapter.reason(bundle, ReasoningOptions())
    assert any("context window" in w for w in adapter.last_call.warnings)
    assert any("context window" in lim for lim in hyp.limitations)


# --- fixture adapter ----------------------------------------------------------------------


def test_fixture_adapter_returns_contract_valid_hypothesis(fixture_profile, bundle):
    adapter = FixtureReasoningAdapter(fixture_profile)
    hyp = adapter.reason(bundle, ReasoningOptions())
    validate_json("hypothesis", hyp.model_dump(mode="json"))
    assert set(hyp.evidence_ids) <= bundle.evidence_ids()
    assert adapter.last_call.ok and adapter.last_call.warnings == []


def test_fixture_and_live_adapters_share_the_interface(fixture_profile, lite_profile):
    assert isinstance(FixtureReasoningAdapter(fixture_profile), ReasoningAdapter)
    assert isinstance(OpenAICompatReasoningAdapter(lite_profile), ReasoningAdapter)


def _fixture_profile(tmp_path, shared: dict) -> ModelProfile:
    path = tmp_path / "final_hypothesis.json"
    path.write_text(json.dumps(shared), encoding="utf-8")
    ep = EndpointConfig(backend="fixture", fixture=str(path), fixture_dir=str(tmp_path))
    return ModelProfile(profile="t", mode="fixture", perception=ep, reasoning=ep)


def test_per_scenario_fixture_is_preferred(tmp_path, bundle):
    profile = _fixture_profile(tmp_path, _claim())
    (tmp_path / "scenario_001").mkdir()
    (tmp_path / "scenario_001" / "final_hypothesis.json").write_text(
        json.dumps(_claim(event_type="vehicle_stop", alternatives=[])), encoding="utf-8"
    )
    adapter = FixtureReasoningAdapter(profile)
    assert adapter.reason(bundle, ReasoningOptions()).event_type == "vehicle_stop"
    other = bundle.model_copy(update={"scenario_id": "scenario_002"})
    assert adapter.reason(other, ReasoningOptions()).event_type == _claim()["event_type"]


def test_fixture_citing_foreign_evidence_is_flagged(tmp_path, bundle):
    adapter = FixtureReasoningAdapter(_fixture_profile(tmp_path, _claim(evidence_ids=["obs_x"])))
    adapter.reason(bundle, ReasoningOptions())
    assert any("not in this bundle" in w for w in adapter.last_call.warnings)


def test_unreadable_fixture_abstains_and_strict_raises(tmp_path, bundle):
    ep = EndpointConfig(backend="fixture", fixture=str(tmp_path / "missing.json"))
    adapter = FixtureReasoningAdapter(
        ModelProfile(profile="t", mode="fixture", perception=ep, reasoning=ep)
    )
    hyp = adapter.reason(bundle, ReasoningOptions())
    assert isinstance(hyp, Hypothesis) and hyp.abstained and not adapter.last_call.ok
    with pytest.raises(AdapterError):
        adapter.reason(bundle, ReasoningOptions(strict=True))

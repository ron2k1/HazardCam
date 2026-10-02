"""P12: per-scenario scoring and the summary, against the real judge-only labels.

The labels are the prepared ``data/prepared/<id>/expected.json`` files. The hypotheses and
bundles here are hand-built inputs to the scoring rules (``eval/SCORING.md``); no score
in this file is reported as a result.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from apps.api.schemas import REPO_ROOT, UNKNOWN, EvidenceBundle, Hypothesis
from eval.scoring import CORRECT_OUTCOMES, class_ok, outcome, score_run, temporal_iou
from eval.summary import constant_baselines, summarize, wilson
from harness.dev_sequence import DevSequenceResult
from inference.vocab import HYPOTHESIS_EVENT_TYPES, NO_EVENT

PREPARED = REPO_ROOT / "data" / "prepared"
EXPECTED = {
    p.parent.name: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(PREPARED.glob("*/expected.json"))
}
EAST = [-2.0, 15.0]  # z_east_pocket center
FAR = [7.19, 42.696]  # a region_01 center recorded for scenario_001


def _bundle(scenario_id: str) -> EvidenceBundle:
    return EvidenceBundle.model_validate(
        {
            "scenario_id": scenario_id,
            "status": "ok",
            "cameras": [{"id": "cam_a"}, {"id": "cam_b"}],
            "evidence": [
                {
                    "id": f"obs_{c}",
                    "camera_id": f"cam_{c}",
                    "t_start": 4.0,
                    "t_end": 12.0,
                    "cue_type": "vehicle_slowing_or_stopping",
                    "description": "a van slows near the frame edge",
                    "confidence": 0.7,
                }
                for c in "ab"
            ],
            "clusters": [
                {
                    "id": "clu_01",
                    "t_start": 4.0,
                    "t_end": 12.0,
                    "evidence_ids": ["obs_a", "obs_b"],
                    "camera_ids": ["cam_a", "cam_b"],
                    "score": 0.6,
                }
            ],
            "region_candidates": [
                {
                    "id": "z_east_pocket",
                    "center": EAST,
                    "radius_m": 10.0,
                    "score": 0.5,
                    "camera_ids": ["cam_a"],
                    "evidence_ids": ["obs_a"],
                    "method": "zone_prior",
                },
                {
                    "id": "region_01",
                    "center": FAR,
                    "radius_m": 25.0,
                    "score": 0.4,
                    "camera_ids": ["cam_a", "cam_b"],
                    "evidence_ids": ["obs_a", "obs_b"],
                    "method": "ray_intersection",
                },
            ],
        }
    )


def _hypothesis(event_type: str, region: str = UNKNOWN, **extra: Any) -> Hypothesis:
    cited = [] if event_type in (UNKNOWN, NO_EVENT) else ["obs_a", "obs_b"]
    return Hypothesis.model_validate(
        {
            "event_type": event_type,
            "region": region,
            "confidence": 0.7,
            "evidence_ids": cited,
            "reason": "built for a scoring test",
            "alternatives": [],
            "limitations": [],
            **extra,
        }
    )


def _result(scenario_id: str, event_type: str, region: str = UNKNOWN, **extra: Any):
    hypothesis = _hypothesis(event_type, region, **extra)
    return DevSequenceResult(
        scenario_id=scenario_id,
        profile="test",
        manifests={},
        batches=[],
        bundle=_bundle(scenario_id),
        raw_hypothesis=hypothesis,
        hypothesis=hypothesis,
        supporting_frames={},
        adapter_calls=[
            {"role": "perception", "ok": True, "latency_s": 2.0, "camera_id": "cam_a"},
            {"role": "reasoning", "ok": True, "latency_s": 1.0, "camera_id": None},
        ],
        tool_latency_ms={"inspect_camera": [2000.0]},
        duration_ms=3500.0,
    )


def test_the_labels_cover_all_three_categories():
    counts = {c: sum(e["category"] == c for e in EXPECTED.values()) for c in CORRECT_OUTCOMES}
    assert len(EXPECTED) == 22
    assert counts == {"positive": 8, "negative": 7, "ambiguous": 7}


@pytest.mark.parametrize(
    ("scenario_id", "event_type", "ok", "label"),
    [
        ("eval_001", "passenger_dropoff_pickup", True, "hit"),
        ("eval_001", "vehicle_stop", True, "hit"),  # in the accepted set
        ("eval_001", "vehicle_turnaround", False, "wrong_class"),
        ("eval_001", UNKNOWN, False, "miss_abstain"),
        ("eval_001", NO_EVENT, False, "miss_no_event"),
        ("eval_005", UNKNOWN, True, "correct_reject"),
        ("eval_005", NO_EVENT, True, "correct_reject"),
        ("eval_005", "vehicle_stop", False, "false_alarm"),
        ("eval_003", "vehicle_turnaround", True, "hit"),
        ("eval_003", UNKNOWN, True, "abstain_ok"),
        ("eval_003", NO_EVENT, False, "miss_no_event"),  # the GT camera shows an event
        ("eval_003", "vehicle_stop", False, "wrong_class"),
        ("eval_003", None, False, "run_failed"),
    ],
)
def test_class_rule_per_category(scenario_id, event_type, ok, label):
    expected = EXPECTED[scenario_id]
    assert class_ok(event_type, expected) is ok
    assert outcome(event_type, expected) == label


def test_outcome_labels_agree_with_the_class_rule_on_every_label():
    for expected in EXPECTED.values():
        correct = CORRECT_OUTCOMES[expected["category"]]
        for event_type in HYPOTHESIS_EVENT_TYPES:
            label = outcome(event_type, expected)
            assert class_ok(event_type, expected) == (label in correct), (expected, event_type)


def test_constant_baselines_match_the_preregistered_numbers():
    baselines = constant_baselines(list(EXPECTED.values()))
    abstain = baselines["answers"][UNKNOWN]
    assert abstain["decision_accuracy"] == pytest.approx(14 / 22)
    assert abstain["balanced_accuracy"] == pytest.approx(2 / 3)
    assert baselines["best"]["decision_accuracy"] == {"answer": UNKNOWN, "value": 14 / 22}
    assert set(baselines["answers"]) == set(HYPOTHESIS_EVENT_TYPES)


def test_region_is_scored_for_event_claims_with_accepted_zones():
    expected = EXPECTED["eval_001"]
    point = expected["region"]["event_point_local_m"]

    hit = score_run(expected, _result("eval_001", "passenger_dropoff_pickup", "z_east_pocket"))
    assert hit.region_scored and hit.region_ok and hit.full_hit
    assert hit.localization_error_m == pytest.approx(math.dist(EAST, point), abs=0.01)

    miss = score_run(expected, _result("eval_001", "passenger_dropoff_pickup", "region_01"))
    assert miss.region_scored and miss.region_ok is False and miss.full_hit is False
    assert miss.localization_error_m == pytest.approx(math.dist(FAR, point), abs=0.01)
    assert miss.fusion_region_hit is True  # fusion had the right zone; the reasoner missed it
    assert miss.best_candidate_error_m == pytest.approx(math.dist(EAST, point), abs=0.01)


def test_region_is_not_scored_for_abstentions_or_negatives():
    abstain = score_run(EXPECTED["eval_003"], _result("eval_003", UNKNOWN))
    assert abstain.region_scored is False and abstain.region_ok is None
    assert abstain.localization_error_m is None and abstain.full_hit is None
    assert abstain.fusion_region_hit is True

    negative = score_run(EXPECTED["eval_005"], _result("eval_005", "vehicle_stop", "region_01"))
    assert negative.region_scored is False and negative.fusion_region_hit is None
    assert negative.outcome == "false_alarm"


def test_temporal_iou():
    assert temporal_iou((0.0, 10.0), (5.0, 15.0)) == pytest.approx(5 / 15)
    assert temporal_iou((0.0, 4.0), (6.0, 9.0)) == 0.0
    assert temporal_iou((2.0, 4.0), (0.0, 8.0)) == pytest.approx(2 / 8)


def test_evidence_time_and_latency_fields():
    expected = EXPECTED["eval_001"]  # window 6.03-28.0
    score = score_run(expected, _result("eval_001", "vehicle_stop", "z_east_pocket"))
    assert score.evidence_count == 2 and score.evidence_cameras == ["cam_a", "cam_b"]
    assert score.unsupported_claim is False
    assert score.best_cluster_iou == pytest.approx(temporal_iou((4.0, 12.0), (6.03, 28.0)))
    assert score.perception_latency_s == [2.0] and score.reasoning_latency_s == 1.0
    assert score.failed_calls == 0 and score.schema_errors == [] and score.schema_valid


def test_a_failed_run_counts_as_incorrect():
    score = score_run(EXPECTED["eval_001"], None, error="ToolCallError: boom")
    assert not score.completed and not score.class_ok and score.outcome == "run_failed"
    assert not score.schema_valid and score.fusion_region_hit is False
    assert score.full_hit is False


def test_scores_never_read_free_text():
    expected = EXPECTED["eval_001"]
    plain = score_run(expected, _result("eval_001", "vehicle_stop", "z_east_pocket"))
    wordy = score_run(
        expected,
        _result(
            "eval_001",
            "vehicle_stop",
            "z_east_pocket",
            reason="a completely different explanation",
            limitations=["something else entirely"],
        ),
    )
    assert plain == wordy


def test_wilson_interval_matches_textbook_values():
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert wilson(0, 0) is None


def _scores(answer_for: dict[str, str | None]) -> list:
    out = []
    for sid, expected in EXPECTED.items():
        event_type = answer_for.get(sid, UNKNOWN)
        if event_type is None:
            out.append(score_run(expected, None, error="ToolCallError: boom"))
        else:
            region = "z_east_pocket" if event_type not in (UNKNOWN, NO_EVENT) else UNKNOWN
            out.append(score_run(expected, _result(sid, event_type, region)))
    return out


def test_always_abstaining_ties_the_baseline_and_does_not_beat_it():
    summary = summarize(_scores({}), EXPECTED, meta={"profile": "test"})
    assert summary["decision"]["accuracy"]["k"] == 14
    assert summary["decision"]["balanced_accuracy"] == pytest.approx(2 / 3)
    assert summary["verdict"] == {"pipeline_ok": True, "beats_constant_baselines": False}


def test_perfect_answers_beat_the_baseline():
    answers = {
        sid: e["event_type"] if e["category"] != "negative" else NO_EVENT
        for sid, e in EXPECTED.items()
    }
    summary = summarize(_scores(answers), EXPECTED, meta={"profile": "test"})
    assert summary["decision"]["accuracy"]["rate"] == 1.0
    assert summary["verdict"]["beats_constant_baselines"] is True
    assert summary["failures"] == []


def test_a_failed_run_stays_in_every_denominator():
    summary = summarize(_scores({"eval_001": None}), EXPECTED, meta={"profile": "test"})
    assert summary["decision"]["accuracy"]["n"] == 22
    assert summary["decision"]["by_category"]["positive"]["n"] == 8
    assert summary["system"]["completion"]["k"] == 21
    assert summary["verdict"]["pipeline_ok"] is False
    assert [f["scenario_id"] for f in summary["failures"] if f["outcome"] == "run_failed"] == [
        "eval_001"
    ]


def test_false_alarms_are_counted_on_negatives():
    negatives = [s for s, e in EXPECTED.items() if e["category"] == "negative"]
    summary = summarize(_scores(dict.fromkeys(negatives, "vehicle_stop")), EXPECTED, meta={})
    assert summary["decision"]["false_alarm_rate"]["k"] == 7
    assert summary["decision"]["by_category"]["negative"]["k"] == 0

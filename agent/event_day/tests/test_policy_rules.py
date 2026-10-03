"""D00: the policy's pure rules (abstention, weakening, alert decision and text)."""

from __future__ import annotations

import pytest

from agent.event_day.policy import (
    ABSTAIN_BELOW,
    ALERT_MAX_CAMERAS,
    AlertRoute,
    abstain,
    alert_decision,
    apply_abstention_rules,
    cited_spans,
    compose_alert,
    redact,
    unsafe_alert_text,
    weakening_violations,
)
from apps.api.schemas import UNKNOWN, EvidenceBundle, Hypothesis
from tools.submit import NOT_DIRECTLY_VISIBLE

RUN_ID = "run_20261003T170000Z_abc123"
# Bot-token shaped, built at run time so no token-like literal sits in the repo.
TOKEN = ":".join(["123456789", "AAE" + "x7_" * 11])


def claim(**update) -> Hypothesis:
    base = {
        "event_type": "vehicle_stop",
        "region": "blind_zone_02",
        "confidence": 0.74,
        "evidence_ids": ["e1", "e2"],
        "reason": "Two cameras show traffic slowing toward the same core.",
        "alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.39}],
        "limitations": [],
    }
    return Hypothesis.model_validate(base | update)


def bundle(cameras=("cam_01", "cam_02", "cam_03"), evidence=None) -> EvidenceBundle:
    evidence = evidence or [
        {"id": "e2", "camera_id": "cam_02", "t_start": 1.2, "t_end": 2.0},
        {"id": "e1", "camera_id": "cam_01", "t_start": 1.0, "t_end": 1.6},
        {"id": "e3", "camera_id": "cam_01", "t_start": 0.4, "t_end": 1.1},
        {"id": "e4", "camera_id": "cam_03", "t_start": 2.1, "t_end": 3.0},
    ]
    return EvidenceBundle.model_validate(
        {
            "scenario_id": "scenario_001",
            "status": "ok",
            "cameras": [{"id": c} for c in cameras],
            "evidence": [
                {"cue_type": "vehicle_slowing_or_stopping", "description": "cue", "confidence": 0.8}
                | e
                for e in evidence
            ],
            "clusters": [],
            "region_candidates": [],
        }
    )


# -- abstention -------------------------------------------------------------------------


def test_a_claim_below_the_floor_becomes_an_abstention_that_keeps_it_as_an_alternative():
    out = apply_abstention_rules(claim(confidence=ABSTAIN_BELOW - 0.01))
    assert out.abstained and out.region == UNKNOWN
    assert out.confidence <= 0.2
    assert out.alternatives[0].event_type == "vehicle_stop"
    assert {a.event_type for a in out.alternatives} == {"vehicle_stop", "vehicle_turnaround"}
    assert any("abstention floor" in lim for lim in out.limitations)
    assert out.evidence_ids == ["e1", "e2"]


def test_a_claim_its_own_alternative_ties_becomes_an_abstention():
    out = apply_abstention_rules(
        claim(confidence=0.5, alternatives=[{"event_type": "vehicle_turn", "confidence": 0.5}])
    )
    assert out.abstained
    assert any("at or above its own claim" in lim for lim in out.limitations)
    assert [a.event_type for a in out.alternatives] == ["vehicle_stop", "vehicle_turn"]


def test_a_claim_with_no_alternatives_or_a_close_one_gets_a_limitation():
    alone = apply_abstention_rules(claim(alternatives=[]))
    assert not alone.abstained
    assert "The reasoner ranked no alternative explanation." in alone.limitations
    close = apply_abstention_rules(
        claim(alternatives=[{"event_type": "vehicle_turn", "confidence": 0.66}])
    )
    assert not close.abstained and close.confidence == 0.74
    assert any("within 0.10" in lim for lim in close.limitations)


def test_a_clear_claim_and_an_abstention_pass_through_unchanged():
    clear = claim()
    assert apply_abstention_rules(clear) is clear
    gave_up = abstain(None, "No camera produced observations.")
    assert apply_abstention_rules(gave_up) is gave_up
    assert gave_up.limitations == ["No camera produced observations.", NOT_DIRECTLY_VISIBLE]


# -- weakening --------------------------------------------------------------------------


def test_only_an_abstention_may_be_submitted_before_the_reasoner_answered():
    assert weakening_violations(claim(), None)
    assert weakening_violations(abstain(None, "x"), None) == []


@pytest.mark.parametrize(
    ("update", "problem"),
    [
        ({"event_type": "vehicle_turn"}, "event_type must stay"),
        ({"confidence": 0.9}, "confidence may not exceed"),
        ({"region": "blind_zone_01"}, "region must stay"),
        ({"evidence_ids": ["e9"]}, "evidence_ids must come from"),
        ({"alternatives": [{"event_type": "object_taken", "confidence": 0.1}]}, "alternatives"),
        ({"alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.5}]}, "exceed"),
    ],
)
def test_a_submitted_claim_may_not_replace_or_strengthen_the_reasoners(update, problem):
    problems = weakening_violations(claim(**update), claim())
    assert any(problem in p for p in problems), problems


def test_softening_is_allowed():
    raw = claim()
    assert (
        weakening_violations(claim(confidence=0.5, region=UNKNOWN, evidence_ids=["e1"]), raw) == []
    )
    assert weakening_violations(abstain(raw, "unsure"), raw) == []


# -- alert ------------------------------------------------------------------------------


def test_only_a_known_event_at_or_above_the_threshold_alerts():
    assert alert_decision(claim()) is None
    assert alert_decision(claim(confidence=ABSTAIN_BELOW)) is None
    assert "below the alert threshold" in alert_decision(claim(confidence=ABSTAIN_BELOW - 0.01))
    assert alert_decision(abstain(claim(), "unsure")) == "the run abstained"
    assert "not an abnormal event type" in alert_decision(claim(event_type="no_event"))


def test_the_alert_text_carries_the_claim_cameras_times_and_run_id():
    text = compose_alert(claim(evidence_ids=["e1", "e3", "e2"]), bundle(), RUN_ID)
    assert text.splitlines() == [
        "Urban Mirror alert",
        "event: vehicle_stop",
        "confidence: 0.74",
        "region: blind_zone_02 (coarse)",
        "cameras: cam_01 t=0.4-1.6s; cam_02 t=1.2-2.0s",
        f"run: {RUN_ID}",
        "Inferred from the visible cameras; the event itself was not directly observed.",
    ]
    assert not unsafe_alert_text(text)


def test_cited_spans_follow_bundle_camera_order():
    spans = cited_spans(claim(evidence_ids=["e4", "e2", "e1"]), bundle())
    assert [c for c, _, _ in spans] == ["cam_01", "cam_02", "cam_03"]


def test_the_alert_text_is_bounded_and_rejects_bad_ids():
    cams = [f"cam_{i:02d}" for i in range(ALERT_MAX_CAMERAS + 2)]
    evidence = [
        {"id": f"e{i}", "camera_id": c, "t_start": float(i), "t_end": i + 0.5}
        for i, c in enumerate(cams)
    ]
    text = compose_alert(
        claim(evidence_ids=[e["id"] for e in evidence]), bundle(cams, evidence), RUN_ID
    )
    assert "; +2 more" in text and "cam_07" not in text
    assert "region: unknown (coarse)" in compose_alert(claim(region="a b/c"), bundle(), RUN_ID)
    with pytest.raises(ValueError):
        compose_alert(claim(), bundle(), "https://example.invalid/run")


@pytest.mark.parametrize(
    "target", ["123456789", "-1001234567890", "@urban_alerts", "-100123:topic:42"]
)
def test_alert_routes_take_chat_ids_usernames_and_topics(target):
    assert AlertRoute(target).target == target


@pytest.mark.parametrize("target", [TOKEN, "https://t.me/x", "", "@ab", "chat 1"])
def test_alert_routes_refuse_tokens_urls_and_junk(target):
    with pytest.raises(ValueError):
        AlertRoute(target)
    with pytest.raises(ValueError):
        AlertRoute("123", channel="slack")


def test_redact_strips_urls_and_bot_tokens():
    raw = f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed\n bot{TOKEN} 401"
    out = redact(raw)
    assert TOKEN not in out and "api.telegram.org" not in out and "\n" not in out
    assert "<url>" in out and "<redacted>" in out
    assert unsafe_alert_text(raw)
    assert redact(None) is None

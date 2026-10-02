"""P10: the final submit gate and supporting-frame resolution."""

from __future__ import annotations

import json

import pytest

from apps.api.schemas import REPO_ROOT, EvidenceBundle, Hypothesis, MediaManifest
from tools.submit import (
    INSUFFICIENT_CONFIDENCE_CAP,
    NOT_DIRECTLY_VISIBLE,
    SINGLE_CAMERA_CONFIDENCE_CAP,
    submit_hypothesis,
)
from tools.supporting_frames import get_supporting_frames

EXAMPLES = REPO_ROOT / "contracts" / "examples"


def _ex(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def bundle() -> EvidenceBundle:
    return EvidenceBundle.model_validate(_ex("evidence_bundle.json"))


@pytest.fixture
def hyp() -> Hypothesis:
    return Hypothesis.model_validate(_ex("hypothesis.json"))


def test_valid_hypothesis_passes_through(bundle, hyp):
    out = submit_hypothesis(hyp, bundle)
    assert (out.event_type, out.region, out.confidence) == (
        hyp.event_type,
        hyp.region,
        hyp.confidence,
    )
    assert out.evidence_ids == hyp.evidence_ids
    assert NOT_DIRECTLY_VISIBLE in out.limitations
    assert out.limitations.count(NOT_DIRECTLY_VISIBLE) == 1


def test_unknown_evidence_dropped(bundle, hyp):
    out = submit_hypothesis(hyp.model_copy(update={"evidence_ids": ["obs_a_001", "ghost"]}), bundle)
    assert out.evidence_ids == ["obs_a_001"]
    assert any("Dropped 1" in lim for lim in out.limitations)


def test_unlisted_region_becomes_unknown(bundle, hyp):
    out = submit_hypothesis(hyp.model_copy(update={"region": "rooftop_9"}), bundle)
    assert out.region == "unknown"


def test_claim_without_evidence_becomes_abstention(bundle, hyp):
    out = submit_hypothesis(hyp.model_copy(update={"evidence_ids": ["ghost"]}), bundle)
    assert out.event_type == "unknown" and out.region == "unknown"
    assert out.confidence <= 0.2
    assert hyp.event_type in [a.event_type for a in out.alternatives]


def test_insufficient_bundle_caps_confidence(bundle, hyp):
    thin = bundle.model_copy(update={"status": "insufficient"})
    out = submit_hypothesis(hyp.model_copy(update={"confidence": 0.9}), thin)
    assert out.confidence == INSUFFICIENT_CONFIDENCE_CAP


def test_single_camera_caps_confidence(bundle, hyp):
    out = submit_hypothesis(
        hyp.model_copy(update={"evidence_ids": ["obs_a_001"], "confidence": 0.95}), bundle
    )
    assert out.confidence == SINGLE_CAMERA_CONFIDENCE_CAP


def test_alternatives_normalized(bundle, hyp):
    alts = [
        {"event_type": hyp.event_type, "confidence": 0.5},
        {"event_type": "stalled_vehicle", "confidence": 0.2},
        {"event_type": "stalled_vehicle", "confidence": 0.39},
        {"event_type": "debris", "confidence": 0.39},
    ]
    out = submit_hypothesis({**hyp.model_dump(), "alternatives": alts}, bundle)
    assert [(a.event_type, a.confidence) for a in out.alternatives] == [
        ("debris", 0.39),
        ("stalled_vehicle", 0.39),
    ]


def test_abstention_is_preserved(bundle):
    out = submit_hypothesis(Hypothesis.model_validate(_ex("hypothesis_abstain.json")), bundle)
    assert out.abstained and out.region == "unknown"


def test_submit_is_idempotent(bundle, hyp):
    once = submit_hypothesis(hyp.model_copy(update={"evidence_ids": ["obs_a_001", "x"]}), bundle)
    assert submit_hypothesis(once, bundle) == once


def test_supporting_frames_resolve_and_dedupe():
    manifest = MediaManifest.model_validate(_ex("media_manifest.json"))
    frames = get_supporting_frames("cam_01", [2, 0, 2], manifest)
    assert [f.index for f in frames] == [2, 0]
    assert frames[0].t == 2.0


def test_supporting_frames_reject_bad_input():
    manifest = MediaManifest.model_validate(_ex("media_manifest.json"))
    with pytest.raises(ValueError, match="invalid indices"):
        get_supporting_frames("cam_01", [0, 7], manifest)
    with pytest.raises(ValueError, match="belongs to camera"):
        get_supporting_frames("cam_gt", [0], manifest)

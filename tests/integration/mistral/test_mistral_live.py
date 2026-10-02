"""Live Ministral reasoning through Ollama (skips when unavailable), plus the lite real-footage
chain: Qwen observations on every model camera -> deterministic fusion -> Ministral -> gate.

Asserts contract validity, bundle-bounded ids/regions and telemetry; it does not score the
answer against ground truth (that is the evaluation harness's job). Latencies print with -s.
"""

from __future__ import annotations

import pytest

from apps.api.schemas import REPO_ROOT, EvidenceBundle, GroundTruthAccessError, validate_json
from inference.base import CallInfo, PerceptionOptions, ReasoningOptions
from inference.perception import OpenAICompatPerceptionAdapter
from inference.profiles import load_profile
from inference.reasoning import OpenAICompatReasoningAdapter, allowed_regions
from tests.integration.qwen.footage import (
    clip_for,
    extract_manifest,
    require_model,
    scenario_view,
)
from tools.inspect_camera import inspect_camera
from tools.reason_hypothesis import reason_hypothesis
from tools.submit import INSUFFICIENT_CONFIDENCE_CAP, submit_hypothesis
from tools.triangulate import build_evidence_bundle

pytestmark = pytest.mark.live_model

EXAMPLE_BUNDLE = REPO_ROOT / "contracts" / "examples" / "evidence_bundle.json"


@pytest.fixture(scope="module")
def example_bundle() -> EvidenceBundle:
    return EvidenceBundle.model_validate_json(EXAMPLE_BUNDLE.read_text(encoding="utf-8"))


def _insufficient(bundle: EvidenceBundle) -> EvidenceBundle:
    data = bundle.model_dump(mode="json")
    data.update(
        status="insufficient", evidence=data["evidence"][:1], clusters=[], region_candidates=[]
    )
    return EvidenceBundle.model_validate(data)


def _check(hyp, bundle: EvidenceBundle, info: CallInfo) -> None:
    validate_json("hypothesis", hyp.model_dump(mode="json"))
    assert set(hyp.evidence_ids) <= bundle.evidence_ids()
    assert hyp.region in allowed_regions(bundle)
    assert hyp.limitations
    confs = [a.confidence for a in hyp.alternatives]
    assert confs == sorted(confs, reverse=True)
    assert info.latency_s > 0 and info.model


@pytest.mark.parametrize("profile_name", ["lite-local", "full-local"])
@pytest.mark.parametrize("variant", ["ok", "insufficient"])
def test_reasoning_on_bundle(profile_name, variant, example_bundle):
    profile = load_profile(profile_name, env={})
    require_model(profile.reasoning)
    bundle = example_bundle if variant == "ok" else _insufficient(example_bundle)
    infos: list[CallInfo] = []
    adapter = OpenAICompatReasoningAdapter(profile)
    hyp = adapter.reason(bundle, ReasoningOptions(strict=True, telemetry=infos.append))
    (info,) = infos
    _check(hyp, bundle, info)
    assert info.ok and info.finish_reason == "stop"
    gated = submit_hypothesis(hyp, bundle)
    if variant == "insufficient":
        assert gated.region == "unknown"
        assert gated.abstained or gated.confidence <= INSUFFICIENT_CONFIDENCE_CAP
    print(
        f"\nLIVE reasoning {profile_name} {info.model} [{variant}]: {info.latency_s:.2f}s "
        f"attempts={info.attempts} repaired={info.repaired} usage={info.usage} -> "
        f"{hyp.event_type}@{hyp.region} conf={hyp.confidence} ids={hyp.evidence_ids} "
        f"alts={[(a.event_type, a.confidence) for a in hyp.alternatives]} "
        f"gated_conf={gated.confidence}"
    )


@pytest.mark.media
def test_lite_chain_on_real_footage(tmp_path):
    """scenario_001 end to end on lite-local; never touches the ground-truth clip."""
    view = scenario_view()
    if view is None or any(clip_for(view, c.id) is None for c in view.cameras):
        pytest.skip("scenario_001 prepared footage not present")
    profile = load_profile("lite-local", env={})
    require_model(profile.perception)
    require_model(profile.reasoning)

    with pytest.raises(GroundTruthAccessError):  # the withheld camera is refused up front
        view.camera("cam_gt")

    perceiver = OpenAICompatPerceptionAdapter(profile)
    batches, timings = [], []
    for cam in view.cameras:
        manifest = extract_manifest(clip_for(view, cam.id), cam.id, tmp_path / cam.id)
        infos: list[CallInfo] = []
        options = PerceptionOptions(
            scenario_id=view.id, scenario_view=view, strict=True, telemetry=infos.append
        )
        batch = inspect_camera(cam.id, manifest, options, adapter=perceiver)
        validate_json("observation_batch", batch.model_dump(mode="json"))
        batches.append(batch)
        timings.append(
            (cam.id, infos[0].latency_s, len(batch.observations), infos[0].dropped_items)
        )

    bundle = build_evidence_bundle(batches, view)
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    infos = []
    hyp = reason_hypothesis(
        bundle,
        ReasoningOptions(strict=True, telemetry=infos.append),
        adapter=OpenAICompatReasoningAdapter(profile),
    )
    _check(hyp, bundle, infos[0])
    gated = submit_hypothesis(hyp, bundle)
    validate_json("hypothesis", gated.model_dump(mode="json"))
    print(
        f"\nLIVE chain lite scenario_001 perception={[(c, round(s, 2), n, d) for c, s, n, d in timings]} "
        f"bundle status={bundle.status} evidence={len(bundle.evidence)} "
        f"clusters={len(bundle.clusters)} candidates={[c.id for c in bundle.region_candidates]} "
        f"reasoning={infos[0].latency_s:.2f}s -> {gated.event_type}@{gated.region} "
        f"conf={gated.confidence} alts={[(a.event_type, a.confidence) for a in gated.alternatives]}"
    )

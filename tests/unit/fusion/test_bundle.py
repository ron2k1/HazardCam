"""P08: build_evidence_bundle status, notes, schema validity and the no-LLM boundary."""

from __future__ import annotations

import ast
import json
import random

import pytest

from apps.api.schemas import (
    REPO_ROOT,
    GroundTruthAccessError,
    ObservationBatch,
    validate_json,
)
from tools.correlate import correlate_observations, fusion_notes
from tools.triangulate import assemble_evidence_bundle, build_evidence_bundle, triangulate_region


def _dump(bundle) -> str:
    return json.dumps(bundle.model_dump(mode="json"))


def test_fixture_observations_give_schema_valid_ok_bundle(scenario, fixture_batches):
    bundle = build_evidence_bundle(fixture_batches, scenario.model_view())
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    assert bundle.status == "ok"
    assert bundle.scenario_id == "scenario_001"
    assert [c.id for c in bundle.cameras] == ["cam_01", "cam_02", "cam_03"]
    assert [e.id for e in bundle.evidence] == ["obs_a_001", "obs_b_001", "obs_c_001"]
    assert {e.id: e.bearing_deg for e in bundle.evidence} == {
        "obs_a_001": 270.0,  # "west"
        "obs_b_001": 315.0,  # "northwest"
        "obs_c_001": None,  # null direction
    }
    (cluster,) = bundle.clusters
    assert (cluster.id, cluster.t_start, cluster.t_end) == ("clu_01", 8.0, 10.5)
    assert cluster.camera_ids == ["cam_01", "cam_02", "cam_03"]
    # 0.5 * 3/3 + 0.3 * mean(.84, .76, .79) + 0.2 / (1 + 1.1 / 1.5)
    assert cluster.score == round(0.5 + 0.3 * (2.39 / 3) + 0.2 / (1 + 1.1 / 1.5), 4)
    # The fixture's west / northwest rays only meet behind cam_01, so fusion falls back
    # to cam_01's ray; no zone lies on it.
    (region,) = bundle.region_candidates
    assert (region.id, region.method, region.center) == ("region_01", "single_ray", [-15.0, 4.0])
    assert any("No forward ray intersection" in n for n in bundle.notes)
    assert "cam_gt" not in _dump(bundle)


def test_geometrically_consistent_fixture_directions_snap_to_blind_zone_02(
    scenario, fixture_batches
):
    # Directions consistent with the illustrative headings (a proposed fixture edit):
    # cam_01 95+28 = 123 deg, cam_02 compass west, cam_03 20-16 = 4 deg.
    fixed = {"cam_01": "right", "cam_02": "west", "cam_03": "center_left"}
    batches = [
        ObservationBatch(
            camera_id=b.camera_id,
            observations=[
                o.model_copy(update={"direction": fixed[b.camera_id]}) for o in b.observations
            ],
        )
        for b in fixture_batches
    ]
    bundle = build_evidence_bundle(batches, scenario.model_view())
    (region,) = bundle.region_candidates
    assert (region.id, region.method) == ("blind_zone_02", "ray_intersection")
    assert region.camera_ids == ["cam_01", "cam_02", "cam_03"]


# --- insufficient paths ---------------------------------------------------------------


def test_one_camera_only_is_insufficient(scenario, fixture_batches):
    only_cam_01 = [b for b in fixture_batches if b.camera_id == "cam_01"]
    bundle = build_evidence_bundle(only_cam_01, scenario.model_view())
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    assert bundle.status == "insufficient"
    assert [e.id for e in bundle.evidence] == ["obs_a_001"]
    assert any(n.startswith("Insufficient:") for n in bundle.notes)
    assert any("cam_02, cam_03" in n for n in bundle.notes)


def test_empty_batches_are_insufficient(scenario):
    bundle = build_evidence_bundle([], scenario.model_view())
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    assert bundle.status == "insufficient"
    assert (bundle.evidence, bundle.clusters, bundle.region_candidates) == ([], [], [])
    assert "No observation batches were supplied." in bundle.notes
    assert "No region candidate: no evidence ray could be cast." in bundle.notes


def test_all_below_min_confidence_is_insufficient(scenario, fixture_batches):
    bundle = build_evidence_bundle(fixture_batches, scenario.model_view(), min_confidence=0.9)
    validate_json("evidence_bundle", bundle.model_dump(mode="json"))
    assert bundle.status == "insufficient"
    assert bundle.evidence == []
    assert (
        "Dropped 3 observation(s) below min_confidence=0.9: "
        "cam_01/obs_a_001, cam_02/obs_b_001, cam_03/obs_c_001." in bundle.notes
    )


def test_min_cameras_is_configurable(scenario, fixture_batches):
    two_cams = [b for b in fixture_batches if b.camera_id != "cam_03"]
    view = scenario.model_view()
    assert build_evidence_bundle(two_cams, view).status == "ok"
    assert build_evidence_bundle(two_cams, view, min_cameras=3).status == "insufficient"
    with pytest.raises(ValueError):
        build_evidence_bundle(two_cams, view, min_cameras=0)


def test_kwargs_reach_correlation(scenario, fixture_batches):
    # obs_b ends at 9.0 and obs_c starts at 9.1: a 0.05 s tolerance splits them.
    bundle = build_evidence_bundle(fixture_batches, scenario.model_view(), tolerance_s=0.05)
    assert [c.evidence_ids for c in bundle.clusters] == [["obs_a_001", "obs_b_001"], ["obs_c_001"]]
    assert bundle.status == "ok"


# --- ids, guard, determinism ----------------------------------------------------------


def test_id_collisions_are_namespaced_and_noted(scenario, make_batch, obs):
    batches = [
        make_batch("cam_01", obs("obs_001", 8.0, 8.5, "right")),
        make_batch("cam_02", obs("obs_001", 8.1, 8.6, "west")),
    ]
    bundle = build_evidence_bundle(batches, scenario.model_view())
    assert [e.id for e in bundle.evidence] == ["cam_01:obs_001", "cam_02:obs_001"]
    assert "Evidence id 'obs_001' from cam_01 renamed to 'cam_01:obs_001' (id collision)." in (
        bundle.notes
    )


def test_ground_truth_batch_or_raw_scenario_is_rejected(scenario, fixture_batches):
    gt = ObservationBatch(camera_id="cam_gt")
    with pytest.raises(GroundTruthAccessError):
        build_evidence_bundle([*fixture_batches, gt], scenario.model_view())
    with pytest.raises(GroundTruthAccessError):
        build_evidence_bundle(fixture_batches, scenario)


def test_bundle_json_does_not_depend_on_input_order(scenario, fixture_batches, make_batch, obs):
    batches = [
        *fixture_batches,
        make_batch("cam_01", obs("late_a", 14.0, 14.5, "center", 0.5)),
        make_batch("cam_03", obs("late_c", 13.6, 14.2, "center_right", 0.6)),
        make_batch("cam_02", obs("obs_a_001", 3.0, 3.2, "left", 0.4)),  # id collision
    ]
    view = scenario.model_view()
    baseline = _dump(build_evidence_bundle(batches, view))
    for seed in range(20):
        rng = random.Random(seed)
        shuffled = [
            ObservationBatch(
                camera_id=b.camera_id,
                observations=rng.sample(b.observations, len(b.observations)),
            )
            for b in rng.sample(batches, len(batches))
        ]
        assert _dump(build_evidence_bundle(shuffled, view)) == baseline


# --- assemble: the split tool-call path -----------------------------------------------


def _split_path(batches, view, *, tolerance_s=1.5, min_confidence=0.3, min_cameras=2):
    evidence, clusters = correlate_observations(
        batches, view, tolerance_s=tolerance_s, min_confidence=min_confidence
    )
    return assemble_evidence_bundle(
        view,
        evidence,
        clusters,
        triangulate_region(evidence, clusters, view),
        min_cameras=min_cameras,
        notes=fusion_notes(batches, view, min_confidence=min_confidence),
    )


def test_assembled_split_calls_equal_build_on_fixture(scenario, fixture_batches):
    view = scenario.model_view()
    assert _dump(_split_path(fixture_batches, view)) == _dump(
        build_evidence_bundle(fixture_batches, view)
    )


@pytest.mark.parametrize(
    "kw",
    [{}, {"tolerance_s": 0.05, "min_confidence": 0.5, "min_cameras": 3}],
    ids=["defaults", "custom_kwargs"],
)
def test_assembled_split_calls_equal_build_with_drops_and_collisions(
    scenario, fixture_batches, make_batch, obs, kw
):
    batches = [
        *fixture_batches,
        make_batch("cam_02", obs("obs_a_001", 8.4, 8.8, "west", 0.7)),  # id collision
        make_batch("cam_03", obs("faint", 9.0, 9.2, "center", 0.2)),  # always dropped
    ]
    view = scenario.model_view()
    split, built = _split_path(batches, view, **kw), build_evidence_bundle(batches, view, **kw)
    assert _dump(split) == _dump(built)
    assert any(n.startswith("Dropped") for n in built.notes)
    assert any("renamed" in n for n in built.notes)


def test_split_path_on_empty_batches_matches_build(scenario):
    view = scenario.model_view()
    assert fusion_notes([], view) == ["No observation batches were supplied."]
    assert _dump(_split_path([], view)) == _dump(build_evidence_bundle([], view))


def test_assemble_accepts_json_dicts(scenario, fixture_batches):
    view = scenario.model_view()
    evidence, clusters = correlate_observations(fixture_batches, view)
    candidates = triangulate_region(evidence, clusters, view)
    as_json = [[x.model_dump(mode="json") for x in xs] for xs in (evidence, clusters, candidates)]
    assert _dump(assemble_evidence_bundle(view, *as_json)) == _dump(
        assemble_evidence_bundle(view, evidence, clusters, candidates)
    )


def test_assemble_status_counts_cameras_from_evidence_not_cluster_claims(scenario, fixture_batches):
    view = scenario.model_view()
    evidence, _ = correlate_observations(fixture_batches, view)
    inflated = {
        "id": "clu_01",
        "t_start": 8.0,
        "t_end": 8.6,
        "evidence_ids": ["obs_a_001"],  # cam_01 only
        "camera_ids": ["cam_01", "cam_02", "cam_03"],
        "score": 0.9,
    }
    bundle = assemble_evidence_bundle(view, evidence, [inflated], [])
    assert bundle.status == "insufficient"
    assert assemble_evidence_bundle(view, evidence, [inflated], [], notes=None).notes == [
        (
            "1 evidence item(s) have no bearing (null/unknown direction "
            "or missing camera heading/fov)."
        ),
        (
            "Insufficient: no temporal cluster spans >= 2 cameras; "
            "cross-camera corroboration is missing."
        ),
        "No region candidate: no evidence ray could be cast.",
    ]


def test_assemble_rejects_ground_truth_citations_and_dangling_clusters(scenario, fixture_batches):
    view = scenario.model_view()
    evidence, clusters = correlate_observations(fixture_batches, view)
    gt_candidate = {
        "id": "region_01",
        "score": 0.5,
        "camera_ids": ["cam_gt"],
        "evidence_ids": [],
        "method": "zone_prior",
    }
    with pytest.raises(GroundTruthAccessError):
        assemble_evidence_bundle(view, evidence, clusters, [gt_candidate])
    gt_evidence = evidence[0].model_copy(update={"camera_id": "cam_gt"})
    with pytest.raises(GroundTruthAccessError):
        assemble_evidence_bundle(view, [gt_evidence, *evidence[1:]], [], [])
    with pytest.raises(GroundTruthAccessError):
        assemble_evidence_bundle(scenario, evidence, clusters, [])
    with pytest.raises(ValueError, match="obs_a_001"):
        assemble_evidence_bundle(view, evidence[1:], clusters, [])
    with pytest.raises(ValueError):
        assemble_evidence_bundle(view, evidence, clusters, [], min_cameras=0)


# --- no LLM dependency ----------------------------------------------------------------

ALLOWED_IMPORTS = {"__future__", "collections", "dataclasses", "math", "apps.api.schemas"}


@pytest.mark.parametrize("module", ["tools/correlate.py", "tools/triangulate.py"])
def test_fusion_modules_import_no_model_or_network_code(module):
    tree = ast.parse((REPO_ROOT / module).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= ALLOWED_IMPORTS | {"tools.correlate"}, imported

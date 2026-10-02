"""P08: deterministic temporal correlation (time offsets, clustering, ids, bearings)."""

from __future__ import annotations

import random

import pytest

from apps.api.schemas import (
    COMPASS_DIRECTIONS,
    IMAGE_DIRECTIONS,
    GroundTruthAccessError,
    ObservationBatch,
)
from tools.correlate import (
    COMPASS_BEARING,
    IMAGE_OFFSET_FRACTION,
    correlate,
    correlate_observations,
    direction_to_bearing,
)


def _two_cams(make_view, **cam_b):
    return make_view({"id": "cam_a"}, {"id": "cam_b", **cam_b})


# --- time alignment -------------------------------------------------------------------


def test_time_offset_aligns_camera_shifted_by_two_seconds(make_view, make_batch, obs):
    batches = [
        make_batch("cam_a", obs("a1", 10.0, 10.2)),
        make_batch("cam_b", obs("b1", 8.0, 8.2)),  # media clock runs 2 s behind
    ]
    evidence, clusters = correlate_observations(batches, _two_cams(make_view, time_offset_s=2.0))
    b1 = next(e for e in evidence if e.id == "b1")
    assert (b1.t_start, b1.t_end) == (10.0, 10.2)
    assert [(c.id, c.camera_ids) for c in clusters] == [("clu_01", ["cam_a", "cam_b"])]

    # Control: without the offset the same media times are 1.8 s apart (> 1.5 s).
    _, clusters = correlate_observations(batches, _two_cams(make_view))
    assert [c.camera_ids for c in clusters] == [["cam_b"], ["cam_a"]]


def test_negative_offset_is_applied_too(make_view, make_batch, obs):
    evidence, _ = correlate_observations(
        [make_batch("cam_b", obs("b1", 5.0, 6.0))], _two_cams(make_view, time_offset_s=-1.25)
    )
    assert (evidence[0].t_start, evidence[0].t_end) == (3.75, 4.75)


# --- clustering -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("second_start", "linked"),
    [(3.49, True), (3.5, True), (3.51, False)],
    ids=["just_inside", "exact_boundary_inclusive", "just_outside"],
)
def test_tolerance_boundary(make_view, make_batch, obs, second_start, linked):
    batches = [
        make_batch("cam_a", obs("a1", 1.0, 2.0)),
        make_batch("cam_b", obs("b1", second_start, second_start + 0.5)),
    ]
    _, clusters = correlate_observations(batches, _two_cams(make_view), tolerance_s=1.5)
    assert len(clusters) == (1 if linked else 2)


def test_zero_tolerance_links_only_touching_intervals(make_view, make_batch, obs):
    touching = [make_batch("cam_a", obs("a1", 1.0, 2.0)), make_batch("cam_b", obs("b1", 2.0, 3.0))]
    apart = [make_batch("cam_a", obs("a1", 1.0, 2.0)), make_batch("cam_b", obs("b1", 2.01, 3.0))]
    view = _two_cams(make_view)
    assert len(correlate_observations(touching, view, tolerance_s=0.0)[1]) == 1
    assert len(correlate_observations(apart, view, tolerance_s=0.0)[1]) == 2


def test_single_linkage_chains_and_ids_follow_t_start(make_view, make_batch, obs):
    view = make_view({"id": "cam_a"}, {"id": "cam_b"}, {"id": "cam_c"})
    batches = [
        make_batch("cam_c", obs("c_late", 30.0, 31.0), obs("c1", 4.0, 5.0)),
        make_batch("cam_b", obs("b1", 2.0, 3.0), obs("b_mid", 15.0, 15.5)),
        make_batch("cam_a", obs("a1", 0.0, 1.0)),
    ]
    _, clusters = correlate_observations(batches, view)
    # a1-b1 and b1-c1 are 1.0 s apart; a1-c1 are 3.0 s apart but chain through b1.
    assert [(c.id, c.evidence_ids, c.t_start, c.t_end) for c in clusters] == [
        ("clu_01", ["a1", "b1", "c1"], 0.0, 5.0),
        ("clu_02", ["b_mid"], 15.0, 15.5),
        ("clu_03", ["c_late"], 30.0, 31.0),
    ]


def test_every_evidence_item_is_in_exactly_one_cluster(make_view, make_batch, obs):
    view = make_view({"id": "cam_a"}, {"id": "cam_b"})
    batches = [
        make_batch("cam_a", *(obs(f"a{i}", 3.0 * i, 3.0 * i + 0.4) for i in range(6))),
        make_batch("cam_b", *(obs(f"b{i}", 2.5 * i, 2.5 * i + 0.4) for i in range(6))),
    ]
    evidence, clusters = correlate_observations(batches, view)
    members = [eid for c in clusters for eid in c.evidence_ids]
    assert sorted(members) == sorted(e.id for e in evidence)


def test_cluster_score_formula_by_hand(make_view, make_batch, obs):
    view = make_view({"id": "cam_a"}, {"id": "cam_b"}, {"id": "cam_c"})
    batches = [
        make_batch("cam_a", obs("a1", 0.0, 1.0, confidence=0.8)),
        make_batch("cam_b", obs("b1", 0.75, 1.0, confidence=0.6)),
    ]
    _, (cluster,) = correlate_observations(batches, view, tolerance_s=1.5)
    # 0.5 * 2/3 cameras + 0.3 * mean(0.8, 0.6) + 0.2 * 1 / (1 + 0.75 / 1.5)
    expected = 0.5 * 2 / 3 + 0.3 * 0.7 + 0.2 * (1 / 1.5)
    assert cluster.score == round(expected, 4) == 0.6767


# --- confidence filter + ids ----------------------------------------------------------


def test_min_confidence_drops_strictly_below_threshold(make_view, make_batch, obs):
    batch = make_batch(
        "cam_a",
        obs("drop", 1.0, 2.0, confidence=0.29),
        obs("keep_eq", 1.0, 2.0, confidence=0.3),
        obs("keep_hi", 1.0, 2.0, confidence=0.9),
    )
    result = correlate([batch], _two_cams(make_view), min_confidence=0.3)
    assert sorted(e.id for e in result.evidence) == ["keep_eq", "keep_hi"]
    assert result.dropped == [("cam_a", "drop")]


def test_evidence_ids_are_preserved_verbatim(make_view, make_batch, obs):
    ids = ["obs_a_001", "Qwen#7 frame-3", "x"]
    batch = make_batch("cam_a", *(obs(i, 1.0, 2.0) for i in ids))
    evidence, clusters = correlate_observations([batch], _two_cams(make_view))
    assert sorted(e.id for e in evidence) == sorted(ids)
    assert sorted(clusters[0].evidence_ids) == sorted(ids)


def test_cross_camera_id_collision_is_namespaced(make_view, make_batch, obs):
    batches = [
        make_batch("cam_a", obs("obs_1", 1.0, 2.0), obs("obs_2", 1.0, 2.0)),
        make_batch("cam_b", obs("obs_1", 1.0, 2.0)),
    ]
    result = correlate(batches, _two_cams(make_view))
    by_id = {e.id: e.camera_id for e in result.evidence}
    assert by_id == {"cam_a:obs_1": "cam_a", "cam_b:obs_1": "cam_b", "obs_2": "cam_a"}
    assert result.renamed == [
        ("cam_a", "obs_1", "cam_a:obs_1"),
        ("cam_b", "obs_1", "cam_b:obs_1"),
    ]


def test_same_camera_duplicate_ids_get_deterministic_suffixes(make_view, make_batch, obs):
    late, early = obs("dup", 5.0, 6.0), obs("dup", 1.0, 2.0)
    for order in ([late, early], [early, late]):
        result = correlate([make_batch("cam_a", *order)], _two_cams(make_view))
        assert {e.id: e.t_start for e in result.evidence} == {"dup": 1.0, "dup#2": 5.0}
        assert result.renamed == [("cam_a", "dup", "dup#2")]


# --- ground-truth guard + argument checks ---------------------------------------------


@pytest.mark.parametrize("camera_id", ["cam_gt", "cam_99"])
def test_ground_truth_or_unknown_camera_batch_is_rejected(scenario, make_batch, obs, camera_id):
    view = scenario.model_view()
    good = make_batch("cam_01", obs("a1", 1.0, 2.0))
    with pytest.raises(GroundTruthAccessError):
        correlate_observations([good, make_batch(camera_id, obs("g1", 1.0, 2.0))], view)
    with pytest.raises(GroundTruthAccessError):  # rejected even when it carries nothing
        correlate_observations([ObservationBatch(camera_id=camera_id)], view)


def test_raw_scenario_is_refused(scenario):
    with pytest.raises(GroundTruthAccessError):
        correlate_observations([], scenario)


@pytest.mark.parametrize("kw", [{"tolerance_s": -0.1}, {"min_confidence": 1.5}])
def test_invalid_arguments_raise(make_view, kw):
    with pytest.raises(ValueError):
        correlate_observations([], _two_cams(make_view), **kw)


# --- order invariance -----------------------------------------------------------------


def test_output_does_not_depend_on_input_order(make_view, make_batch, obs):
    view = make_view(
        {"id": "cam_a", "heading_deg": 90, "fov_deg": 60},
        {"id": "cam_b", "heading_deg": 180, "fov_deg": 70, "time_offset_s": 0.5},
        {"id": "cam_c"},
    )
    batches = [
        make_batch("cam_a", obs("x", 1.0, 2.0, "left"), obs("a2", 9.0, 9.5, "north", 0.9)),
        make_batch("cam_b", obs("x", 1.2, 2.2, "right", 0.6), obs("dup", 4.0, 4.1)),
        make_batch(
            "cam_c", obs("c1", 2.5, 3.0), obs("dup", 9.2, 9.4), obs("lo", 3.0, 3.1, None, 0.1)
        ),
        make_batch("cam_a", obs("dup", 4.0, 4.1, "center")),
    ]

    def dump(bs):
        evidence, clusters = correlate_observations(bs, view)
        return [e.model_dump() for e in evidence], [c.model_dump() for c in clusters]

    baseline = dump(batches)
    for seed in range(20):
        rng = random.Random(seed)
        shuffled = []
        for b in rng.sample(batches, len(batches)):
            observations = list(b.observations)
            rng.shuffle(observations)
            shuffled.append(ObservationBatch(camera_id=b.camera_id, observations=observations))
        assert dump(shuffled) == baseline


# --- bearings -------------------------------------------------------------------------


def test_bearing_tables_cover_the_contract_vocabulary():
    assert set(IMAGE_OFFSET_FRACTION) == set(IMAGE_DIRECTIONS)
    assert set(COMPASS_BEARING) == set(COMPASS_DIRECTIONS)


@pytest.mark.parametrize(
    ("direction", "bearing"),
    [
        ("left", 66.0),
        ("center_left", 78.0),
        ("center", 90.0),
        ("center_right", 102.0),
        ("right", 114.0),
        ("toward_camera", 90.0),
        ("away_from_camera", 90.0),
        ("Center-Left", 78.0),
        (" RIGHT ", 114.0),
    ],
)
def test_image_relative_bearing_is_heading_plus_fov_fraction(direction, bearing):
    assert direction_to_bearing(direction, heading_deg=90.0, fov_deg=60.0) == bearing


@pytest.mark.parametrize(
    ("direction", "bearing"),
    [
        ("north", 0.0),
        ("northeast", 45.0),
        ("east", 90.0),
        ("southeast", 135.0),
        ("south", 180.0),
        ("southwest", 225.0),
        ("west", 270.0),
        ("northwest", 315.0),
        ("North-East", 45.0),
    ],
)
def test_compass_bearing_ignores_camera_geometry(direction, bearing):
    assert direction_to_bearing(direction, heading_deg=None, fov_deg=None) == bearing
    assert direction_to_bearing(direction, heading_deg=200.0, fov_deg=40.0) == bearing


@pytest.mark.parametrize(
    ("heading", "direction", "bearing"), [(10.0, "left", 346.0), (350.0, "right", 14.0)]
)
def test_image_relative_bearing_wraps(heading, direction, bearing):
    assert direction_to_bearing(direction, heading_deg=heading, fov_deg=60.0) == bearing


@pytest.mark.parametrize(
    ("direction", "heading", "fov"),
    [
        (None, 90.0, 60.0),
        ("upward", 90.0, 60.0),
        ("left", None, 60.0),
        ("center", 90.0, None),
    ],
)
def test_bearing_is_none_without_direction_or_geometry(direction, heading, fov):
    assert direction_to_bearing(direction, heading_deg=heading, fov_deg=fov) is None


def test_evidence_bearing_uses_the_emitting_camera(make_view, make_batch, obs):
    view = make_view(
        {"id": "cam_a", "heading_deg": 0.0, "fov_deg": 50.0},
        {"id": "cam_b", "heading_deg": 270.0, "fov_deg": 80.0},
    )
    batches = [
        make_batch("cam_a", obs("a1", 1.0, 2.0, "right")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center_left")),
    ]
    evidence, _ = correlate_observations(batches, view)
    assert {e.id: e.bearing_deg for e in evidence} == {"a1": 20.0, "b1": 254.0}

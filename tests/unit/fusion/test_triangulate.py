"""P08: deterministic coarse triangulation (rays, crossings, zones, fallbacks)."""

from __future__ import annotations

import math
import random

import pytest

from apps.api.schemas import EvidenceCluster, EvidenceItem, GroundTruthAccessError
from tools.correlate import correlate_observations
from tools.triangulate import (
    MAX_REGION_CLUSTERS,
    NOMINAL_RADIUS_M,
    NOMINAL_RANGE_M,
    Ray,
    evidence_rays,
    intersect_rays,
    triangulate_region,
)

TAN_22_5 = math.sqrt(2) - 1  # tan(22.5 deg), the compass-word angular half-uncertainty


def _triangulate(view, *batches):
    evidence, clusters = correlate_observations(list(batches), view)
    return triangulate_region(evidence, clusters, view)


def _ray(origin, bearing, camera_id="cam", evidence_id="e"):
    return Ray(evidence_id, camera_id, origin, bearing, weight=1.0, sigma_deg=10.0)


@pytest.fixture
def x_view(make_view):
    """cam_a at (0, 0) looking 45 deg, cam_b at (10, 0) looking 315 deg: axes cross at (5, 5)."""

    def make(*, zones=(), heading=True):
        geo_a = {"heading_deg": 45.0, "fov_deg": 60.0} if heading else {}
        geo_b = {"heading_deg": 315.0, "fov_deg": 60.0} if heading else {}
        return make_view(
            {"id": "cam_a", "position": [0.0, 0.0], **geo_a},
            {"id": "cam_b", "position": [10.0, 0.0], **geo_b},
            zones=zones,
        )

    return make


# --- pairwise crossings ---------------------------------------------------------------


def test_intersect_rays_hand_computed():
    crossing = intersect_rays(_ray((0.0, 0.0), 45.0, "a"), _ray((10.0, 0.0), 315.0, "b"))
    assert crossing.point == pytest.approx((5.0, 5.0))
    assert (crossing.range_a, crossing.range_b) == pytest.approx((5 * math.sqrt(2),) * 2)
    assert crossing.sin_angle == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("bearing_a", "bearing_b"),
    [(0.0, 0.0), (0.0, 180.0), (0.0, 356.0)],
    ids=["parallel", "anti_parallel", "near_parallel_converging_4deg"],
)
def test_parallel_and_near_parallel_rays_do_not_cross(bearing_a, bearing_b):
    # The 4 deg pair converges ahead of both cameras (y = 10 / tan 4 = 143 m); it is
    # rejected only by the 5 deg crossing-angle floor.
    assert intersect_rays(_ray((0.0, 0.0), bearing_a), _ray((10.0, 0.0), bearing_b)) is None


def test_rays_sharing_an_origin_never_cross():
    # Why the same-camera pair filter is belt-and-braces: a shared origin gives range 0.
    assert intersect_rays(_ray((3.0, 4.0), 10.0), _ray((3.0, 4.0), 80.0)) is None


def test_six_degree_convergence_is_accepted():
    # cam_b leans 6 deg back toward cam_a's axis: they meet at x = 0, y = 10 / tan(6 deg).
    crossing = intersect_rays(_ray((0.0, 0.0), 0.0), _ray((10.0, 0.0), 354.0))
    assert crossing.point == pytest.approx((0.0, 10.0 / math.tan(math.radians(6.0))))


@pytest.mark.parametrize(
    ("bearing_a", "bearing_b"),
    [(45.0, 135.0), (225.0, 135.0)],
    ids=["behind_b", "behind_both"],
)
def test_crossing_behind_a_camera_is_ignored(bearing_a, bearing_b):
    # The infinite lines meet at (5, 5) / (5, -5), behind at least one camera.
    assert intersect_rays(_ray((0.0, 0.0), bearing_a), _ray((10.0, 0.0), bearing_b)) is None


# --- ray_intersection candidates ------------------------------------------------------


def test_two_cameras_triangulate_to_hand_computed_point(x_view, make_batch, obs):
    (cand,) = _triangulate(
        x_view(),
        make_batch("cam_a", obs("a1", 1.0, 2.0, "center", 0.8)),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center", 0.6)),
    )
    assert cand.method == "ray_intersection"
    assert (cand.id, cand.label) == ("region_01", None)
    assert cand.center == [5.0, 5.0]
    # angular term = hypot(2 x 5*sqrt(2) * tan(6 deg)) = 1.05 m < 3 m floor
    assert cand.radius_m == 3.0
    assert (cand.camera_ids, cand.evidence_ids) == (["cam_a", "cam_b"], ["a1", "b1"])
    # cluster = 0.5 * 2/2 + 0.3 * 0.7 + 0.2 * 1 = 0.91; region = 0.91 * (0.5 * 1 + 0.5 * 3/3)
    assert cand.score == 0.91


def test_compass_words_meet_at_the_same_point_with_wider_radius(x_view, make_batch, obs):
    (cand,) = _triangulate(
        x_view(heading=False),  # compass words need no heading or fov
        make_batch("cam_a", obs("a1", 1.0, 2.0, "northeast", 0.8)),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "northwest", 0.6)),
    )
    assert cand.center == [5.0, 5.0]
    # hypot(5*sqrt(2) * tan 22.5, 5*sqrt(2) * tan 22.5) / sin 90 = 10 * tan 22.5
    radius = 10 * TAN_22_5
    assert cand.radius_m == round(radius, 3) == 4.142
    assert cand.score == round(0.91 * (0.5 + 0.5 * 3.0 / radius), 4) == 0.7845


def test_image_relative_and_compass_bearings_agree(make_view, make_batch, obs):
    # heading 25 + 0.2 * 100 = 45 (center_right); heading 335 - 0.2 * 100 = 315 (center_left)
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0], "heading_deg": 25.0, "fov_deg": 100.0},
        {"id": "cam_b", "position": [10.0, 0.0], "heading_deg": 335.0, "fov_deg": 100.0},
    )
    image = _triangulate(
        view,
        make_batch("cam_a", obs("a1", 1.0, 2.0, "center_right")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center_left")),
    )
    compass = _triangulate(
        view,
        make_batch("cam_a", obs("a1", 1.0, 2.0, "northeast")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "northwest")),
    )
    assert image[0].center == compass[0].center == [5.0, 5.0]
    # image sigma = 0.1 * fov = 10 deg -> 10 * tan 10 = 1.76 m (floored); compass -> 4.142 m
    assert (image[0].radius_m, compass[0].radius_m) == (3.0, 4.142)


def test_three_camera_weighted_center_and_radius(make_view, make_batch, obs):
    # A (0,0) NE, B (10,0) NW, C (0,8) E. Crossings: AB (5,5), AC (8,8), BC (2,8).
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0]},
        {"id": "cam_b", "position": [10.0, 0.0]},
        {"id": "cam_c", "position": [0.0, 8.0]},
    )
    (cand,) = _triangulate(
        view,
        make_batch("cam_a", obs("a1", 1.0, 2.0, "northeast", 1.0)),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "northwest", 0.5)),
        make_batch("cam_c", obs("c1", 1.0, 2.0, "east", 1.0)),
    )
    # pair weights AB 0.5, AC 1.0, BC 0.5 -> center = (0.5*(5,5) + (8,8) + 0.5*(2,8)) / 2
    assert cand.center == [5.75, 7.25]
    spread = math.sqrt((0.5 * 5.625 + 1.0 * 5.625 + 0.5 * 14.625) / 2)
    r2 = math.sqrt(2)
    unc_ab = math.hypot(5 * r2, 5 * r2) * TAN_22_5 / 1.0
    unc_ac = math.hypot(8 * r2, 8.0) * TAN_22_5 / math.sin(math.radians(45))
    unc_bc = math.hypot(8 * r2, 2.0) * TAN_22_5 / math.sin(math.radians(135))
    angular = (0.5 * unc_ab + 1.0 * unc_ac + 0.5 * unc_bc) / 2
    radius = math.hypot(spread, angular)
    assert cand.radius_m == round(radius, 3) == 7.335
    # cluster = 0.5 * 3/3 + 0.3 * (2.5/3) + 0.2 * 1 = 0.95
    assert cand.score == round(0.95 * (0.5 * 1.0 + 0.5 * 3.0 / radius), 4)
    assert cand.camera_ids == ["cam_a", "cam_b", "cam_c"]


def test_agreement_counts_only_cameras_in_a_valid_crossing(make_view, make_batch, obs):
    # cam_c at (20, 0) looks south: both of its crossings are behind it.
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0]},
        {"id": "cam_b", "position": [10.0, 0.0]},
        {"id": "cam_c", "position": [20.0, 0.0]},
    )
    (cand,) = _triangulate(
        view,
        make_batch("cam_a", obs("a1", 1.0, 2.0, "northeast")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "northwest")),
        make_batch("cam_c", obs("c1", 1.0, 2.0, "south")),
    )
    assert (cand.camera_ids, cand.evidence_ids) == (["cam_a", "cam_b"], ["a1", "b1"])
    # cluster = 0.5 + 0.3 * 0.8 + 0.2 = 0.94; agreement 2/3; radius 10 tan 22.5
    assert cand.score == round(0.94 * (0.5 * 2 / 3 + 0.5 * 3.0 / (10 * TAN_22_5)), 4)


def test_rays_from_the_same_camera_never_cross_each_other(make_view, make_batch, obs):
    view = make_view({"id": "cam_a", "position": [0.0, 0.0]}, {"id": "cam_b"})
    (cand,) = _triangulate(
        view, make_batch("cam_a", obs("a1", 1.0, 2.0, "north"), obs("a2", 1.0, 2.0, "east"))
    )
    assert cand.method == "single_ray"


# --- zone snapping --------------------------------------------------------------------


def test_center_inside_zone_takes_zone_id_and_label_keeps_geometry(x_view, make_batch, obs):
    zones = [
        {"id": "core", "label": "intersection core", "center": [5.5, 4.5], "radius_m": 2.0},
        {"id": "far", "center": [30.0, 30.0], "radius_m": 5.0},
    ]
    (cand,) = _triangulate(
        x_view(zones=zones),
        make_batch("cam_a", obs("a1", 1.0, 2.0, "center")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center")),
    )
    assert (cand.id, cand.label, cand.method) == ("core", "intersection core", "ray_intersection")
    assert (cand.center, cand.radius_m) == ([5.0, 5.0], 3.0)


def test_overlapping_zones_pick_smallest_normalized_distance(x_view, make_batch, obs):
    zones = [
        {"id": "wide", "center": [8.0, 5.0], "radius_m": 10.0},  # 3 / 10 = 0.3
        {"id": "tight", "center": [5.0, 5.2], "radius_m": 2.0},  # 0.2 / 2 = 0.1
    ]
    (cand,) = _triangulate(
        x_view(zones=zones),
        make_batch("cam_a", obs("a1", 1.0, 2.0, "center")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center")),
    )
    assert cand.id == "tight"


def test_center_outside_zones_gets_region_id_that_skips_zone_ids(x_view, make_batch, obs):
    zones = [{"id": "region_01", "center": [40.0, 40.0], "radius_m": 3.0}]
    (cand,) = _triangulate(
        x_view(zones=zones),
        make_batch("cam_a", obs("a1", 1.0, 2.0, "center")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center")),
    )
    assert (cand.id, cand.label) == ("region_02", None)


# --- single-ray fallbacks -------------------------------------------------------------


@pytest.fixture
def east_view(make_view):
    """One positioned camera at the origin looking east (90 deg, fov 60)."""

    def make(zones=()):
        return make_view(
            {"id": "cam_a", "position": [0.0, 0.0], "heading_deg": 90.0, "fov_deg": 60.0},
            zones=zones,
        )

    return make


def test_single_ray_without_zone_is_nominal_point(east_view, make_batch, obs):
    (cand,) = _triangulate(east_view(), make_batch("cam_a", obs("a1", 1.0, 2.0, "center")))
    assert cand.method == "single_ray"
    assert cand.id == "region_01"
    assert (cand.center, cand.radius_m) == ([NOMINAL_RANGE_M, 0.0], NOMINAL_RADIUS_M)
    # cluster = 0.5 * 1/1 + 0.3 * 0.8 + 0.2 * 1 = 0.94; single ray keeps a quarter
    assert cand.score == round(0.94 * 0.25, 4)
    assert (cand.camera_ids, cand.evidence_ids) == (["cam_a"], ["a1"])


def test_single_ray_through_zone_becomes_zone_prior(east_view, make_batch, obs):
    zones = [
        {"id": "lot", "label": "east lot", "center": [20.0, 2.0], "radius_m": 3.0},  # miss 2
        {"id": "pier", "center": [40.0, 1.0], "radius_m": 3.0},  # miss 1 -> closest
        {"id": "behind", "center": [-20.0, 0.0], "radius_m": 3.0},  # behind the camera
    ]
    (cand,) = _triangulate(east_view(zones), make_batch("cam_a", obs("a1", 1.0, 2.0, "center")))
    assert (cand.id, cand.method) == ("pier", "zone_prior")
    assert (cand.center, cand.radius_m) == ([40.0, 1.0], 3.0)
    assert cand.score == round(0.94 * 0.5, 4)


@pytest.mark.parametrize(
    "center",
    [[-20.0, 0.0], [-0.5, 0.0], [20.0, 10.0]],
    ids=["far_behind", "camera_inside_zone_centered_behind", "ahead_but_10m_off_the_ray"],
)
def test_zone_behind_or_off_the_ray_is_not_a_prior(east_view, make_batch, obs, center):
    zones = [{"id": "behind", "center": center, "radius_m": 3.0}]
    (cand,) = _triangulate(east_view(zones), make_batch("cam_a", obs("a1", 1.0, 2.0, "center")))
    assert cand.method == "single_ray"


def test_zone_ahead_beats_a_closer_zone_centered_behind(east_view, make_batch, obs):
    zones = [
        {"id": "behind", "center": [-2.0, 0.0], "radius_m": 3.0},  # contains the camera
        {"id": "ahead", "center": [20.0, 2.5], "radius_m": 3.0},  # miss 2.5
    ]
    (cand,) = _triangulate(east_view(zones), make_batch("cam_a", obs("a1", 1.0, 2.0, "center")))
    assert (cand.id, cand.method) == ("ahead", "zone_prior")


def test_non_crossing_rays_fall_back_to_the_strongest_ray(make_view, make_batch, obs):
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0], "heading_deg": 0.0, "fov_deg": 60.0},
        {"id": "cam_b", "position": [10.0, 0.0], "heading_deg": 0.0, "fov_deg": 60.0},
    )
    (cand,) = _triangulate(
        view,
        make_batch("cam_a", obs("a1", 1.0, 2.0, "toward_camera", 0.9)),  # weight 0.45
        make_batch("cam_b", obs("b1", 1.0, 2.0, "center", 0.6)),  # weight 0.6
    )
    assert (cand.method, cand.evidence_ids, cand.center) == ("single_ray", ["b1"], [10.0, 15.0])


# --- empty / guard paths --------------------------------------------------------------


def test_no_geometry_gives_no_candidates(make_view, make_batch, obs):
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0], "heading_deg": 0.0, "fov_deg": 60.0},
        {"id": "cam_b", "heading_deg": 0.0, "fov_deg": 60.0},  # no position
    )
    assert _triangulate(view, make_batch("cam_a", obs("a1", 1.0, 2.0, None))) == []
    assert _triangulate(view, make_batch("cam_b", obs("b1", 1.0, 2.0, "north"))) == []
    assert triangulate_region([], [], view) == []


def test_evidence_from_ground_truth_camera_is_rejected(scenario):
    item = EvidenceItem(
        id="g1",
        camera_id="cam_gt",
        t_start=1.0,
        t_end=2.0,
        cue_type="x",
        description="x",
        bearing_deg=0.0,
        confidence=0.9,
    )
    cluster = EvidenceCluster(
        id="clu_01", t_start=1.0, t_end=2.0, evidence_ids=["g1"], camera_ids=["cam_gt"], score=1
    )
    with pytest.raises(GroundTruthAccessError):
        triangulate_region([item], [cluster], scenario.model_view())
    with pytest.raises(GroundTruthAccessError):
        triangulate_region([], [], scenario)


def test_cluster_citing_unknown_evidence_is_rejected(x_view):
    cluster = EvidenceCluster(
        id="clu_01", t_start=1.0, t_end=2.0, evidence_ids=["ghost"], camera_ids=["cam_a"], score=1
    )
    with pytest.raises(ValueError, match="ghost"):
        triangulate_region([], [cluster], x_view())


# --- multiple clusters ----------------------------------------------------------------


def _crossing_pair(make_batch, obs, t, conf_a=0.8, conf_b=0.8):
    return [
        make_batch("cam_a", obs(f"a@{t}", t, t + 0.5, "center", conf_a)),
        make_batch("cam_b", obs(f"b@{t}", t, t + 0.5, "center", conf_b)),
    ]


def test_candidates_are_score_ordered_capped_and_zone_deduplicated(x_view, make_batch, obs):
    zones = [{"id": "core", "center": [5.0, 5.0], "radius_m": 2.0}]
    batches = [
        *_crossing_pair(make_batch, obs, 0.0, 0.5, 0.5),
        *_crossing_pair(make_batch, obs, 10.0, 0.9, 0.9),
        *_crossing_pair(make_batch, obs, 20.0, 0.7, 0.7),
        *_crossing_pair(make_batch, obs, 30.0, 0.4, 0.4),
    ]
    view = x_view(zones=zones)
    evidence, clusters = correlate_observations(batches, view)
    assert len(clusters) == 4 > MAX_REGION_CLUSTERS
    (cand,) = triangulate_region(evidence, clusters, view)
    # all four clusters snap to "core"; only the best (t = 10, confidence 0.9) survives
    assert (cand.id, cand.evidence_ids) == ("core", ["a@10.0", "b@10.0"])

    no_zone = x_view()
    candidates = triangulate_region(evidence, clusters, no_zone)
    assert [c.id for c in candidates] == ["region_01", "region_02", "region_03"]
    assert [c.evidence_ids[0] for c in candidates] == ["a@10.0", "a@20.0", "a@0.0"]
    assert [c.score for c in candidates] == sorted((c.score for c in candidates), reverse=True)


def test_candidates_do_not_depend_on_input_order(make_view, make_batch, obs):
    view = make_view(
        {"id": "cam_a", "position": [0.0, 0.0]},
        {"id": "cam_b", "position": [10.0, 0.0]},
        {"id": "cam_c", "position": [0.0, 8.0]},
        zones=[{"id": "z", "center": [6.0, 6.0], "radius_m": 1.5}],
    )
    batches = [
        make_batch("cam_a", obs("a1", 1.0, 2.0, "northeast", 1.0), obs("a2", 20.0, 21.0, "east")),
        make_batch("cam_b", obs("b1", 1.0, 2.0, "northwest", 0.5)),
        make_batch("cam_c", obs("c1", 1.0, 2.0, "east", 1.0), obs("c2", 20.5, 21.0, "southeast")),
    ]
    evidence, clusters = correlate_observations(batches, view)
    baseline = [c.model_dump() for c in triangulate_region(evidence, clusters, view)]
    for seed in range(20):
        rng = random.Random(seed)
        ev, cl = rng.sample(evidence, len(evidence)), rng.sample(clusters, len(clusters))
        assert [c.model_dump() for c in triangulate_region(ev, cl, view)] == baseline


def test_ray_payload_matches_sse_shape(x_view, make_batch, obs):
    evidence, _ = correlate_observations(
        [make_batch("cam_a", obs("a1", 1.0, 2.0, "center"))], x_view()
    )
    (ray,) = evidence_rays(evidence, x_view())
    assert ray.to_dict() == {
        "camera_id": "cam_a",
        "evidence_id": "a1",
        "origin": [0.0, 0.0],
        "bearing_deg": 45.0,
    }

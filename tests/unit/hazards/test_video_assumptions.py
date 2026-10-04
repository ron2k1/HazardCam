"""One test per testable upstream video assumption, at its exact threshold.

``test_upstream_video_parity.py`` runs the original code and the port on the same clips;
these tests pin each rule's boundary on tiny synthetic arrays so a drift is named.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from hazards import scan
from tests.unit.hazards._helpers import make_synthetic_video, scene_background, write_video

# --- [1/6] decode, timing, background ----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ((1920, 1080), (768, 432)),
        ((1280, 721), (768, 433)),  # height rounded, not truncated
        ((1000, 333), (768, 256)),
        ((640, 360), (640, 360)),  # never upscaled
        ((768, 500), (768, 500)),
    ],
)
def test_analysis_size_is_width_768_never_upscaled(source, expected):
    assert scan.analysis_size(*source) == expected
    assert scan.CFG["analysis_width"] == 768


def test_decode_reads_every_frame_with_inter_area(synthetic_video: Path):
    video = scan.decode_video(synthetic_video)
    cap = cv2.VideoCapture(str(synthetic_video))
    raw = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        raw.append(frame)
    cap.release()
    assert video.n == len(raw) == 40
    assert (video.source_w, video.source_h, video.aw, video.ah) == (960, 540, 768, 432)
    assert video.fps == 10.0 and video.reported_n == 40
    for got, frame in zip(video.frames, raw, strict=True):
        np.testing.assert_array_equal(
            got, cv2.resize(frame, (768, 432), interpolation=cv2.INTER_AREA)
        )


def test_decode_aborts_above_max_frames(synthetic_video: Path):
    assert scan.CFG["max_frames"] == 15000
    with pytest.raises(ValueError, match="memory/frame limit; process it in chunks"):
        scan.decode_video(synthetic_video, {**scan.CFG, "max_frames": 39})
    assert scan.decode_video(synthetic_video, {**scan.CFG, "max_frames": 40}).n == 40


def test_decode_needs_two_frames(tmp_path: Path):
    one = make_synthetic_video(tmp_path / "one.mp4", frames=1)
    with pytest.raises(ValueError, match="At least two decodable frames are required"):
        scan.decode_video(one)
    assert scan.decode_video(make_synthetic_video(tmp_path / "two.mp4", frames=2)).n == 2


def test_decode_rejects_unreadable_files(tmp_path: Path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video" * 100)
    with pytest.raises(RuntimeError, match="Cannot decode junk.mp4"):
        scan.decode_video(junk)


def test_timing_is_frame_index_over_source_fps():
    np.testing.assert_array_equal(scan.frame_times(5, 2.5), [0.0, 0.4, 0.8, 1.2, 1.6])
    video = scan.DecodedVideo([np.zeros((2, 2, 3), np.uint8)] * 315, 24.99, 4, 4, 315, 4, 4)
    assert video.duration == 315 / 24.99
    assert video.times[-1] == 314 / 24.99


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (40, [0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39]),
        (10, list(range(10))),
        (2, [0, 1]),
        (21, list(range(21))),
    ],
)
def test_background_uses_21_evenly_spaced_frames(n, expected):
    assert scan.background_indices(n).tolist() == expected
    assert scan.CFG["background_samples"] == 21


def test_background_indices_for_a_long_clip():
    indices = scan.background_indices(315)
    assert len(indices) == 21 and indices[0] == 0 and indices[-1] == 314
    assert indices.tolist() == np.unique(np.linspace(0, 314, 21).astype(int)).tolist()


def test_background_is_the_per_pixel_median():
    frames = [np.full((4, 4, 3), v, np.uint8) for v in (10, 200, 30)]
    frames[1][0, 0] = 0
    bg = scan.temporal_background(frames, np.array([0, 1, 2]))
    assert bg.dtype == np.uint8
    assert bg[1, 1, 0] == 30 and bg[0, 0, 0] == 10
    # an even sample count averages the middle pair, then truncates to uint8
    assert scan.temporal_background(frames[:2], np.array([0, 1]))[1, 1, 0] == 105


# --- [2/6] motion -------------------------------------------------------------------------


def _uniform(value: int, size: int = 32) -> np.ndarray:
    return np.full((size, size, 3), value, np.uint8)


@pytest.mark.parametrize(("delta", "moving"), [(18, False), (19, True)])
def test_motion_threshold_is_strictly_above_18(delta, moving):
    assert scan.CFG["difference_threshold"] == 18
    frames = [_uniform(100), _uniform(100 + delta)]
    motion = scan.compute_motion(frames, frames[0])
    assert bool(motion.masks[1].all()) is moving
    assert not motion.masks[1].any() or moving
    assert motion.step_fraction[1] == (1.0 if moving else 0.0)


def test_background_difference_counts_as_motion():
    """Adjacent OR background change: a parked change keeps registering."""
    frames = [_uniform(100), _uniform(140), _uniform(140)]
    motion = scan.compute_motion(frames, frames[0])
    assert motion.step_fraction[2] == 0.0  # no adjacent change
    assert motion.masks[2].all()  # still moving vs the background
    assert not motion.masks[0].any()  # frame 0 is never marked
    np.testing.assert_array_equal(motion.heatmap, motion.masks[1:].mean(axis=0))
    np.testing.assert_array_equal(motion.fraction, motion.masks.mean(axis=(1, 2)))


def test_motion_open_3x3_removes_specks():
    base = _uniform(0, 31)
    speck = base.copy()
    speck[15, 15] = 255
    motion = scan.compute_motion([base, speck], base)
    blurred = cv2.GaussianBlur(cv2.cvtColor(speck, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    assert (blurred > 18).sum() == 5  # a plus shape survives the threshold...
    assert not motion.masks[1].any()  # ...and the 3x3 opening removes it


@pytest.mark.parametrize(("gap", "bridged"), [(8, True), (9, False)])
def test_motion_close_7x7_bridges_small_gaps(gap, bridged):
    """The blur spreads each blob 1 px over the threshold; close 7x7 fills <= 6 px."""
    base = _uniform(0, 48)
    two = base.copy()
    two[14:34, 4:16] = 255
    two[14:34, 16 + gap : 28 + gap] = 255
    masks = scan.compute_motion([base, two], base).masks[1]
    assert bool(masks[24, 16 : 16 + gap].all()) is bridged


# --- quality warnings -----------------------------------------------------------------------


def test_frame_count_warning():
    assert scan.frame_count_warning(315, 314) == (
        "Container reports 315 frames; decoder read 314. Check for truncation."
    )
    assert scan.frame_count_warning(40, 40) is None
    assert scan.frame_count_warning(0, 40) is None  # unknown container count: no warning


@pytest.mark.parametrize(("peak", "warn"), [(0.35, False), (0.3501, True)])
def test_global_change_warning_above_35_percent(peak, warn):
    result = scan.global_change_warning(np.array([0.0, 0.1, peak]))
    assert result == (scan.WARN_GLOBAL_CHANGE if warn else None)


def _texture(size: int = 128) -> np.ndarray:
    rng = np.random.default_rng(3)
    return cv2.GaussianBlur(rng.integers(0, 255, (size, size)).astype(np.uint8), (5, 5), 0)


@pytest.mark.parametrize(("shift", "warn"), [(0, False), (2, False), (5, True), (8, True)])
def test_translation_warning_above_3_px_median(shift, warn):
    tex = _texture()
    gray = np.stack([tex] + [np.roll(tex, shift, axis=1)] * 4)
    result = scan.translation_warning(gray, np.arange(5))
    assert result == (scan.WARN_TRANSLATION if warn else None)


def test_translation_ignores_weak_phase_responses():
    rng = np.random.default_rng(9)
    gray = rng.integers(0, 255, (5, 64, 64)).astype(np.uint8)  # unrelated frames
    assert scan.translation_warning(gray, np.arange(5)) is None


def test_fallback_and_floor_warnings_wording():
    stage = _static_stage(scene_background(960, 540), detected=None)
    assert stage.warnings == [scan.WARN_STATIC_FALLBACK, scan.WARN_NO_FLOOR]
    assert stage.segmentation_method == "edge-contour fallback"


# --- [3/6] movement zones -------------------------------------------------------------------


def _motion_with(masks: np.ndarray) -> scan.Motion:
    n, ah, aw = masks.shape
    zeros = np.zeros((n, ah, aw), np.uint8)
    return scan.Motion(
        zeros,
        zeros[0],
        masks,
        np.zeros(n),
        masks[1:].mean(axis=0),
        masks.mean(axis=(1, 2)),
    )


@pytest.mark.parametrize(("active_frames", "zone"), [(3, False), (4, True)])
def test_movement_heatmap_threshold_is_above_0_012(active_frames, zone):
    masks = np.zeros((251, 100, 200), np.uint8)
    masks[1 : 1 + active_frames, 40:60, 80:120] = 1
    props = scan.movement_proposals(_motion_with(masks), scan.frame_times(251, 25), 200, 100)
    assert bool(props) is zone


@pytest.mark.parametrize(("height", "kept"), [(3, False), (4, True)])
def test_movement_minimum_area_is_0_08_percent(height, kept):
    masks = np.zeros((3, 100, 200), np.uint8)  # 0.0008 * 200 * 100 = 16 px
    masks[1:, 40 : 40 + height, 80:84] = 1
    props = scan.movement_proposals(_motion_with(masks), scan.frame_times(3, 10), 200, 100)
    assert bool(props) is kept


@pytest.mark.parametrize(("rows", "kept"), [(60, True), (61, False)])
def test_movement_box_at_most_60_percent_of_the_frame(rows, kept):
    masks = np.zeros((3, 100, 200), np.uint8)
    masks[1:, 20 : 20 + rows, :] = 1
    props = scan.movement_proposals(_motion_with(masks), scan.frame_times(3, 10), 200, 100)
    assert bool(props) is kept


@pytest.mark.parametrize(("weak_px", "start"), [(15, 1.0), (16, 0.5)])
def test_movement_peak_and_active_window(weak_px, start):
    n = 30
    masks = np.zeros((n, 100, 200), np.uint8)
    masks[10:20, 40:50, 80:90] = 1  # full trace (1.0) in frames 10..19
    weak = np.zeros(100, np.uint8)
    weak[:weak_px] = 1
    masks[5:7, 40:50, 80:90] = weak.reshape(10, 10)  # trace weak_px / 100 in frames 5, 6
    props = scan.movement_proposals(_motion_with(masks), scan.frame_times(n, 10), 200, 100)
    assert len(props) == 1
    zone = props[0]
    assert zone["peak_frame"] == 10  # first argmax
    assert zone["active_start_s"] == start  # 0.15 of the peak is not active, 0.16 is
    assert zone["active_end_s"] == 1.9
    assert zone["bbox_analysis"] == [80, 40, 90, 50]
    assert zone["proposal_score"] == pytest.approx(masks[1:, 40:50, 80:90].mean(axis=0).sum())


# --- floor, paint, static candidates -------------------------------------------------------


def _floor_inputs(aw: int = 100, ah: int = 50, saturation: int = 20):
    hsv = np.zeros((ah, aw, 3), np.uint8)
    hsv[:, :, 1] = saturation
    return hsv, np.zeros((ah, aw), np.uint8)


def test_floor_mask_needs_more_than_4_percent():
    hsv, edges = _floor_inputs()
    exact = np.zeros((50, 100), np.uint8)
    exact[46:50, 0:50] = 1  # 200 px = exactly 4% of 5000
    assert not scan.floor_from_masks([exact], hsv, edges, 100, 50).any()
    bigger = exact.copy()
    bigger[45, 0] = 1
    assert scan.floor_from_masks([bigger], hsv, edges, 100, 50).sum() == 201


def test_floor_mask_must_touch_the_bottom_rows():
    hsv, edges = _floor_inputs()
    high = np.zeros((50, 100), np.uint8)
    high[10:40, :] = 1
    assert not scan.floor_from_masks([high], hsv, edges, 100, 50).any()
    low = np.zeros((50, 100), np.uint8)
    low[10:48, :] = 1  # rows 47..49 hold 100 of 300 px > 2%
    assert scan.floor_from_masks([low], hsv, edges, 100, 50).any()


@pytest.mark.parametrize(("saturation", "floor"), [(69, True), (70, False)])
def test_floor_median_saturation_below_70(saturation, floor):
    hsv, edges = _floor_inputs(saturation=saturation)
    mask = np.zeros((50, 100), np.uint8)
    mask[30:, :] = 1
    assert bool(scan.floor_from_masks([mask], hsv, edges, 100, 50).any()) is floor


@pytest.mark.parametrize(("edge_px", "floor"), [(119, True), (120, False)])
def test_floor_edge_density_below_6_percent(edge_px, floor):
    hsv, edges = _floor_inputs()
    mask = np.zeros((50, 100), np.uint8)
    mask[30:, :] = 1  # 2000 px; 6% = 120 px
    flat = np.zeros(2000, np.uint8)
    flat[:edge_px] = 255
    edges[30:, :] = flat.reshape(20, 100)
    assert bool(scan.floor_from_masks([mask], hsv, edges, 100, 50).any()) is floor


@pytest.mark.parametrize(
    ("hsv", "paint"),
    [
        ((18, 65, 55), True),
        ((90, 255, 255), True),
        ((17, 65, 55), False),
        ((91, 200, 200), False),
        ((18, 64, 55), False),
        ((18, 65, 54), False),
        ((30, 200, 200), True),
    ],
)
def test_paint_hsv_range(hsv, paint):
    pixel = np.array([[hsv]], np.uint8)
    assert bool(scan.paint_mask(pixel)[0, 0]) is paint


def _static_stage(background: np.ndarray, detected) -> scan.StaticStage:
    aw, ah = scan.analysis_size(background.shape[1], background.shape[0])
    small = cv2.resize(background, (aw, ah), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    return scan.propose_static(
        small, gray, np.zeros((ah, aw)), scan.frame_times(10, 10), aw, ah, detected
    )


def _region(aw: int, ah: int, box: tuple[int, int, int, int]) -> np.ndarray:
    mask = np.zeros((ah, aw), np.uint8)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = 1
    return mask


def _static(masks, aw=200, ah=100, floor=None, paint=None, heatmap=None):
    floor = np.zeros((ah, aw), np.uint8) if floor is None else floor
    paint = np.zeros((ah, aw), np.uint8) if paint is None else paint
    heatmap = np.zeros((ah, aw)) if heatmap is None else heatmap
    return scan.static_proposals(
        masks,
        heatmap,
        floor,
        bool(floor.any()),
        paint,
        cv2.dilate(paint, np.ones((21, 21), np.uint8)) > 0,
        scan.frame_times(10, 10),
        aw,
        ah,
    )


@pytest.mark.parametrize(
    ("box", "kept"),
    [
        ((10, 10, 30, 30), True),  # 400 px = 2%
        ((10, 10, 21, 30), False),  # 11 px wide < 12
        ((10, 10, 22, 30), True),  # 12 px wide
        ((10, 10, 30, 21), False),  # 11 px tall < 12
        ((0, 0, 200, 15), True),  # 3000 px = 15%: kept
        ((0, 0, 200, 16), False),  # 3200 px = 16% > 15%
    ],
)
def test_static_candidate_size_rules(box, kept):
    props, indices = _static([_region(200, 100, box)])
    assert bool(props) is kept
    assert indices == ([0] if kept else [])


@pytest.mark.parametrize(("pixels", "kept"), [(40, True), (39, False)])
def test_static_candidate_minimum_area_is_0_2_percent(pixels, kept):
    shape = np.zeros((100, 200), np.uint8)  # 0.002 * 200 * 100 = 40 px
    shape[10, 10:30] = 1  # an L: 20 px row...
    shape[11 : 11 + pixels - 20, 10] = 1  # ...plus a column, box >= 12 x 12
    assert (shape > 0).sum() == pixels
    assert bool(_static([shape])[0]) is kept


@pytest.mark.parametrize(("right", "kept"), [(70, True), (110, False)])
def test_static_box_area_at_most_20_percent(right, kept):
    outline = np.zeros((100, 200), np.uint8)
    cv2.rectangle(outline, (10, 10), (right, 60), 1, 2)  # thin: small area, large box
    props, _ = _static([outline])
    assert bool(props) is kept


def test_static_excludes_floor_and_paint_regions():
    candidate = _region(200, 100, (50, 50, 80, 80))
    floor = np.zeros((100, 200), np.uint8)
    floor[50:66, 50:80] = 1  # 16 of 30 rows: > 50% floor -> dropped
    assert _static([candidate], floor=floor)[0] == []
    floor_half = np.zeros((100, 200), np.uint8)
    floor_half[50:65, 50:80] = 1  # exactly 50% -> kept
    assert len(_static([candidate], floor=floor_half)[0]) == 1
    paint = np.zeros((100, 200), np.uint8)
    paint[50:69, 50:80] = 255  # 19 of 30 rows = 63% paint -> dropped
    assert _static([candidate], paint=paint)[0] == []
    paint[66:69] = 0  # 16 of 30 rows = 53% -> kept
    assert len(_static([candidate], paint=paint)[0]) == 1


def test_static_score_formula():
    candidate = _region(200, 100, (50, 50, 80, 80))
    heatmap = np.full((100, 200), 0.2)
    floor = np.zeros((100, 200), np.uint8)
    floor[80:, :] = 1  # below the candidate: some ring contact, none inside
    paint = np.zeros((100, 200), np.uint8)
    paint[60:62, 85:95] = 255  # outside the box; its 21x21 dilation reaches cols 75..79
    (prop,), _ = _static([candidate], floor=floor, paint=paint, heatmap=heatmap)
    ring = (cv2.dilate(candidate, np.ones((15, 15), np.uint8)) > 0) & (candidate == 0)
    near = cv2.dilate(paint, np.ones((21, 21), np.uint8)) > 0
    contact = float(floor[ring].mean())
    proximity = float(near[candidate > 0].mean())
    expected = np.sqrt(900 / 20000) * 0.8 * (0.05 + contact) ** 2 * (1 + 2 * proximity)
    assert prop["proposal_score"] == pytest.approx(expected)
    assert prop["floor_contact"] == contact and prop["paint_proximity"] == proximity
    assert 0 < contact < 1 and proximity == 110 / 900
    assert prop["stability"] == pytest.approx(0.8)
    assert prop["peak_frame"] == 0 and prop["active_start_s"] == 0.0
    assert prop["active_end_s"] == 0.9


def test_static_floor_contact_is_half_without_a_floor():
    (prop,), _ = _static([_region(200, 100, (50, 50, 80, 80))])
    assert prop["floor_contact"] == 0.5


# --- zone selection -------------------------------------------------------------------------


@pytest.mark.parametrize(("bottom", "kept"), [(5, True), (6, False), (7, False)])
def test_select_distinct_drops_iou_at_or_above_0_6(bottom, kept):
    first = {"bbox_analysis": [0, 0, 10, 10], "proposal_score": 1.0}
    second = {"bbox_analysis": [0, 0, 10, bottom], "proposal_score": 0.5}
    selected = scan.select_distinct([second, first], 5)
    assert selected[0] is first
    assert (second in selected) is kept


def test_select_zones_caps_ids_and_orders_movement_first():
    def props(kind: str, count: int, y: int) -> list[dict]:
        return [
            {
                "kind": kind,
                "bbox_analysis": [i * 60, y, i * 60 + 50, y + 50],
                "proposal_score": float(i),
                "peak_frame": 0,
            }
            for i in range(count)
        ]

    zones = scan.select_zones(
        props(scan.KIND_MOVEMENT, 7, 0), props(scan.KIND_STATIC, 7, 200), 768, 432, 1920, 1080
    )
    assert [z["zone_id"] for z in zones] == [f"Z{i:02d}" for i in range(1, 11)]
    assert [z["kind"] for z in zones] == [scan.KIND_MOVEMENT] * 5 + [scan.KIND_STATIC] * 5
    assert [z["proposal_score"] for z in zones[:5]] == [6.0, 5.0, 4.0, 3.0, 2.0]
    top = zones[0]
    assert top["bbox_analysis"] == [360, 0, 410, 50]
    assert top["bbox_normalized"] == [round(360 / 768, 5), 0.0, round(410 / 768, 5), 0.11574]
    assert top["bbox_source"] == [900, 0, 1025, 125]


# --- [4/6] evidence -------------------------------------------------------------------------


def _zone(zone_id: str, peak: int, box: list[int]) -> dict:
    return {"zone_id": zone_id, "peak_frame": peak, "bbox_source": box}


def test_evidence_plan_order_and_count():
    n, fps = 40, 10.0
    fraction = np.zeros(n)
    fraction[[20, 21, 30, 5]] = [0.9, 0.8, 0.7, 0.6]  # 21 is < 0.7 s from 20
    zones = [
        _zone("Z01", 10, [100, 100, 140, 120]),
        _zone("Z02", 25, [0, 0, 800, 400]),
        _zone("Z03", 20, [900, 500, 960, 540]),
    ]
    plan = scan.evidence_plan(n, fps, fraction, zones, 960, 540)
    assert scan.peak_indices(fraction, fps) == [20, 30, 5]
    assert sorted(scan.overview_indices(n)) == [0, 5, 11, 16, 22, 27, 33, 39]
    full = [r.frame_index for r in plan if r.kind == scan.EVIDENCE_FULL]
    assert full == [0, 5, 11, 16, 20, 22, 27, 30, 33, 39]
    crops = [(r.zone_id, r.frame_index, r.box) for r in plan if r.kind == scan.EVIDENCE_ZONE]
    assert crops == [
        ("Z01", 10, (50, 50, 190, 170)),  # pad max(50, 25% of 40) = 50; opposite end N-1
        ("Z01", 39, (50, 50, 190, 170)),
        ("Z02", 0, (0, 0, 960, 540)),  # pad 200, clipped; peak >= N//2 -> frame 0
        ("Z02", 25, (0, 0, 960, 540)),
        ("Z03", 0, (850, 450, 960, 540)),  # peak == N//2 -> frame 0
        ("Z03", 20, (850, 450, 960, 540)),
    ]
    tiles = [(r.frame_index, r.box) for r in plan if r.kind == scan.EVIDENCE_TILE]
    assert tiles == [
        (20, (0, 0, 528, 297)),
        (20, (432, 0, 960, 297)),
        (20, (0, 243, 528, 540)),
        (20, (432, 243, 960, 540)),
    ]
    assert [r.kind for r in plan] == (
        [scan.EVIDENCE_FULL] * 10 + [scan.EVIDENCE_ZONE] * 6 + [scan.EVIDENCE_TILE] * 4
    )
    assert all(r.max_width == 768 for r in plan if r.kind != scan.EVIDENCE_FULL)
    assert all(r.max_width is None for r in plan if r.kind == scan.EVIDENCE_FULL)


def test_evidence_plan_short_clip_dedupes_frames():
    plan = scan.evidence_plan(
        2, 10.0, np.array([0.0, 1.0]), [_zone("Z01", 0, [0, 0, 10, 10])], 64, 48
    )
    assert [r.frame_index for r in plan if r.kind == scan.EVIDENCE_FULL] == [0, 1]
    assert [r.frame_index for r in plan if r.kind == scan.EVIDENCE_ZONE] == [0, 1]


@pytest.fixture(scope="module")
def big_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("big") / "source.mp4"
    return make_synthetic_video(path, width=1920, height=1080, frames=4, fps=5)


def test_write_evidence_canvas_label_and_sizes(big_video: Path, tmp_path: Path):
    plan = [
        scan.EvidenceRequest(0, scan.EVIDENCE_FULL),
        scan.EvidenceRequest(3, scan.EVIDENCE_ZONE, "Z02", (100, 100, 400, 300), 768),
        scan.EvidenceRequest(1, scan.EVIDENCE_TILE, None, (0, 0, 1056, 594), 768),
    ]
    times = scan.frame_times(4, 5)
    evidence = scan.write_evidence(big_video, tmp_path, plan, times, 1920, 1080)
    assert [e["evidence_id"] for e in evidence] == ["E001", "E002", "E003"]
    assert evidence[0]["bbox_source"] == [0, 0, 1920, 1080]
    assert evidence[1]["bbox_source"] == [100, 100, 400, 300]
    assert evidence[1]["timestamp_s"] == 0.6 and evidence[1]["zone_id"] == "Z02"
    sizes = [cv2.imread(str(tmp_path / e["path"])).shape[:2] for e in evidence]
    assert sizes == [(576 + 36, 1024), (200 + 36, 520), (432 + 36, 768)]
    header = cv2.imread(str(tmp_path / evidence[0]["path"]))[:36]
    assert header.max() > 200  # burned-in white label
    assert np.median(header) == pytest.approx(22, abs=2)
    for e in evidence:
        assert e["sha256"] == scan.sha256_file(tmp_path / e["path"])
        assert e["path"] == f"evidence/{e['evidence_id']}.jpg"


def test_write_evidence_uses_jpeg_quality_92(big_video: Path, tmp_path: Path):
    plan = [scan.EvidenceRequest(0, scan.EVIDENCE_ZONE, "Z01", (0, 0, 300, 200), 768)]
    (item,) = scan.write_evidence(big_video, tmp_path, plan, scan.frame_times(4, 5), 1920, 1080)
    cap = cv2.VideoCapture(str(big_video))
    _, frame = cap.read()
    cap.release()
    canvas = np.full((236, 520, 3), 22, np.uint8)
    canvas[36:, :300] = frame[0:200, 0:300]
    cv2.putText(
        canvas,
        "E001 | t=0.000s | zone crop | Z01",
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
    )
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok and (tmp_path / item["path"]).read_bytes() == encoded.tobytes()


def test_write_evidence_budget_is_40_images(big_video: Path, tmp_path: Path):
    assert scan.CFG["max_total_images"] == 40
    plan = [scan.EvidenceRequest(0, scan.EVIDENCE_FULL)] * 4
    with pytest.raises(ValueError, match="Evidence image budget exceeded"):
        scan.write_evidence(
            big_video,
            tmp_path,
            plan,
            scan.frame_times(4, 5),
            1920,
            1080,
            {**scan.CFG, "max_total_images": 3},
        )


def test_small_source_is_never_upscaled_in_evidence(tmp_path: Path):
    video = write_video(tmp_path / "small.mp4", [scene_background(400, 300)] * 3, 5)
    (item,) = scan.write_evidence(
        video,
        tmp_path,
        [scan.EvidenceRequest(0, scan.EVIDENCE_FULL)],
        scan.frame_times(3, 5),
        400,
        300,
    )
    assert cv2.imread(str(tmp_path / item["path"])).shape[:2] == (336, 520)


def test_annotate_banner_and_tags():
    frame = np.zeros((100, 200, 3), np.uint8)
    zones = [
        {"zone_id": "Z01", "kind": scan.KIND_MOVEMENT, "bbox_analysis": [10, 20, 60, 70]},
        {"zone_id": "Z02", "kind": scan.KIND_STATIC, "bbox_analysis": [100, 20, 150, 70]},
    ]
    plain = scan.annotate(frame, zones)
    banner = scan.annotate(frame, zones, 1.234)
    assert plain.shape == (100, 200, 3) and banner.shape == (128, 200, 3)
    assert tuple(plain[70, 35]) == (220, 145, 30)  # movement box colour (BGR)
    assert tuple(plain[70, 125]) == (30, 175, 245)  # static box colour (BGR)
    np.testing.assert_array_equal(banner[28:], plain)
    assert banner[:28].max() == 255 and banner[0, -1].tolist() == [22, 22, 22]

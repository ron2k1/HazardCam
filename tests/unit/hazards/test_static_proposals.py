"""Port change: local YOLO boxes are ADDED to the edge-contour candidates, never replace them.

The floor mask is built from the edge-contour masks only (YOLO gives object boxes, not
floor regions), and when the detector is down the original fallback and warning apply.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from hazards import scan
from hazards.detector.client import Detection, DetectorClient, DetectorHealth, DetectResult
from tests.unit.hazards._helpers import StubDetector, scene_background, unreachable_transport

AW, AH = 768, 432


def _inputs(background: np.ndarray | None = None):
    bg = background if background is not None else scene_background(960, 540)
    small = cv2.resize(bg, (AW, AH), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    return small, gray, np.zeros((AH, AW)), scan.frame_times(40, 10)


def _floor_scene() -> np.ndarray:
    background = scene_background(960, 540)
    cv2.rectangle(background, (6, 276), (953, 535), (200, 200, 200), 3)
    return background


def _detected(*boxes: tuple[float, float, float, float], width=AW, height=AH) -> DetectResult:
    return DetectResult(
        width=width,
        height=height,
        objects=[
            Detection(model="yolo11s", label=f"obj{i}", conf=0.5 + i / 100, box=box)
            for i, box in enumerate(boxes)
        ],
    )


def test_yolo_boxes_are_added_before_the_unchanged_edge_candidates():
    small, gray, heat, times = _inputs()
    base = scan.propose_static(small, gray, heat, times, AW, AH, None)
    boxes = [(420.0, 250.0, 470.0, 300.0), (100.0, 300.0, 160.0, 380.0)]
    union = scan.propose_static(small, gray, heat, times, AW, AH, _detected(*boxes))
    assert union.yolo_mask_count == 2
    assert union.edge_mask_count == base.edge_mask_count
    assert union.proposals[2:] == base.proposals
    assert union.sources[:2] == ["yolo11s: obj0 (0.50)", "yolo11s: obj1 (0.51)"]
    assert union.sources[2:] == [scan.EDGE_SOURCE] * len(base.proposals)
    assert [p["bbox_analysis"] for p in union.proposals[:2]] == [
        [420, 250, 470, 300],
        [100, 300, 160, 380],
    ]
    assert union.segmentation_method == (
        "local YOLO11s boxes on the temporal background + edge contours"
    )
    assert scan.WARN_STATIC_FALLBACK not in union.warnings
    assert scan.WARN_STATIC_FALLBACK in base.warnings


@pytest.mark.parametrize("background", [None, "floor"])
def test_floor_mask_ignores_yolo_boxes(background):
    small, gray, heat, times = _inputs(_floor_scene() if background else None)
    base = scan.propose_static(small, gray, heat, times, AW, AH, None)
    # a box covering the whole bottom half would pass every floor rule if it were a region
    huge = _detected((0.0, AH * 0.5, float(AW), float(AH)), (10.0, 10.0, 200.0, 200.0))
    union = scan.propose_static(small, gray, heat, times, AW, AH, huge)
    np.testing.assert_array_equal(union.floor_mask, base.floor_mask)
    assert union.floor_available is base.floor_available is bool(background)
    assert (scan.WARN_NO_FLOOR in union.warnings) is (not background)


def test_a_floor_box_from_yolo_would_have_been_a_floor():
    """Guards the previous test: the same box as a REGION mask does pass the floor rules."""
    small, gray, _, _ = _inputs()
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    edge_map = cv2.Canny(gray, 60, 150)
    box = np.zeros((AH, AW), np.uint8)
    box[AH // 2 :, :] = 1
    assert scan.floor_from_masks([box], hsv, edge_map, AW, AH).any()


def test_yolo_boxes_follow_the_upstream_static_rules():
    small, gray, heat, times = _inputs()
    stage = scan.propose_static(
        small,
        gray,
        heat,
        times,
        AW,
        AH,
        _detected(
            (300.0, 100.0, 305.0, 105.0),  # 25 px: below the 0.2% minimum area
            (0.0, 0.0, 700.0, 400.0),  # > 15% of the frame
            (420.0, 250.0, 470.0, 300.0),  # kept
        ),
    )
    assert stage.yolo_mask_count == 3
    assert [s for s in stage.sources if s != scan.EDGE_SOURCE] == ["yolo11s: obj2 (0.52)"]


def test_yolo_box_on_a_floor_is_excluded_like_any_region():
    small, gray, heat, times = _inputs(_floor_scene())
    base = scan.propose_static(small, gray, heat, times, AW, AH, None)
    ys, xs = np.where(base.floor_mask > 0)
    x, y = int(np.median(xs)), int(np.median(ys))
    stage = scan.propose_static(
        small, gray, heat, times, AW, AH, _detected((x - 30.0, y - 30.0, x + 30.0, y + 30.0))
    )
    assert base.floor_mask[y - 30 : y + 30, x - 30 : x + 30].mean() > 0.5
    assert stage.yolo_mask_count == 1
    assert stage.proposals == base.proposals  # dropped by the > 50% floor rule


def test_box_masks_scale_from_the_posted_image_to_analysis_pixels():
    result = _detected((10.2, 20.7, 30.1, 40.0), (5.0, 5.0, 5.0, 9.0), width=384, height=216)
    masks, sources = scan.box_masks(result, AW, AH)
    assert len(masks) == 1 and sources == ["yolo11s: obj0 (0.50)"]
    ys, xs = np.where(masks[0] > 0)
    # floor(min * 2) .. ceil(max * 2), clipped to the frame; degenerate boxes are dropped
    assert (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) == (20, 61, 41, 80)


def test_box_masks_clip_and_drop_bad_boxes():
    result = _detected(
        (-50.0, -10.0, 9000.0, 20.0), (float("nan"), 0.0, 10.0, 10.0), (30.0, 30.0, 10.0, 10.0)
    )
    masks, _ = scan.box_masks(result, AW, AH)
    assert len(masks) == 2
    ys, xs = np.where(masks[0] > 0)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (0, AW - 1, 0, 19)
    ys, xs = np.where(masks[1] > 0)  # reversed corners are normalised
    assert (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) == (10, 30, 10, 30)


# --- detector call on the temporal background ---------------------------------------------


def test_detector_down_keeps_the_upstream_fallback():
    detector = DetectorClient(transport=unreachable_transport())
    small, *_ = _inputs()
    result, run = scan.detect_on_background(small, detector)
    assert result is None
    assert run.status == "unreachable" and "unreachable" in (run.error or "")
    assert run.models_sha256 is None and run.objects == []


def test_detector_disabled_and_models_missing():
    small, *_ = _inputs()
    assert scan.detect_on_background(small, None)[1].status == "disabled"
    detector = DetectorClient(transport=unreachable_transport())
    health = DetectorHealth(base_url=detector.base_url, ok=True, models={"other": "x"})
    result, run = scan.detect_on_background(small, detector, health=health)
    assert result is None and run.status == "models_missing"


def test_detector_runs_on_the_background_png():
    stub = StubDetector(
        objects=[{"model": "yolo11s", "label": "box", "conf": 0.7, "box": [1, 2, 30, 40]}]
    ).start()
    try:
        small, *_ = _inputs()
        result, run = scan.detect_on_background(small, DetectorClient(stub.url), conf=0.25)
    finally:
        stub.stop()
    assert result is not None and run.status == "ok"
    (request,) = stub.requests
    assert request["path"] == "/detect" and request["content_type"] == "image/png"
    assert request["query"] == {"models": ["yolo11s"], "conf": ["0.25"]}
    assert request["image_shape"] == (AH, AW, 3)
    decoded = cv2.imdecode(np.frombuffer(request["body"], np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(decoded, small)  # lossless: the exact background
    assert run.used_models == ["yolo11s"]
    assert run.models_sha256 == {"yolo11s": stub.models["yolo11s"]}
    assert run.image_size == [AW, AH] and run.as_dict()["boxes"] == 1


def test_detector_with_no_boxes_keeps_the_yolo_method_over_edge_contours():
    """The fallback is for a detector that did not answer, not one that found nothing."""
    stub = StubDetector(objects=[]).start()
    try:
        small, gray, heat, times = _inputs()
        result, run = scan.detect_on_background(small, DetectorClient(stub.url))
    finally:
        stub.stop()
    assert run.status == "no_boxes" and run.as_dict()["boxes"] == 0
    stage = scan.propose_static(small, gray, heat, times, AW, AH, result)
    assert stage.segmentation_method == (
        "local YOLO11s boxes on the temporal background + edge contours"
    )
    assert scan.WARN_STATIC_FALLBACK not in stage.warnings
    assert stage.yolo_mask_count == 0
    # the candidates are exactly the original edge-contour ones
    base = scan.propose_static(small, gray, heat, times, AW, AH, None)
    assert stage.proposals == base.proposals and stage.sources == base.sources
    assert stage.segmentation_method != base.segmentation_method == "edge-contour fallback"
    assert scan.WARN_STATIC_FALLBACK in base.warnings


def test_world_model_is_only_used_when_served():
    stub = StubDetector(objects=[]).start()
    try:
        small, *_ = _inputs()
        _, run = scan.detect_on_background(
            small, DetectorClient(stub.url), models=("yolo11s", "yolov8s-worldv2")
        )
    finally:
        stub.stop()
    assert stub.requests[0]["query"]["models"] == ["yolo11s,yolov8s-worldv2"]
    assert run.used_models == ["yolo11s", "yolov8s-worldv2"]
    assert scan.segmentation_method_for(run.used_models) == (
        "local YOLO11s + YOLOv8s-World boxes on the temporal background + edge contours"
    )

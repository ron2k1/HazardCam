"""Computer-vision stages of the hazard review, ported from ``astra_video_hazard.py``.

Every video assumption of the teammate script (astra-1.1) is kept: fixed camera, every
frame decoded and resized to 768 px wide with INTER_AREA, timing = frame_index / fps, a
21-sample per-pixel median background, the same motion masks, quality warnings, movement
zones, floor/paint rules, static-candidate score, selection, evidence sampling and labels.

The ONLY change to proposals: static region masks came from FastSAM on the temporal
background (falling back to edge contours). Here the local YOLO detector runs on the same
background image, each box becomes a rectangular mask, and the candidate set is those boxes
UNION the original edge-contour masks. The floor mask always comes from the edge-contour
masks (the original fallback path); YOLO gives boxes, not floor regions.

numpy + cv2 only (httpx via the detector client); ffmpeg makes the browser H.264 video.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from tools.media.binaries import ffmpeg_bin, ffprobe_bin, passthrough_args, run_tool

from .detector.client import (
    DEFAULT_CONF,
    DEFAULT_MODELS,
    DetectorClient,
    DetectorError,
    DetectorHealth,
    DetectResult,
)

log = logging.getLogger(__name__)

UPSTREAM_PATH = "third_party/astra_safety_hazard/astra_video_hazard.py"
UPSTREAM_SHA256 = "ae92565bdd6daff3332f2fe4d3c6669533b7eee16d32ce6fef23e42986eba132"
UPSTREAM_VERSION = "astra-1.1"
PIPELINE_VERSION = "astra-1.1-gb10"

# Verbatim from the upstream script (``CFG = dict(...)``); tests compare it via ``ast``.
CFG: dict[str, Any] = {
    "analysis_width": 768,
    "max_frames": 15000,
    "background_samples": 21,
    "difference_threshold": 18,
    "motion_frequency_threshold": 0.012,
    "minimum_zone_fraction": 0.0008,
    "max_motion_zones": 5,
    "max_static_zones": 5,
    "overview_frames": 8,
    "peak_frames": 3,
    "crop_width": 768,
    "image_width": 1024,
    "max_total_images": 40,
    "max_payload_mb": 30,
    "temperature": 0,
    "seed": 42,
    "num_ctx": 65536,
    "num_predict": 6000,
    "request_timeout_s": 900,
    "pipeline_version": "astra-1.1",
}

# Literals that are inline in the upstream code, named here so tests can pin them.
SELECT_IOU = 0.6
PEAK_MIN_GAP_S = 0.7
ACTIVE_PEAK_FRACTION = 0.15
GLOBAL_CHANGE_FRACTION = 0.35
SHIFT_RESPONSE_MIN = 0.2
SHIFT_MEDIAN_MAX_PX = 3
PAINT_HSV_LOW = (18, 65, 55)
PAINT_HSV_HIGH = (90, 255, 255)
EVIDENCE_JPEG_QUALITY = 92
EVIDENCE_HEADER_PX = 36
EVIDENCE_MIN_CANVAS_W = 520
BANNER_PX = 28

KIND_MOVEMENT = "movement"
KIND_STATIC = "possible_obstruction"
EVIDENCE_FULL = "full scene"
EVIDENCE_ZONE = "zone crop"
EVIDENCE_TILE = "scene tile"
COLORS = {KIND_MOVEMENT: (220, 145, 30), KIND_STATIC: (30, 175, 245)}

PROCESSED_VIDEO_NAME = "processed.mp4"
EDGE_SOURCE = "edge contour"
MOTION_SOURCE = "motion heatmap"

# Quality warnings: same wording and thresholds as upstream.
WARN_FRAME_COUNT = (
    "Container reports {reported} frames; decoder read {decoded}. Check for truncation."
)
WARN_GLOBAL_CHANGE = (
    "Large global changes detected: camera movement, scene cuts, or lighting may invalidate "
    "fixed-camera zones."
)
WARN_TRANSLATION = (
    "Median image translation exceeds 3 analysis pixels; stabilize before trusting zone locations."
)
WARN_STATIC_FALLBACK = (
    "FastSAM unavailable/no masks: edge-contour static proposals have limited recall."
)
WARN_NO_FLOOR = (
    "No reliable floor-like mask found; static-zone ranking uses general scene candidates."
)

SEGMENTATION_FALLBACK = "edge-contour fallback"
_MODEL_DISPLAY = {"yolo11s": "YOLO11s", "yolov8s-worldv2": "YOLOv8s-World"}


def segmentation_method_for(models: Sequence[str]) -> str:
    """``local YOLO11s boxes on the temporal background + edge contours`` for the default."""
    names = " + ".join(_MODEL_DISPLAY.get(m, m) for m in models)
    return f"local {names} boxes on the temporal background + edge contours"


# --- small upstream helpers (identical) ---------------------------------------------------


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    (x0, y0) = (max(a[0], b[0]), max(a[1], b[1]))
    (x1, y1) = (min(a[2], b[2]), min(a[3], b[3]))
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0


def select_distinct(proposals: list[dict], limit: int) -> list[dict]:
    selected: list[dict] = []
    for item in sorted(proposals, key=lambda p: p["proposal_score"], reverse=True):
        if all(
            box_iou(item["bbox_analysis"], old["bbox_analysis"]) < SELECT_IOU for old in selected
        ):
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


@contextmanager
def single_threaded_cv() -> Iterator[None]:
    """Upstream calls ``cv2.setNumThreads(1)``; scope it so the API process is restored."""
    previous = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        yield
    finally:
        cv2.setNumThreads(previous)


def write_dict_csv(path: Path, rows: list[dict], columns: Sequence[str] | None = None) -> None:
    """``pandas.DataFrame(rows).to_csv(index=False)`` without pandas: ordered column union."""
    if columns is None:
        ordered: dict[str, None] = {}
        for row in rows:
            ordered.update(dict.fromkeys(row))
        columns = list(ordered)

    def cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, dict)):
            return str(value)
        return value

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([cell(row.get(c)) for c in columns])


# --- [1/6] decode --------------------------------------------------------------------------


@dataclass
class DecodedVideo:
    frames: list[np.ndarray]
    fps: float
    source_w: int
    source_h: int
    reported_n: int
    aw: int
    ah: int

    @property
    def n(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        return self.n / self.fps

    @property
    def times(self) -> np.ndarray:
        return frame_times(self.n, self.fps)


def analysis_size(source_w: int, source_h: int, analysis_width: int = 768) -> tuple[int, int]:
    aw = min(analysis_width, source_w)
    ah = round(source_h * aw / source_w)
    return aw, ah


def frame_times(n: int, fps: float) -> np.ndarray:
    """Timing = frame_index / source_fps."""
    return np.arange(n) / fps


def decode_video(path: Path, cfg: Mapping[str, Any] = CFG) -> DecodedVideo:
    """Decode EVERY frame, resized to the analysis width with INTER_AREA."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot decode {Path(path).name}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    (source_w, source_h) = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    reported_n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not np.isfinite(fps) or fps <= 0 or min(source_w, source_h) <= 0:
        cap.release()
        raise ValueError("Invalid video dimensions or FPS")
    aw, ah = analysis_size(source_w, source_h, cfg["analysis_width"])
    frames: list[np.ndarray] = []
    try:
        while True:
            (ok, frame) = cap.read()
            if not ok:
                break
            if len(frames) >= cfg["max_frames"]:
                raise ValueError(
                    "Video exceeds the configured memory/frame limit; process it in chunks."
                )
            frames.append(cv2.resize(frame, (aw, ah), interpolation=cv2.INTER_AREA))
    finally:
        cap.release()
    if len(frames) < 2:
        raise ValueError("At least two decodable frames are required")
    return DecodedVideo(frames, fps, source_w, source_h, reported_n, aw, ah)


def background_indices(n: int, samples: int = 21) -> np.ndarray:
    return np.unique(np.linspace(0, n - 1, min(n, samples)).astype(int))


def temporal_background(frames: Sequence[np.ndarray], indices: np.ndarray) -> np.ndarray:
    """Per-pixel median of the evenly spaced sample frames."""
    return np.median(np.stack([frames[i] for i in indices]), axis=0).astype(np.uint8)


def frame_count_warning(reported_n: int, decoded_n: int) -> str | None:
    if reported_n and reported_n != decoded_n:
        return WARN_FRAME_COUNT.format(reported=reported_n, decoded=decoded_n)
    return None


# --- [2/6] motion --------------------------------------------------------------------------


@dataclass
class Motion:
    gray: np.ndarray
    bg_gray: np.ndarray
    masks: np.ndarray
    step_fraction: np.ndarray
    heatmap: np.ndarray
    fraction: np.ndarray


def compute_motion(
    frames: Sequence[np.ndarray], background: np.ndarray, cfg: Mapping[str, Any] = CFG
) -> Motion:
    """Adjacent OR background difference > threshold on 5x5-blurred gray; open 3x3, close 7x7."""
    n = len(frames)
    ah, aw = frames[0].shape[:2]
    gray = np.stack(
        [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0) for f in frames]
    )
    bg_gray = cv2.GaussianBlur(cv2.cvtColor(background, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    kernel3 = np.ones((3, 3), np.uint8)
    masks = np.zeros((n, ah, aw), dtype=np.uint8)
    step_fraction = np.zeros(n)
    for i in range(1, n):
        adjacent = cv2.absdiff(gray[i], gray[i - 1]) > cfg["difference_threshold"]
        background_change = cv2.absdiff(gray[i], bg_gray) > cfg["difference_threshold"]
        step_fraction[i] = adjacent.mean()
        moving = (adjacent | background_change).astype(np.uint8)
        moving = cv2.morphologyEx(moving, cv2.MORPH_OPEN, kernel3)
        masks[i] = cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    heatmap = masks[1:].mean(axis=0)
    fraction = masks.mean(axis=(1, 2))
    return Motion(gray, bg_gray, masks, step_fraction, heatmap, fraction)


def global_change_warning(step_fraction: np.ndarray) -> str | None:
    if (step_fraction > GLOBAL_CHANGE_FRACTION).any():
        return WARN_GLOBAL_CHANGE
    return None


def translation_warning(gray: np.ndarray, bg_indices: np.ndarray) -> str | None:
    shifts = []
    for i in bg_indices[1:]:
        (shift, response) = cv2.phaseCorrelate(
            gray[0].astype(np.float32), gray[i].astype(np.float32)
        )
        if response > SHIFT_RESPONSE_MIN:
            shifts.append(float(np.hypot(*shift)))
    if shifts and np.median(shifts) > SHIFT_MEDIAN_MAX_PX:
        return WARN_TRANSLATION
    return None


def heatmap_image(background: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
    """``motion_heatmap.png``: magma colour map over the background (vmin 0, vmax 1, 0.65)."""
    heat = cv2.applyColorMap(np.clip(heatmap * 255.0, 0, 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    return cv2.addWeighted(background, 0.35, heat, 0.65, 0)


# --- [3/6] proposals -----------------------------------------------------------------------


def movement_proposals(
    motion: Motion, times: np.ndarray, aw: int, ah: int, cfg: Mapping[str, Any] = CFG
) -> list[dict]:
    active = (motion.heatmap > cfg["motion_frequency_threshold"]).astype(np.uint8)
    active = cv2.morphologyEx(active, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    (_count, _labels, stats, _centroids) = cv2.connectedComponentsWithStats(active)
    proposals = []
    for x, y, w, h, area in stats[1:]:
        if area < aw * ah * cfg["minimum_zone_fraction"] or w * h > 0.6 * aw * ah:
            continue
        trace = motion.masks[:, y : y + h, x : x + w].mean(axis=(1, 2))
        peak = int(np.argmax(trace))
        active_indices = np.flatnonzero(
            trace > max(0.01, float(trace.max()) * ACTIVE_PEAK_FRACTION)
        )
        proposals.append(
            {
                "kind": KIND_MOVEMENT,
                "bbox_analysis": [int(x), int(y), int(x + w), int(y + h)],
                "proposal_score": float(motion.heatmap[y : y + h, x : x + w].sum()),
                "peak_frame": peak,
                "active_start_s": float(times[active_indices[0]]) if len(active_indices) else 0.0,
                "active_end_s": float(times[active_indices[-1]]) if len(active_indices) else 0.0,
            }
        )
    return proposals


def paint_mask(hsv: np.ndarray) -> np.ndarray:
    """Yellow/green floor paint, same HSV range as upstream."""
    return cv2.inRange(hsv, PAINT_HSV_LOW, PAINT_HSV_HIGH)


def edge_contour_masks(bg_gray: np.ndarray, aw: int, ah: int) -> list[np.ndarray]:
    """The upstream fallback region masks: closed Canny edges -> filled contours."""
    edges = cv2.Canny(bg_gray, 60, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    (contours, _) = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    masks = []
    for contour in contours:
        mask = np.zeros((ah, aw), np.uint8)
        cv2.drawContours(mask, [contour], -1, 1, cv2.FILLED)
        masks.append(mask)
    return masks


def box_masks(result: DetectResult, aw: int, ah: int) -> tuple[list[np.ndarray], list[str]]:
    """Each detector box (in the posted image's pixels) -> a rectangular analysis mask."""
    sx, sy = aw / result.width, ah / result.height
    masks: list[np.ndarray] = []
    sources: list[str] = []
    for obj in result.objects:
        (x0, y0, x1, y1) = obj.box
        if not all(math.isfinite(v) for v in obj.box):
            continue
        xa = max(0, min(aw, math.floor(min(x0, x1) * sx)))
        xb = max(0, min(aw, math.ceil(max(x0, x1) * sx)))
        ya = max(0, min(ah, math.floor(min(y0, y1) * sy)))
        yb = max(0, min(ah, math.ceil(max(y0, y1) * sy)))
        if xb <= xa or yb <= ya:
            continue
        mask = np.zeros((ah, aw), np.uint8)
        mask[ya:yb, xa:xb] = 1
        masks.append(mask)
        sources.append(f"{obj.model}: {obj.label} ({obj.conf:.2f})")
    return masks, sources


def floor_from_masks(
    region_masks: Sequence[np.ndarray],
    hsv: np.ndarray,
    edge_map: np.ndarray,
    aw: int,
    ah: int,
) -> np.ndarray:
    """Union of floor-like masks: > 4% area, touches the bottom rows, low saturation/edges."""
    floor_mask = np.zeros((ah, aw), np.uint8)
    for mask in region_masks:
        if mask.shape != (ah, aw):
            mask = cv2.resize(mask, (aw, ah), interpolation=cv2.INTER_NEAREST)
        inside = mask > 0
        if (
            inside.sum() > 0.04 * aw * ah
            and mask[-3:].mean() > 0.02
            and (np.median(hsv[:, :, 1][inside]) < 70)
            and ((edge_map[inside] > 0).mean() < 0.06)
        ):
            floor_mask |= mask
    return floor_mask


def static_proposals(
    region_masks: Sequence[np.ndarray],
    heatmap: np.ndarray,
    floor_mask: np.ndarray,
    floor_available: bool,
    paint: np.ndarray,
    paint_near: np.ndarray,
    times: np.ndarray,
    aw: int,
    ah: int,
) -> tuple[list[dict], list[int]]:
    """Upstream static candidates, same exclusions and score. Also returns mask indices."""
    proposals: list[dict] = []
    kept: list[int] = []
    for index, mask in enumerate(region_masks):
        if mask.shape != (ah, aw):
            mask = cv2.resize(mask, (aw, ah), interpolation=cv2.INTER_NEAREST)
        (ys, xs) = np.where(mask > 0)
        area = len(xs)
        if area < 0.002 * aw * ah or area > 0.15 * aw * ah:
            continue
        (x0, x1, y0, y1) = (int(xs.min()), int(xs.max() + 1), int(ys.min()), int(ys.max() + 1))
        if x1 - x0 < 12 or y1 - y0 < 12 or (x1 - x0) * (y1 - y0) > 0.2 * aw * ah:
            continue
        stability = 1 - float(heatmap[mask > 0].mean())
        proximity = float(paint_near[mask > 0].mean())
        if floor_available and float(floor_mask[mask > 0].mean()) > 0.5:
            continue
        if float((paint[mask > 0] > 0).mean()) > 0.6:
            continue
        ring = (cv2.dilate(mask, np.ones((15, 15), np.uint8)) > 0) & (mask == 0)
        floor_contact = float(floor_mask[ring].mean()) if floor_available and ring.any() else 0.5
        score = (
            math.sqrt(area / (aw * ah))
            * stability
            * (0.05 + floor_contact) ** 2
            * (1 + 2 * proximity)
        )
        proposals.append(
            {
                "kind": KIND_STATIC,
                "bbox_analysis": [x0, y0, x1, y1],
                "proposal_score": score,
                "stability": stability,
                "paint_proximity": proximity,
                "floor_contact": floor_contact,
                "peak_frame": 0,
                "active_start_s": 0.0,
                "active_end_s": float(times[-1]),
            }
        )
        kept.append(index)
    return proposals, kept


@dataclass
class DetectorRun:
    """What the local detector contributed (recorded in zones.json, report and manifest)."""

    url: str | None
    requested_models: list[str]
    conf: float
    status: str = "disabled"  # ok | no_boxes | unreachable | models_missing | error | disabled
    error: str | None = None
    device: str | None = None
    models_sha256: dict[str, str] | None = None
    used_models: list[str] = field(default_factory=list)
    image_size: list[int] | None = None
    elapsed_ms: float | None = None
    objects: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "error": self.error,
            "device": self.device,
            "requested_models": self.requested_models,
            "used_models": self.used_models,
            "models_sha256": self.models_sha256,
            "conf": self.conf,
            "image": "temporal background (analysis resolution, PNG)",
            "image_size": self.image_size,
            "boxes": len(self.objects),
            "elapsed_ms": self.elapsed_ms,
            "objects": self.objects,
        }


def detect_on_background(
    background: np.ndarray,
    detector: DetectorClient | None,
    *,
    health: DetectorHealth | None = None,
    models: Sequence[str] = DEFAULT_MODELS,
    conf: float = DEFAULT_CONF,
) -> tuple[DetectResult | None, DetectorRun]:
    """Run the local YOLO models on the temporal background; never raises."""
    run = DetectorRun(
        url=detector.base_url if detector else None, requested_models=list(models), conf=conf
    )
    if detector is None:
        run.error = "detector disabled"
        return None, run
    health = health if health is not None else detector.health()
    run.device = health.device
    if not health.ok:
        run.status, run.error = "unreachable", health.error
        return None, run
    available = [m for m in models if m in health.models]
    if not available:
        run.status = "models_missing"
        run.error = f"detector serves {sorted(health.models)}, not {list(models)}"
        return None, run
    ok, encoded = cv2.imencode(".png", background)
    if not ok:
        run.status, run.error = "error", "could not encode the background image"
        return None, run
    try:
        result = detector.detect(
            encoded.tobytes(), content_type="image/png", models=available, conf=conf
        )
    except DetectorError as exc:
        run.status, run.error = "error", str(exc)
        return None, run
    run.used_models = available
    run.models_sha256 = {m: health.models[m] for m in available}
    run.image_size = [result.width, result.height]
    run.elapsed_ms = result.elapsed_ms
    run.objects = [o.as_dict() for o in result.objects]
    run.status = "ok" if result.objects else "no_boxes"
    return result, run


@dataclass
class StaticStage:
    proposals: list[dict]
    sources: list[str]
    floor_mask: np.ndarray
    floor_available: bool
    segmentation_method: str
    warnings: list[str]
    yolo_mask_count: int
    edge_mask_count: int


def propose_static(
    background: np.ndarray,
    bg_gray: np.ndarray,
    heatmap: np.ndarray,
    times: np.ndarray,
    aw: int,
    ah: int,
    detected: DetectResult | None,
    used_models: Sequence[str] = DEFAULT_MODELS,
) -> StaticStage:
    """Static candidates = YOLO boxes UNION edge contours; floor from edge contours only.

    ``detected`` is None when the detector did not answer (unreachable, error, models
    missing, disabled): that alone takes the original "edge-contour fallback" and its
    warning. A detector that answered with zero boxes still ran the YOLO method; the
    candidate set is then exactly the edge contours (``pipeline.detector.status`` records
    ``no_boxes``).
    """
    hsv = cv2.cvtColor(background, cv2.COLOR_BGR2HSV)
    paint = paint_mask(hsv)
    paint_near = cv2.dilate(paint, np.ones((21, 21), np.uint8)) > 0
    warnings: list[str] = []
    edge_masks = edge_contour_masks(bg_gray, aw, ah)
    yolo_masks, yolo_sources = box_masks(detected, aw, ah) if detected else ([], [])
    if detected is not None:
        segmentation_method = segmentation_method_for(used_models)
        region_masks = [*yolo_masks, *edge_masks]
        sources = [*yolo_sources, *([EDGE_SOURCE] * len(edge_masks))]
    else:
        segmentation_method = SEGMENTATION_FALLBACK
        region_masks = list(edge_masks)
        sources = [EDGE_SOURCE] * len(edge_masks)
        warnings.append(WARN_STATIC_FALLBACK)
    edge_map = cv2.Canny(bg_gray, 60, 150)
    floor_mask = floor_from_masks(edge_masks, hsv, edge_map, aw, ah)
    floor_available = bool(floor_mask.any())
    if floor_available:
        floor_near = cv2.dilate(floor_mask, np.ones((9, 9), np.uint8)) > 0
        paint_near = (
            cv2.dilate(((paint > 0) & floor_near).astype(np.uint8), np.ones((21, 21), np.uint8)) > 0
        )
    else:
        warnings.append(WARN_NO_FLOOR)
    proposals, kept = static_proposals(
        region_masks, heatmap, floor_mask, floor_available, paint, paint_near, times, aw, ah
    )
    return StaticStage(
        proposals=proposals,
        sources=[sources[i] for i in kept],
        floor_mask=floor_mask,
        floor_available=floor_available,
        segmentation_method=segmentation_method,
        warnings=warnings,
        yolo_mask_count=len(yolo_masks),
        edge_mask_count=len(edge_masks),
    )


def select_zones(
    motion_props: list[dict],
    static_props: list[dict],
    aw: int,
    ah: int,
    source_w: int,
    source_h: int,
    cfg: Mapping[str, Any] = CFG,
) -> list[dict]:
    """<= 5 movement + <= 5 static zones (IoU 0.6), ids Z01... in that order."""
    zones = select_distinct(motion_props, cfg["max_motion_zones"]) + select_distinct(
        static_props, cfg["max_static_zones"]
    )
    for i, zone in enumerate(zones, 1):
        zone["zone_id"] = f"Z{i:02d}"
        box = zone["bbox_analysis"]
        zone["bbox_normalized"] = [
            round(box[0] / aw, 5),
            round(box[1] / ah, 5),
            round(box[2] / aw, 5),
            round(box[3] / ah, 5),
        ]
        zone["bbox_source"] = [
            round(box[0] * source_w / aw),
            round(box[1] * source_h / ah),
            round(box[2] * source_w / aw),
            round(box[3] * source_h / ah),
        ]
    return zones


# --- [4/6] annotated video and evidence ----------------------------------------------------


def annotate(
    frame: np.ndarray, zones: Sequence[dict], timestamp: float | None = None
) -> np.ndarray:
    output = frame.copy()
    for z in zones:
        (x0, y0, x1, y1) = z["bbox_analysis"]
        color = COLORS[z["kind"]]
        tag = z["zone_id"] + (" M" if z["kind"] == KIND_MOVEMENT else " S")
        cv2.rectangle(output, (x0, y0), (x1, y1), color, 2)
        cv2.putText(
            output, tag, (x0, max(15, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3
        )
        cv2.putText(output, tag, (x0, max(15, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    if timestamp is not None:
        output = cv2.copyMakeBorder(
            output, BANNER_PX, 0, 0, 0, cv2.BORDER_CONSTANT, value=(22, 22, 22)
        )
        cv2.putText(
            output,
            f"t={timestamp:.2f}s | M: movement | S: stationary review candidate",
            (8, 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (255, 255, 255),
            1,
        )
    return output


def probe_video(path: Path) -> dict[str, Any]:
    """Codec, pixel format and exact decoded frame count (ffprobe -count_frames)."""
    proc = run_tool(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,nb_read_frames,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        what="ffprobe processed video",
    )
    stream = (json.loads(proc.stdout).get("streams") or [{}])[0]
    return {
        "codec": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "frames": int(stream.get("nb_read_frames") or 0),
        "frame_rate": stream.get("r_frame_rate"),
    }


def write_processed_video(
    frames: Sequence[np.ndarray],
    zones: Sequence[dict],
    times: np.ndarray,
    fps: float,
    out_path: Path,
) -> dict[str, Any]:
    """Annotated frames via cv2 (lossless intermediate), then browser H.264 via ffmpeg."""
    n = len(frames)
    ah, aw = frames[0].shape[:2]
    writer = None
    intermediate = None
    for codec, suffix in (("FFV1", ".avi"), ("MJPG", ".avi"), ("mp4v", ".mp4")):
        candidate_path = out_path.with_name(f"{out_path.stem}.cv2{suffix}")
        candidate = cv2.VideoWriter(
            str(candidate_path),
            cv2.CAP_FFMPEG,
            cv2.VideoWriter_fourcc(*codec),
            fps,
            (aw, ah + BANNER_PX),
        )
        if candidate.isOpened():
            writer, intermediate = candidate, (codec, candidate_path)
            break
        candidate.release()
    if writer is None or intermediate is None:
        raise RuntimeError(
            "No video encoder available; install an OpenCV build with video encoding support"
        )
    try:
        for i, f in enumerate(frames):
            writer.write(annotate(f, zones, float(times[i])))
    finally:
        writer.release()
    codec, tmp_path = intermediate
    ffmpeg = ffmpeg_bin()
    try:
        run_tool(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(tmp_path),
                "-map",
                "0:v:0",
                "-an",
                *passthrough_args(ffmpeg),
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            what="processed video H.264 transcode",
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    check = cv2.VideoCapture(str(out_path))
    try:
        if not (check.isOpened() and int(check.get(cv2.CAP_PROP_FRAME_COUNT)) == n):
            raise RuntimeError("Processed video failed frame-count verification")
    finally:
        check.release()
    probe = probe_video(out_path)
    if probe["codec"] != "h264" or probe["pix_fmt"] != "yuv420p" or probe["frames"] != n:
        raise RuntimeError(f"Processed video is not browser H.264 with {n} frames: {probe}")
    return {"name": out_path.name, **probe, "intermediate_codec": codec, "faststart": True}


def evidence_label(eid: str, timestamp_s: float, kind: str, zone_id: str | None = None) -> str:
    """Burned-in label ``E### | t=1.234s | kind | Z##`` (upstream format)."""
    return f"{eid} | t={timestamp_s:.3f}s | {kind}" + (f" | {zone_id}" if zone_id else "")


def overview_indices(n: int, cfg: Mapping[str, Any] = CFG) -> set[int]:
    return set(np.linspace(0, n - 1, min(n, cfg["overview_frames"])).astype(int).tolist())


def peak_indices(
    motion_fraction: np.ndarray, fps: float, cfg: Mapping[str, Any] = CFG
) -> list[int]:
    """Top motion frames, at least 0.7 s apart (same argsort walk as upstream)."""
    peaks: list[int] = []
    for i in np.argsort(motion_fraction)[::-1]:
        if all(abs(i - j) / fps >= PEAK_MIN_GAP_S for j in peaks):
            peaks.append(int(i))
        if len(peaks) >= cfg["peak_frames"]:
            break
    return peaks


@dataclass(frozen=True)
class EvidenceRequest:
    frame_index: int
    kind: str
    zone_id: str | None = None
    box: tuple[int, int, int, int] | None = None
    max_width: int | None = None


def evidence_plan(
    n: int,
    fps: float,
    motion_fraction: np.ndarray,
    zones: Sequence[dict],
    source_w: int,
    source_h: int,
    cfg: Mapping[str, Any] = CFG,
) -> list[EvidenceRequest]:
    """Upstream evidence order: uniform + peak full scenes, zone crops, 4 scene tiles."""
    plan: list[EvidenceRequest] = []
    full = overview_indices(n, cfg) | set(peak_indices(motion_fraction, fps, cfg))
    for i in sorted(full):
        plan.append(EvidenceRequest(int(i), EVIDENCE_FULL))
    for z in zones:
        (x0, y0, x1, y1) = z["bbox_source"]
        pad = max(50, round(max(x1 - x0, y1 - y0) * 0.25))
        box = (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(source_w, x1 + pad),
            min(source_h, y1 + pad),
        )
        indices = [z["peak_frame"], n - 1 if z["peak_frame"] < n // 2 else 0]
        for i in sorted(set(indices)):
            plan.append(
                EvidenceRequest(int(i), EVIDENCE_ZONE, z["zone_id"], box, cfg["crop_width"])
            )
    for y0, y1 in [(0, round(source_h * 0.55)), (round(source_h * 0.45), source_h)]:
        for x0, x1 in [(0, round(source_w * 0.55)), (round(source_w * 0.45), source_w)]:
            plan.append(
                EvidenceRequest(n // 2, EVIDENCE_TILE, None, (x0, y0, x1, y1), cfg["crop_width"])
            )
    return plan


def write_evidence(
    video_path: Path,
    out: Path,
    plan: Sequence[EvidenceRequest],
    times: np.ndarray,
    source_w: int,
    source_h: int,
    cfg: Mapping[str, Any] = CFG,
) -> list[dict]:
    """Crop original-resolution frames, burn in the label, JPEG q92, 40-image budget."""
    evidence: list[dict] = []
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    source_cap = cv2.VideoCapture(str(video_path))

    def original_frame(index: int) -> np.ndarray:
        source_cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        (ok, image) = source_cap.read()
        if not ok:
            raise RuntimeError(f"Could not read source frame {index}")
        return image

    try:
        for req in plan:
            if len(evidence) >= cfg["max_total_images"]:
                raise ValueError(
                    "Evidence image budget exceeded; revise sampling settings explicitly"
                )
            frame = original_frame(req.frame_index)
            if req.box:
                (x0, y0, x1, y1) = req.box
                frame = frame[y0:y1, x0:x1]
            if frame.size == 0:
                raise ValueError("Empty evidence crop")
            max_width = req.max_width or cfg["image_width"]
            scale = min(1.0, max_width / frame.shape[1])
            frame = cv2.resize(
                frame,
                (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))),
            )
            canvas = np.full(
                (
                    frame.shape[0] + EVIDENCE_HEADER_PX,
                    max(frame.shape[1], EVIDENCE_MIN_CANVAS_W),
                    3,
                ),
                22,
                np.uint8,
            )
            canvas[EVIDENCE_HEADER_PX:, : frame.shape[1]] = frame
            eid = f"E{len(evidence) + 1:03d}"
            label = evidence_label(eid, float(times[req.frame_index]), req.kind, req.zone_id)
            cv2.putText(canvas, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            path = out / "evidence" / f"{eid}.jpg"
            if not cv2.imwrite(
                str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, EVIDENCE_JPEG_QUALITY]
            ):
                raise RuntimeError(f"Failed writing {path.name}")
            evidence.append(
                {
                    "evidence_id": eid,
                    "frame_index": int(req.frame_index),
                    "timestamp_s": float(times[req.frame_index]),
                    "kind": req.kind,
                    "zone_id": req.zone_id,
                    "bbox_source": list(req.box) if req.box else [0, 0, source_w, source_h],
                    "path": str(path.relative_to(out)),
                    "sha256": sha256_file(path),
                }
            )
    finally:
        source_cap.release()
    return evidence


# --- orchestration of steps 1-4 ------------------------------------------------------------


@dataclass
class ScanResult:
    meta: dict[str, Any]
    quality_warnings: list[str]
    zones: list[dict]
    evidence: list[dict]
    segmentation_method: str
    detector: DetectorRun
    zone_sources: dict[str, str]
    processed_video: dict[str, Any]
    candidate_counts: dict[str, int]
    times: np.ndarray
    heatmap: np.ndarray
    n: int
    duration: float
    aw: int
    ah: int

    @property
    def weights_sha256(self) -> dict[str, str] | None:
        return self.detector.models_sha256 if self.detector.status == "ok" else None


def run_scan(
    video_path: Path,
    out: Path,
    *,
    source_name: str,
    source_sha256: str,
    detector: DetectorClient | None,
    detector_health: DetectorHealth | None = None,
    detector_models: Sequence[str] = DEFAULT_MODELS,
    detector_conf: float = DEFAULT_CONF,
    cfg: Mapping[str, Any] = CFG,
    progress: Callable[[int], None] = lambda _step: None,
) -> ScanResult:
    """Steps 1-4 of the upstream script; writes the CV artifacts into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence").mkdir(exist_ok=True)

    progress(1)
    video = decode_video(video_path, cfg)
    n, fps, aw, ah = video.n, video.fps, video.aw, video.ah
    (source_w, source_h) = (video.source_w, video.source_h)
    times = video.times
    bg_idx = background_indices(n, cfg["background_samples"])
    background = temporal_background(video.frames, bg_idx)
    quality_warnings: list[str] = []
    if warning := frame_count_warning(video.reported_n, n):
        quality_warnings.append(warning)
    meta = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "fps": fps,
        "source_width": source_w,
        "source_height": source_h,
        "decoded_frames": n,
        "reported_frames": video.reported_n,
        "duration_s": video.duration,
        "analysis_width": aw,
        "analysis_height": ah,
        "timing_method": "frame_index/source_fps",
    }
    save_json(out / "video_metadata.json", meta)

    progress(2)
    motion = compute_motion(video.frames, background, cfg)
    for warning in (
        global_change_warning(motion.step_fraction),
        translation_warning(motion.gray, bg_idx),
    ):
        if warning:
            quality_warnings.append(warning)
    np.savez_compressed(
        out / "motion_data.npz",
        heatmap=motion.heatmap,
        frame_times_s=times,
        frame_motion_fraction=motion.fraction,
    )
    write_dict_csv(
        out / "motion_timeline.csv",
        [
            {"time_s": float(t), "motion_fraction": float(m), "adjacent_change_fraction": float(s)}
            for t, m, s in zip(times, motion.fraction, motion.step_fraction, strict=True)
        ],
        ["time_s", "motion_fraction", "adjacent_change_fraction"],
    )
    cv2.imwrite(str(out / "motion_heatmap.png"), heatmap_image(background, motion.heatmap))
    log.info("quality warnings: %s", quality_warnings or "none")

    progress(3)
    motion_props = movement_proposals(motion, times, aw, ah, cfg)
    detected, detector_run = detect_on_background(
        background, detector, health=detector_health, models=detector_models, conf=detector_conf
    )
    static = propose_static(
        background,
        motion.bg_gray,
        motion.heatmap,
        times,
        aw,
        ah,
        detected,
        detector_run.used_models or detector_models,
    )
    quality_warnings.extend(static.warnings)
    cv2.imwrite(str(out / "floor_proposal_mask.png"), static.floor_mask * 255)
    source_of = {id(p): s for p, s in zip(static.proposals, static.sources, strict=True)}
    zones = select_zones(motion_props, static.proposals, aw, ah, source_w, source_h, cfg)
    zone_sources = {
        z["zone_id"]: (MOTION_SOURCE if z["kind"] == KIND_MOVEMENT else source_of[id(z)])
        for z in zones
    }
    save_json(
        out / "all_zone_proposals.json", {"movement": motion_props, "static": static.proposals}
    )
    write_dict_csv(out / "zones.csv", zones)
    candidate_counts = {"movement": len(motion_props), "static": len(static.proposals)}
    save_json(
        out / "zones.json",
        {
            "method": static.segmentation_method,
            "zones": zones,
            "candidate_counts": candidate_counts,
            "note": "Proposal scores are heuristic rankings within each kind, not hazard probabilities.",
            "zone_sources": zone_sources,
            "region_masks": {
                "yolo_boxes": static.yolo_mask_count,
                "edge_contours": static.edge_mask_count,
            },
            "detector": detector_run.as_dict(),
        },
    )
    log.info(
        "%d movement candidates, %d static candidates; %d zones selected.",
        len(motion_props),
        len(static.proposals),
        len(zones),
    )

    progress(4)
    processed = write_processed_video(video.frames, zones, times, fps, out / PROCESSED_VIDEO_NAME)
    cv2.imwrite(str(out / "zones_overview.jpg"), annotate(video.frames[0], zones))
    plan = evidence_plan(n, fps, motion.fraction, zones, source_w, source_h, cfg)
    del video  # free decoded frames before reading full-resolution evidence frames
    evidence = write_evidence(video_path, out, plan, times, source_w, source_h, cfg)
    save_json(out / "evidence_manifest.json", evidence)
    log.info("%d evidence images", len(evidence))
    return ScanResult(
        meta=meta,
        quality_warnings=quality_warnings,
        zones=zones,
        evidence=evidence,
        segmentation_method=static.segmentation_method,
        detector=detector_run,
        zone_sources=zone_sources,
        processed_video=processed,
        candidate_counts=candidate_counts,
        times=times,
        heatmap=motion.heatmap,
        n=n,
        duration=n / fps,
        aw=aw,
        ah=ah,
    )

#!/usr/bin/env python3
"""Relative depth for one real frame of each wall clip, computed on this machine.

Runs Depth Anything V2 Small (``onnx-community/depth-anything-v2-small``, Apache-2.0)
through onnxruntime on the CPU over the middle frame of
``data/hazards/clips/<clip_id>/source.mp4`` and writes
``data/hazards/clips/<clip_id>/depth.json``: a coarse grid of RELATIVE inverse depth
(higher = nearer) plus where it came from. The camera wall's blind-zone plan drapes the
clip's video over that grid to draw the scene in 3D.

What the numbers are, and are not:

* the model predicts affine-invariant inverse depth, so scale and shift are unknown and
  the clips carry no camera calibration: the grid is never metres;
* values are clipped to the frame's 1st..99th percentile, min-max normalised and stored
  as uint8 (255 = nearest), row-major from the top-left, base64-encoded;
* nothing here is part of a GB10 review run, and no finding depends on it.

The preprocessing follows the model's ``preprocessor_config.json`` for sizes and
normalisation (DPTImageProcessor: keep the aspect ratio, take whichever scale is nearer 1,
snap each side to a multiple of 14, ImageNet mean/std). The resize itself is OpenCV
bicubic, as in the upstream Depth-Anything-V2 transform, so values can differ slightly from
the transformers (PIL) path. Download the model once into the gitignored ``models/``::

    models/depth-anything-v2-small/model.onnx
    models/depth-anything-v2-small/preprocessor_config.json

Usage::

    uv run --group depth python scripts/hazards/depth_relief.py hz_00 hz_01 bs_01 bs_02
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hazards.scan import save_json, sha256_file

MODEL_ID = "onnx-community/depth-anything-v2-small"
MODEL_LICENSE = "Apache-2.0"
MODEL_DIR = REPO_ROOT / "models" / "depth-anything-v2-small"
CLIPS_DIR = REPO_ROOT / "data" / "hazards" / "clips"
OUTPUT_NAME = "depth.json"
GRID_WIDTH = 192  # grid height follows the frame's aspect ratio
CLIP_PERCENTILES = (1.0, 99.0)


def constrain_to_multiple_of(value: float, multiple: int) -> int:
    """DPT's rounding: nearest multiple, never below one multiple."""
    return max(multiple, round(value / multiple) * multiple)


def model_input_size(width: int, height: int, config: dict[str, Any]) -> tuple[int, int]:
    """``(width, height)`` the DPTImageProcessor resizes a ``width`` x ``height`` frame to."""
    target_h = config["size"]["height"]
    target_w = config["size"]["width"]
    multiple = int(config.get("ensure_multiple_of") or 1)
    scale_h = target_h / height
    scale_w = target_w / width
    if config.get("keep_aspect_ratio"):
        if abs(1 - scale_w) < abs(1 - scale_h):
            scale_h = scale_w
        else:
            scale_w = scale_h
    return (
        constrain_to_multiple_of(scale_w * width, multiple),
        constrain_to_multiple_of(scale_h * height, multiple),
    )


def preprocess(rgb: np.ndarray, config: dict[str, Any]) -> np.ndarray:
    """``rgb`` uint8 HxWx3 -> float32 1x3xH'xW': preprocessor_config sizes and mean/std, cv2 bicubic."""
    height, width = rgb.shape[:2]
    size = model_input_size(width, height, config)
    resized = cv2.resize(rgb, size, interpolation=cv2.INTER_CUBIC).astype(np.float32)
    resized *= float(config.get("rescale_factor", 1 / 255))
    mean = np.asarray(config["image_mean"], dtype=np.float32)
    std = np.asarray(config["image_std"], dtype=np.float32)
    normalised = (resized - mean) / std
    return np.ascontiguousarray(normalised.transpose(2, 0, 1)[None, ...], dtype=np.float32)


def read_frame(path: Path, index: int) -> np.ndarray:
    """Frame ``index`` as RGB, decoded sequentially (seeking can land on a keyframe)."""
    cap = cv2.VideoCapture(str(path))
    try:
        frame = None
        for _ in range(index + 1):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"{path}: could not decode frame {index}")
        assert frame is not None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        cap.release()


def frame_count(path: Path) -> tuple[int, float]:
    cap = cv2.VideoCapture(str(path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()


def quantise(depth: np.ndarray, width: int, height: int) -> tuple[np.ndarray, list[float]]:
    """Area-resample to ``width`` x ``height``, clip to the percentiles, scale to 0..255."""
    grid = cv2.resize(depth.astype(np.float32), (width, height), interpolation=cv2.INTER_AREA)
    lo, hi = (float(v) for v in np.percentile(grid, CLIP_PERCENTILES))
    span = hi - lo if hi > lo else 1.0
    scaled = np.clip((grid - lo) / span, 0.0, 1.0)
    return np.round(scaled * 255).astype(np.uint8), [lo, hi]


def relief_for_clip(clip_id: str, session: Any, config: dict[str, Any], model_sha: str) -> dict:
    clip_dir = CLIPS_DIR / clip_id
    source = clip_dir / "source.mp4"
    if not source.is_file():
        raise FileNotFoundError(f"{source} is missing")
    frames, fps = frame_count(source)
    index = frames // 2
    rgb = read_frame(source, index)
    height, width = rgb.shape[:2]

    pixel_values = preprocess(rgb, config)
    input_name = session.get_inputs()[0].name
    started = time.perf_counter()
    (predicted,) = session.run(None, {input_name: pixel_values})
    elapsed_ms = (time.perf_counter() - started) * 1000
    depth = np.asarray(predicted, dtype=np.float32).reshape(pixel_values.shape[2:])

    grid_h = max(2, round(GRID_WIDTH * height / width))
    grid, clip_range = quantise(depth, GRID_WIDTH, grid_h)
    return {
        "clip_id": clip_id,
        "kind": "relative_inverse_depth",
        "note": (
            "Relative inverse depth (higher = nearer) from one real frame; unknown scale "
            "and shift, never metres. Computed locally, not part of the GB10 review run."
        ),
        "model": {
            "id": MODEL_ID,
            "license": MODEL_LICENSE,
            "sha256": model_sha,
            "runtime": f"onnxruntime {ort_version()} (CPUExecutionProvider)",
            "input_size": list(pixel_values.shape[3:1:-1]),
            "inference_ms": round(elapsed_ms, 1),
        },
        "frame": {
            "index": index,
            "time_s": round(index / fps, 3) if fps else None,
            "of_frames": frames,
            "width": width,
            "height": height,
        },
        "source_sha256": sha256_file(source),
        "grid": {
            "width": GRID_WIDTH,
            "height": grid_h,
            "encoding": "uint8 base64, row-major from the top-left, 255 = nearest",
            "clip_percentiles": list(CLIP_PERCENTILES),
            "clip_range_raw": [round(v, 6) for v in clip_range],
            "data": base64.b64encode(grid.tobytes()).decode("ascii"),
        },
    }


def ort_version() -> str:
    import onnxruntime as ort

    return str(ort.__version__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("clips", nargs="+", help="clip ids, e.g. hz_00 bs_02")
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args(argv)

    import onnxruntime as ort

    model_path = args.model_dir / "model.onnx"
    config = json.loads((args.model_dir / "preprocessor_config.json").read_text())
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    model_sha = sha256_file(model_path)

    for clip_id in args.clips:
        doc = relief_for_clip(clip_id, session, config, model_sha)
        out = CLIPS_DIR / clip_id / OUTPUT_NAME
        save_json(out, doc)
        frame = doc["frame"]
        print(
            f"{clip_id}: frame {frame['index']}/{frame['of_frames']} "
            f"({frame['width']}x{frame['height']}) -> model input "
            f"{doc['model']['input_size']}, {doc['model']['inference_ms']} ms, "
            f"grid {doc['grid']['width']}x{doc['grid']['height']} -> {out.relative_to(REPO_ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

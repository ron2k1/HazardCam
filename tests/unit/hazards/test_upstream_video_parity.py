"""Same assumptions on the videos: run the UPSTREAM steps 1-4 and the port on one clip.

The original ``run_pipeline`` is one long function, so the test executes its statements
from the top through the evidence export (step 4), skipping only imports and the
matplotlib/pandas/print lines (no new dependencies), with FastSAM weights absent: exactly
the upstream "edge-contour fallback" path the port keeps when the detector is down.

Both pipelines then read the same generated video on the same machine. Decoding, motion,
quality warnings, movement and static proposals, zones, the floor mask, the annotated
frames and every evidence JPEG must be identical (byte for byte where both write files).
"""

from __future__ import annotations

import ast
import csv
import hashlib
import importlib
import importlib.util
import json
import math
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest

from hazards import scan
from hazards.detector.client import Detection, DetectorClient, DetectResult
from hazards.pipeline import STEP_MESSAGES
from tests.unit.hazards._helpers import (
    moving_square_frames,
    scene_background,
    unreachable_transport,
    write_video,
)
from tests.unit.hazards.conftest import needs_ffmpeg

REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = REPO_ROOT / scan.UPSTREAM_PATH
TREE = ast.parse(UPSTREAM.read_text(encoding="utf-8"))
# Statements touching these names only draw figures, build DataFrames or print.
_PLOT_NAMES = {"plt", "pd", "fig", "ax", "axes", "im", "zone_df", "matplotlib", "print", "preview"}
_HELPERS = {"sha256_file", "save_json", "box_iou", "select_distinct"}

pytestmark = needs_ffmpeg


def _upstream_steps_1_to_4() -> Any:
    run_pipeline = next(
        n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "run_pipeline"
    )
    body: list[ast.stmt] = []
    for stmt in run_pipeline.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "STANDARDS" for t in stmt.targets
        ):
            break  # step 5 (model) starts here
        names = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        if isinstance(stmt, ast.Import | ast.ImportFrom) or names & _PLOT_NAMES:
            continue
        body.append(stmt)
    helpers = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in _HELPERS]
    module = ast.Module(body=[*helpers, *body], type_ignores=[])
    return compile(module, str(UPSTREAM), "exec", dont_inherit=True)


UPSTREAM_CODE = _upstream_steps_1_to_4()


def run_upstream(video: Path, output_root: Path) -> dict[str, Any]:
    steps: list[str] = []
    namespace: dict[str, Any] = {
        "np": np,
        "cv2": cv2,
        "math": math,
        "hashlib": hashlib,
        "json": json,
        "importlib": importlib,
        "Path": Path,
        "progress": steps.append,
        "args": SimpleNamespace(
            video=video,
            output_dir=output_root,
            model="qwen3.6:35b-a3b",
            ollama_url="127.0.0.1:9",
            skip_model=True,
            refresh=False,
            weights=output_root / "absent-FastSAM-s.pt",
        ),
    }
    previous = cv2.getNumThreads()
    try:
        exec(UPSTREAM_CODE, namespace)  # noqa: S102 - pinned, sha-checked local file
    finally:
        cv2.setNumThreads(previous)
    namespace["steps"] = steps
    return namespace


def run_port(video: Path, out: Path) -> scan.ScanResult:
    detector = DetectorClient(transport=unreachable_transport())
    with scan.single_threaded_cv():
        return scan.run_scan(
            video,
            out,
            source_name="hz_99",
            source_sha256=scan.sha256_file(video),
            detector=detector,
            detector_health=detector.health(),
        )


# --- generated test clips (GENERATED TEST MEDIA) ---------------------------------------------


def _static_scene() -> tuple[Iterator[np.ndarray], float]:
    return moving_square_frames(scene_background(960, 540), 40), 10.0


def _camera_shake() -> tuple[Iterator[np.ndarray], float]:
    """Odd frames shifted 8 px: triggers the median-translation warning."""

    def frames() -> Iterator[np.ndarray]:
        for i, frame in enumerate(moving_square_frames(scene_background(960, 540), 40)):
            yield np.roll(frame, 8, axis=1) if i % 2 else frame

    return frames(), 10.0


def _lighting_flash() -> tuple[Iterator[np.ndarray], float]:
    """One over-exposed frame: triggers the global-change warning and a motion peak."""

    def frames() -> Iterator[np.ndarray]:
        for i, frame in enumerate(moving_square_frames(scene_background(960, 540), 30)):
            yield cv2.add(frame, np.full_like(frame, 90)) if i == 17 else frame

    return frames(), 12.5


def _small_short() -> tuple[Iterator[np.ndarray], float]:
    """400x300, 6 frames: no upscaling, < 8 overview and < 21 background frames, 520 px canvas."""
    return moving_square_frames(scene_background(400, 300), 6, square=30), 7.5


def _outlined_floor() -> tuple[Iterator[np.ndarray], float]:
    """A closed outline around the floor: the edge contours yield a floor mask."""
    background = scene_background(960, 540)
    cv2.rectangle(background, (6, 276), (953, 535), (200, 200, 200), 3)
    return moving_square_frames(background, 40), 10.0


SCENARIOS: dict[str, Callable[[], tuple[Iterator[np.ndarray], float]]] = {
    "static_scene": _static_scene,
    "camera_shake": _camera_shake,
    "lighting_flash": _lighting_flash,
    "small_short": _small_short,
    "outlined_floor": _outlined_floor,
}


@pytest.fixture(scope="module", params=list(SCENARIOS))
def both(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp(request.param)
    frames, fps = SCENARIOS[request.param]()
    video = write_video(root / "clips" / "hz_99" / "source.mp4", frames, fps)
    upstream = run_upstream(video, root / "upstream")
    port_out = root / "port"
    port = run_port(video, port_out)
    upstream_out = root / "upstream" / upstream["RUN_ID"]
    return SimpleNamespace(
        name=request.param,
        video=video,
        up=upstream,
        up_out=upstream_out,
        port=port,
        port_out=port_out,
    )


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_decode_and_metadata_match(both):
    up_meta = dict(both.up["META"])
    assert up_meta.pop("source_name") == "source.mp4"  # upstream sends the file name
    port_meta = dict(both.port.meta)
    assert port_meta.pop("source_name") == "hz_99"  # the port sends the neutral id
    assert port_meta == up_meta
    assert both.port.n == both.up["N"]
    np.testing.assert_array_equal(both.port.times, both.up["TIMES"])
    assert (both.port.aw, both.port.ah) == (both.up["AW"], both.up["AH"])


def test_motion_matches(both):
    port = np.load(both.port_out / "motion_data.npz")
    up = np.load(both.up_out / "motion_data.npz")
    for key in ("heatmap", "frame_times_s", "frame_motion_fraction"):
        np.testing.assert_array_equal(port[key], up[key])
    with (both.port_out / "motion_timeline.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert [float(r["adjacent_change_fraction"]) for r in rows] == both.up["step_fraction"].tolist()
    assert [float(r["motion_fraction"]) for r in rows] == both.up["MOTION_FRACTION"].tolist()


def test_quality_warnings_match(both):
    assert both.port.quality_warnings == both.up["QUALITY_WARNINGS"]
    expected = {
        "camera_shake": scan.WARN_TRANSLATION,
        "lighting_flash": scan.WARN_GLOBAL_CHANGE,
    }
    if both.name in expected:
        assert expected[both.name] in both.port.quality_warnings
    assert scan.WARN_STATIC_FALLBACK in both.port.quality_warnings
    assert (scan.WARN_NO_FLOOR in both.port.quality_warnings) is (both.name != "outlined_floor")


def test_proposals_floor_and_zones_match(both):
    assert _bytes(both.port_out / "all_zone_proposals.json") == _bytes(
        both.up_out / "all_zone_proposals.json"
    )
    assert _bytes(both.port_out / "floor_proposal_mask.png") == _bytes(
        both.up_out / "floor_proposal_mask.png"
    )
    assert both.port.zones == both.up["ZONES"]
    assert both.port.segmentation_method == both.up["segmentation_method"]
    assert both.port.segmentation_method == "edge-contour fallback"
    zones_json = json.loads((both.port_out / "zones.json").read_text())
    up_zones_json = json.loads((both.up_out / "zones.json").read_text())
    for key in ("method", "zones", "candidate_counts", "note"):
        assert zones_json[key] == up_zones_json[key]


def test_annotated_frames_match(both):
    frames = both.up["frames"]
    for i in sorted({0, len(frames) // 2, len(frames) - 1}):
        t = float(both.up["TIMES"][i])
        np.testing.assert_array_equal(
            scan.annotate(frames[i], both.port.zones, t), both.up["annotated"](frames[i], t)
        )
    assert _bytes(both.port_out / "zones_overview.jpg") == _bytes(
        both.up_out / "zones_overview.jpg"
    )


def test_evidence_is_byte_identical(both):
    assert both.port.evidence == both.up["evidence"]
    assert _bytes(both.port_out / "evidence_manifest.json") == _bytes(
        both.up_out / "evidence_manifest.json"
    )
    for item in both.port.evidence:
        assert scan.sha256_file(both.port_out / item["path"]) == item["sha256"]
        assert _bytes(both.port_out / item["path"]) == _bytes(both.up_out / item["path"])


def test_processed_video_has_every_frame(both):
    assert both.port.processed_video["frames"] == both.up["N"]
    assert both.port.processed_video["codec"] == "h264"
    assert both.port.processed_video["pix_fmt"] == "yuv420p"


def test_step_messages_match(both):
    assert both.up["steps"] == list(STEP_MESSAGES[:4])


def test_yolo_boxes_are_added_to_the_upstream_candidates(both):
    """With detector boxes, the upstream edge candidates survive unchanged, after the boxes."""
    up = both.up
    aw, ah = up["AW"], up["AH"]
    box = (aw * 0.55, ah * 0.58, aw * 0.62, ah * 0.70)
    detected = DetectResult(
        width=aw,
        height=ah,
        objects=[Detection(model="yolo11s", label="suitcase", conf=0.61, box=box)],
    )
    stage = scan.propose_static(
        up["BACKGROUND"], up["bg_gray"], up["MOTION_HEATMAP"], up["TIMES"], aw, ah, detected
    )
    yolo = [s for s in stage.sources if s != scan.EDGE_SOURCE]
    assert yolo == ["yolo11s: suitcase (0.61)"]
    # upstream's zone selection adds these keys to the chosen proposal dicts in place
    zone_keys = {"zone_id", "bbox_normalized", "bbox_source"}
    upstream_static = [
        {k: v for k, v in p.items() if k not in zone_keys} for p in up["static_proposals"]
    ]
    assert stage.proposals[len(yolo) :] == upstream_static
    assert stage.sources[len(yolo) :] == [scan.EDGE_SOURCE] * len(up["static_proposals"])
    np.testing.assert_array_equal(stage.floor_mask, up["floor_mask"])
    assert stage.edge_mask_count == len(up["region_masks"])
    assert stage.yolo_mask_count == 1
    assert scan.WARN_STATIC_FALLBACK not in stage.warnings

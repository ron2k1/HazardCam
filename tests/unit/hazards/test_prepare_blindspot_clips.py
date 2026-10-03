"""prepare_blindspot_clips: synchronised warehouse cuts in the hazard clip store.

Camera file names stay judge-only (labels/), titles are neutral, clip.json carries
kind/review_mode "blindspot", and the pipeline picks the blind-spot mode from it.
All media here is generated test media.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from hazards import pipeline, scan
from tests.unit.hazards._helpers import make_synthetic_video
from tests.unit.hazards.conftest import needs_ffmpeg

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "hazards_prepare_blindspot_clips",
    REPO_ROOT / "scripts" / "hazards" / "prepare_blindspot_clips.py",
)
assert _SPEC is not None and _SPEC.loader is not None
bs = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bs
_SPEC.loader.exec_module(bs)

HAZARD_CLIP_KEYS = ["clip_id", "title", "duration_s", "fps", "width", "height", "source_sha256"]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("3", "Camera_0003"),
        ("0014", "Camera_0014"),
        ("Camera_0005", "Camera_0005"),
        (" Camera_0019.mp4 ", "Camera_0019"),
    ],
)
def test_camera_names(entry, expected):
    assert bs.camera_name(entry) == expected


def test_bad_camera_names_are_rejected():
    with pytest.raises(SystemExit, match="unknown camera"):
        bs.camera_name("cam3")


def test_ground_truth_summary_counts_objects_and_view_changes():
    def obj(kind: str, oid: int, box: list[int] | None) -> dict:
        return {
            "object type": kind,
            "object id": oid,
            "2d bounding box visible": {"Camera_0003": box} if box else {},
        }

    big, tiny = [0, 0, 100, 100], [0, 0, 10, 10]
    truth = {
        "10": [obj("Person", 1, big), obj("Forklift", 7, big)],
        "11": [obj("Person", 1, big), obj("Forklift", 7, None), obj("Person", 2, tiny)],
        "12": [obj("Person", 1, big), obj("Person", 3, big)],
        "13": [obj("Person", 9, big)],  # outside the segment
    }
    summary = bs.ground_truth_summary(truth, "Camera_0003", 10, 3)
    assert summary["in_view"] == {"Forklift": 1, "Person": 2}
    assert summary["enter_or_leave_view_events"] == 2  # forklift leaves, person 3 enters
    assert bs.ground_truth_summary(None, "Camera_0003", 0, 3) is None


@pytest.fixture
def warehouse(tmp_path: Path) -> dict[str, Path]:
    """Two generated 30 fps 'cameras' on a fake drive; the local folder starts empty."""
    drive, local = tmp_path / "drive", tmp_path / "local"
    drive.mkdir()
    for n in (3, 5):
        make_synthetic_video(
            drive / f"Camera_{n:04d}.mp4", width=320, height=180, frames=60, fps=30.0, square=24
        )
    return {"drive": drive, "local": local, "data": tmp_path / "data"}


def _main(warehouse: dict[str, Path], *extra: str) -> int:
    return bs.main(
        [
            "--cameras",
            "3,5",
            "--start",
            "0.5",
            "--duration",
            "1.0",
            "--data-dir",
            str(warehouse["data"]),
            "--local-dir",
            str(warehouse["local"]),
            "--drive-dir",
            str(warehouse["drive"]),
            "--no-ground-truth",
            *extra,
        ]
    )


@needs_ffmpeg
def test_stages_synchronised_blindspot_clips(warehouse):
    assert _main(warehouse) == 0
    data = warehouse["data"]
    # sources were copied off the drive first
    assert (warehouse["local"] / "Camera_0003.mp4").read_bytes() == (
        warehouse["drive"] / "Camera_0003.mp4"
    ).read_bytes()
    for n, camera in ((1, "Camera_0003"), (2, "Camera_0005")):
        clip_id = f"bs_{n:02d}"
        clip_text = (data / "clips" / clip_id / "clip.json").read_text()
        clip = json.loads(clip_text)
        assert list(clip) == [*HAZARD_CLIP_KEYS, "kind", "review_mode"]
        assert clip["clip_id"] == clip_id and clip["title"] == f"Aisle camera {n}"
        assert clip["kind"] == "blindspot" and clip["review_mode"] == "blindspot"
        assert (clip["fps"], clip["width"], clip["height"]) == (30.0, 320, 180)
        assert clip["duration_s"] == 1.0
        assert "Camera" not in clip_text and "Warehouse" not in clip_text
        source = data / "clips" / clip_id / "source.mp4"
        assert scan.sha256_file(source) == clip["source_sha256"]
        probe = scan.probe_video(source)
        assert (probe["codec"], probe["pix_fmt"], probe["frames"]) == ("h264", "yuv420p", 30)
        assert source.read_bytes()[4:8] == b"ftyp"
        assert b"moov" in source.read_bytes()[:4096]  # +faststart: moov before mdat
        label = json.loads((data / "labels" / f"{clip_id}.json").read_text())
        assert label["original_name"] == f"{camera}.mp4"
        assert label["source_sha256"] == clip["source_sha256"]
        assert label["segment"]["start_frame"] == 15 and label["segment"]["frames"] == 30
        assert label["segment"]["sync_group"] == "warehouse_000_t0.5"
        assert label["ground_truth"] is None
        assert pipeline.resolve_review_mode(source) == "blindspot"


@needs_ffmpeg
def test_restaging_the_same_segment_is_a_no_op(warehouse, capsys):
    assert _main(warehouse) == 0
    first = json.loads((warehouse["data"] / "clips" / "bs_01" / "clip.json").read_text())
    assert _main(warehouse) == 0
    assert "already holds 30 frames" in capsys.readouterr().out
    again = json.loads((warehouse["data"] / "clips" / "bs_01" / "clip.json").read_text())
    assert again == first


@needs_ffmpeg
def test_a_different_segment_needs_force(warehouse):
    assert _main(warehouse) == 0
    stale = warehouse["data"] / "reports" / "bs_01" / "run"
    stale.mkdir(parents=True)
    with pytest.raises(SystemExit, match="--force"):
        bs.main(
            [
                "--cameras",
                "3",
                "--start",
                "0.2",
                "--duration",
                "1.0",
                "--data-dir",
                str(warehouse["data"]),
                "--local-dir",
                str(warehouse["local"]),
                "--drive-dir",
                str(warehouse["drive"]),
                "--no-ground-truth",
            ]
        )
    assert stale.is_dir()
    assert not list((warehouse["data"] / "clips" / "bs_01").glob("*.next.mp4"))


def test_missing_cameras_are_reported(tmp_path):
    with pytest.raises(SystemExit, match="neither"):
        bs.ensure_local("Camera_0001", tmp_path / "local", tmp_path / "drive")

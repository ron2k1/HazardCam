"""prepare_clips: neutral ids, judge-only labels, clean-decode selection, example import.

The labels and original file names must never reach clip.json, the review pipeline or
the model request.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from hazards import pipeline, review, scan
from hazards.detector.client import DetectorClient
from tests.unit.hazards._helpers import (
    StubVLLM,
    make_synthetic_video,
    moving_square_frames,
    scene_background,
    unreachable_transport,
    write_video,
)
from tests.unit.hazards.conftest import gb10_like_endpoint, needs_ffmpeg

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "hazards_prepare_clips", REPO_ROOT / "scripts" / "hazards" / "prepare_clips.py"
)
assert _SPEC is not None and _SPEC.loader is not None
prepare_clips = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = prepare_clips  # dataclasses resolve their module here
_SPEC.loader.exec_module(prepare_clips)

pytestmark = needs_ffmpeg

LABELS = ("0_safe_walkway_violation", "2_unauthorized_intervention", "10_opened_panel_cover")
# Label fragments and file stems. Each holds "_" or ".", which base64 image data never does,
# and none occurs in the prompts (single words such as "panel" or "violation" do).
LEAKS = (
    "safe_walkway",
    "walkway_violation",
    "unauthorized_intervention",
    "opened_panel",
    "panel_cover",
    "_te1",
    "_te2",
    "_te10",
    "te1.mp4",
)


def _clip(path: Path, seed: int) -> Path:
    """Small clips with distinct bytes (per-clip brightness offset), 12 frames at 8 fps."""
    background = cv2.add(scene_background(160, 120), np.full((120, 160, 3), seed, np.uint8))
    return write_video(path, moving_square_frames(background, 12, square=12), 8)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dataset")
    split = root / "test"
    a, b, c = (split / name for name in LABELS)
    _clip(a / "0_te10.mp4", 1)
    _clip(a / "0_te2.mp4", 2)
    _clip(a / "0_te1.mp4", 3)
    _clip(a / "._0_te0.mp4", 4)  # a valid video hidden as a macOS resource fork
    b.mkdir(parents=True)
    (b / "2_te1.mp4").write_bytes(b"\x00corrupt" * 512)  # does not decode
    _clip(b / "2_te2.mp4", 5)
    _clip(c / "10_te1.mp4", 6)
    (split / "._10_hidden").mkdir()
    _clip(split / "._10_hidden" / "x.mp4", 7)
    _clip(root / "train" / LABELS[0] / "0_tr1.mp4", 8)
    return root


def test_natural_sort_and_hidden_files():
    names = ["0_te10.mp4", "0_te2.mp4", "0_te1.mp4"]
    assert sorted(names, key=prepare_clips.natural_key) == ["0_te1.mp4", "0_te2.mp4", "0_te10.mp4"]
    assert not prepare_clips.visible(Path("._0_te1.mp4"))
    assert prepare_clips.visible(Path("0_te1.mp4"))


def test_selection_takes_the_first_clean_clip_per_label(dataset: Path):
    chosen = prepare_clips.select_dataset_clips(dataset, "test", 1)
    assert [(label, path.name) for label, path in chosen] == [
        ("0_safe_walkway_violation", "0_te1.mp4"),
        ("2_unauthorized_intervention", "2_te2.mp4"),  # 2_te1 is corrupt
        ("10_opened_panel_cover", "10_te1.mp4"),
    ]
    two = prepare_clips.select_dataset_clips(dataset, "test", 2)
    assert [p.name for label, p in two if label == LABELS[0]] == ["0_te1.mp4", "0_te2.mp4"]


def test_probe_clip(dataset: Path):
    info = prepare_clips.probe_clip(dataset / "test" / LABELS[0] / "0_te1.mp4")
    assert info == prepare_clips.ClipInfo(1.5, 8.0, 160, 120, 12)
    assert prepare_clips.probe_clip(dataset / "test" / LABELS[1] / "2_te1.mp4") is None


def test_ids_are_a_seeded_shuffle():
    ids = prepare_clips.assign_ids(8, prepare_clips.DEFAULT_SEED)
    assert sorted(ids) == list(range(1, 9))
    assert ids == prepare_clips.assign_ids(8, prepare_clips.DEFAULT_SEED)
    assert ids != list(range(1, 9))


@pytest.fixture(scope="module")
def staged(dataset: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("staged") / "hazards"
    assert prepare_clips.main(["--dataset", str(dataset), "--out", str(out), "--seed", "7"]) == 0
    return out


def test_clip_json_is_neutral(staged: Path):
    clip_dirs = sorted((staged / "clips").iterdir())
    shas = {scan.sha256_file(d / "source.mp4") for d in clip_dirs}
    assert len(shas) == len(clip_dirs) == 3  # distinct test videos
    numbers = prepare_clips.assign_ids(3, 7)
    assert [d.name for d in clip_dirs] == sorted(f"hz_{n:02d}" for n in numbers)
    for clip_dir in clip_dirs:
        assert sorted(p.name for p in clip_dir.iterdir()) == ["clip.json", "source.mp4"]
        text = (clip_dir / "clip.json").read_text()
        clip = json.loads(text)
        assert list(clip) == [
            "clip_id",
            "title",
            "duration_s",
            "fps",
            "width",
            "height",
            "source_sha256",
        ]
        assert clip["clip_id"] == clip_dir.name
        assert clip["title"] == f"Floor camera {clip_dir.name[3:]}"
        assert clip["source_sha256"] == scan.sha256_file(clip_dir / "source.mp4")
        assert (clip["width"], clip["height"], clip["fps"]) == (160, 120, 8.0)
        assert clip["duration_s"] == 1.5
        for leak in LEAKS:
            assert leak not in text


def test_labels_are_judge_only_files(staged: Path, dataset: Path):
    chosen = prepare_clips.select_dataset_clips(dataset, "test", 1)
    numbers = prepare_clips.assign_ids(len(chosen), 7)
    for (label, path), number in zip(chosen, numbers, strict=True):
        clip_id = f"hz_{number:02d}"
        stored = json.loads((staged / "labels" / f"{clip_id}.json").read_text())
        assert stored == {
            "dataset_label": label,
            "dataset_split": "test",
            "original_name": path.name,
            "source_sha256": scan.sha256_file(path),
        }
        assert stored["source_sha256"] == scan.sha256_file(
            staged / "clips" / clip_id / "source.mp4"
        )


def test_restaging_is_idempotent(staged: Path, dataset: Path):
    before = {p: p.read_bytes() for p in staged.rglob("*.json")}
    assert prepare_clips.main(["--dataset", str(dataset), "--out", str(staged), "--seed", "7"]) == 0
    assert {p: p.read_bytes() for p in staged.rglob("*.json")} == before


def test_the_model_request_never_sees_labels_or_names(staged: Path, tmp_path: Path):
    for clip_dir in sorted((staged / "clips").iterdir()):
        clip_id = clip_dir.name
        stub = StubVLLM()
        run_dir = pipeline.review_clip(
            clip_dir / "source.mp4",
            tmp_path / "reports" / clip_id,
            source_name=clip_id,
            detector=DetectorClient(transport=unreachable_transport()),
            reviewer=review.HazardReviewer(
                gb10_like_endpoint(), profile_name="gb10", transport=stub.transport, env={}
            ),
        )
        assert stub.chat_payloads, "the stub model was not called"
        label = json.loads((staged / "labels" / f"{clip_id}.json").read_text())
        forbidden = [*LEAKS, label["dataset_label"], label["original_name"]]
        forbidden.append(Path(label["original_name"]).stem)
        for payload in stub.chat_payloads:
            text = json.dumps(payload)
            assert clip_id in text
            for leak in forbidden:
                assert leak not in text, leak
        for path in run_dir.rglob("*.json"):
            text = path.read_text()
            for leak in forbidden:
                assert leak not in text, (path.name, leak)


def test_a_clip_id_keeps_its_video_unless_forced(staged: Path, tmp_path: Path):
    data = tmp_path / "data"
    shutil.copytree(staged, data)
    clip_id = min(p.name for p in (data / "clips").iterdir())
    (data / "reports" / clip_id / "abc").mkdir(parents=True)
    other = _clip(tmp_path / "other.mp4", 30)
    info = prepare_clips.probe_clip(other)
    label = {"dataset_label": "x", "dataset_split": "test", "original_name": "other.mp4"}
    with pytest.raises(SystemExit, match="already holds a different video"):
        prepare_clips.write_clip(data, clip_id, "t", other, info, label, force=False)
    prepare_clips.write_clip(data, clip_id, "t", other, info, label, force=True)
    assert not (data / "reports" / clip_id).exists()
    assert scan.sha256_file(data / "clips" / clip_id / "source.mp4") == scan.sha256_file(other)


def test_labels_narrow_the_selection_by_name_or_index(dataset: Path):
    chosen = prepare_clips.select_dataset_clips(dataset, "test", 1, ["10", LABELS[0]])
    assert [(label, path.name) for label, path in chosen] == [
        ("0_safe_walkway_violation", "0_te1.mp4"),
        ("10_opened_panel_cover", "10_te1.mp4"),
    ]
    # index "1" is not a prefix match for "10_..." and an unknown entry is an error
    with pytest.raises(SystemExit, match="unknown label '1'"):
        prepare_clips.select_dataset_clips(dataset, "test", 1, ["1"])
    assert prepare_clips.select_dataset_clips(dataset, "test", 1, None) == (
        prepare_clips.select_dataset_clips(dataset, "test", 1)
    )


def test_labels_and_prune_restage_a_smaller_set(staged: Path, dataset: Path, tmp_path: Path):
    data = tmp_path / "data"
    shutil.copytree(staged, data)
    (data / "clips" / "hz_00").mkdir()  # the original example slot is never pruned
    (data / "reports" / "hz_00").mkdir(parents=True)
    argv = ["--dataset", str(dataset), "--out", str(data), "--seed", "7", "--labels", "0,10"]
    with pytest.raises(SystemExit, match="already holds a different video"):
        prepare_clips.main(argv + ["--prune"])  # ids 1..2 would get other videos
    assert prepare_clips.main(argv + ["--prune", "--force"]) == 0
    assert sorted(p.name for p in (data / "clips").iterdir()) == ["hz_00", "hz_01", "hz_02"]
    assert sorted(p.name for p in (data / "labels").iterdir()) == ["hz_01.json", "hz_02.json"]
    assert (data / "reports" / "hz_00").is_dir()
    stored = {
        json.loads((data / "labels" / f"hz_{n:02d}.json").read_text())["dataset_label"]
        for n in (1, 2)
    }
    assert stored == {LABELS[0], LABELS[2]}


def test_missing_split_is_reported(tmp_path: Path):
    with pytest.raises(SystemExit, match="dataset split not found"):
        prepare_clips.select_dataset_clips(tmp_path, "test", 1)


# --- original example import ----------------------------------------------------------------


@pytest.fixture(scope="module")
def fake_example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An example_output/ shaped like the original one, built from a stub-model run."""
    root = tmp_path_factory.mktemp("example")
    video = make_synthetic_video(root / "safety_hazard" / prepare_clips.EXAMPLE_VIDEO)
    stub = StubVLLM()
    run_dir = pipeline.review_clip(
        video,
        root / "runs",
        source_name="hz_77",
        detector=DetectorClient(transport=unreachable_transport()),
        reviewer=review.HazardReviewer(gb10_like_endpoint(), transport=stub.transport, env={}),
    )
    example_out = root / "safety_hazard" / "example_output"
    shutil.copytree(run_dir, example_out)
    report = json.loads((example_out / "hazard_report.json").read_text())
    report["video"]["source_name"] = prepare_clips.EXAMPLE_VIDEO  # what upstream wrote
    report["artifacts"]["processed_video"] = "4_tr1_processed.mp4"
    (example_out / "processed.mp4").rename(example_out / "4_tr1_processed.mp4")
    del report["pipeline"], report["instructions"]
    scan.save_json(example_out / "hazard_report.json", report)
    manifest = json.loads((example_out / "run_manifest.json").read_text())
    manifest["source"]["source_name"] = prepare_clips.EXAMPLE_VIDEO
    scan.save_json(example_out / "run_manifest.json", manifest)
    return root / "safety_hazard"


def test_import_example_as_hz_00(fake_example: Path, tmp_path: Path):
    data = tmp_path / "hazards"
    run_dir = prepare_clips.import_example(fake_example, data, force=False)
    manifest_src = json.loads((fake_example / "example_output" / "run_manifest.json").read_text())
    assert run_dir == data / "reports" / "hz_00" / prepare_clips.upstream_run_id(manifest_src)

    clip = json.loads((data / "clips" / "hz_00" / "clip.json").read_text())
    assert clip["clip_id"] == "hz_00" and clip["title"] == "Press line camera"
    label = json.loads((data / "labels" / "hz_00.json").read_text())
    assert {k: label[k] for k in prepare_clips.EXAMPLE_LABEL} == prepare_clips.EXAMPLE_LABEL

    rep = json.loads((run_dir / "hazard_report.json").read_text())
    assert rep["video"]["source_name"] == "hz_00"
    assert rep["model"]["inference_source"] == "original run (Ollama, macOS)"
    assert rep["artifacts"]["processed_video"] == "processed.mp4"
    assert rep["instructions"]["system_prompt"] == review.SYSTEM_PROMPT
    assert rep["pipeline"]["version"] == "astra-1.1" and rep["pipeline"]["imported"] is True
    assert rep["pipeline"]["processed_video"]["codec"] == "h264"
    assert rep["pipeline"]["processed_video"]["frames"] == 40
    for e in rep["evidence"]:
        assert scan.sha256_file(run_dir / e["path"]) == e["sha256"]
    for name in ("zones_overview.jpg", "zones.json", "evidence_manifest.json", "processed.mp4"):
        assert (run_dir / name).is_file()
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["source"]["source_name"] == "hz_00" and manifest["imported"]
    progress = json.loads((run_dir / "progress.json").read_text())
    assert [p["message"] for p in progress] == list(pipeline.STEP_MESSAGES)
    latest = json.loads((data / "reports" / "hz_00" / "latest_run.json").read_text())
    assert latest["run_id"] == run_dir.name and latest["status"] == rep["status"]
    for path in [*run_dir.glob("*.json"), data / "clips" / "hz_00" / "clip.json"]:
        assert "4_tr1" not in path.read_text(), path.name


def test_import_example_rejects_a_mismatched_report(fake_example: Path, tmp_path: Path):
    bad = tmp_path / "bad"
    shutil.copytree(fake_example, bad)
    report_path = bad / "example_output" / "hazard_report.json"
    report = json.loads(report_path.read_text())
    report["video"]["source_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report))
    with pytest.raises(SystemExit, match="does not belong to the example video"):
        prepare_clips.import_example(bad, tmp_path / "data", force=False)


def test_import_example_rejects_tampered_evidence(fake_example: Path, tmp_path: Path):
    bad = tmp_path / "bad"
    shutil.copytree(fake_example, bad)
    (bad / "example_output" / "evidence" / "E001.jpg").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="evidence E001 hash differs"):
        prepare_clips.import_example(bad, tmp_path / "data", force=False)


def test_script_steps_are_the_pipeline_steps():
    assert prepare_clips.SCRIPT_STEPS == pipeline.STEP_MESSAGES

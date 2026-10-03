"""End to end on a generated clip: review_clip writes the upstream artifacts and reports."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from hazards import pipeline, report, review, scan
from hazards.detector.client import DetectorClient
from tests.unit.hazards._helpers import StubDetector, StubVLLM, unreachable_transport
from tests.unit.hazards.conftest import gb10_like_endpoint, needs_ffmpeg

pytestmark = needs_ffmpeg

CV_ARTIFACTS = [
    "video_metadata.json",
    "motion_data.npz",
    "motion_timeline.csv",
    "motion_heatmap.png",
    "floor_proposal_mask.png",
    "all_zone_proposals.json",
    "zones.csv",
    "zones.json",
    "processed.mp4",
    "zones_overview.jpg",
    "evidence_manifest.json",
    "hazard_report.json",
    "hazard_report.csv",
    "hazard_report.md",
    "hazard_report.html",
    "run_manifest.json",
    "progress.json",
]


def _top_level_boxes(path: Path) -> list[str]:
    boxes, data, offset = [], path.read_bytes(), 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[offset : offset + 8])
        if size == 1:
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
        boxes.append(kind.decode("latin-1"))
        if size < 8:
            break
        offset += size
    return boxes


@pytest.fixture(scope="module")
def skip_model_run(tmp_path_factory: pytest.TempPathFactory, synthetic_video: Path):
    output_root = tmp_path_factory.mktemp("reports") / "hz_99"
    calls: list[tuple[int, int, str]] = []
    run_dir = pipeline.review_clip(
        synthetic_video,
        output_root,
        source_name="hz_99",
        skip_model=True,
        detector=DetectorClient(transport=unreachable_transport()),
        progress=lambda step, total, message: calls.append((step, total, message)),
    )
    return run_dir, output_root, calls


def test_skip_model_run_writes_every_artifact(skip_model_run, synthetic_video):
    run_dir, output_root, _ = skip_model_run
    source_sha = scan.sha256_file(synthetic_video)
    assert run_dir == output_root / pipeline.compute_run_id(source_sha, None)
    for name in CV_ARTIFACTS:
        assert (run_dir / name).stat().st_size > 0, name
    assert not list(run_dir.glob("*.cv2.*"))  # the lossless intermediate is removed
    latest = json.loads((output_root / "latest_run.json").read_text())
    assert latest["run_id"] == run_dir.name and latest["status"] == "preprocessing_only"


def test_report_shape_without_a_model(skip_model_run):
    run_dir, _, _ = skip_model_run
    rep = json.loads((run_dir / "hazard_report.json").read_text())
    assert rep["status"] == review.STATUS_PREPROCESSING and rep["findings"] == []
    assert rep["scene_summary"] == report.NO_REVIEW_SUMMARY and rep["model"] == {}
    assert rep["video"]["source_name"] == "hz_99"
    assert rep["video"]["decoded_frames"] == 40 and rep["video"]["fps"] == 10.0
    assert rep["segmentation_method"] == "edge-contour fallback"
    assert rep["segmentation_weights_sha256"] is None
    assert rep["artifacts"]["processed_video"] == "processed.mp4"
    assert rep["limitations"][: len(report.LIMITATIONS)] == report.LIMITATIONS
    assert scan.WARN_STATIC_FALLBACK in rep["pipeline"]["quality_warnings"]
    assert rep["pipeline"]["version"] == "astra-1.1-gb10"
    assert rep["pipeline"]["ported_from_sha256"] == scan.UPSTREAM_SHA256
    assert rep["pipeline"]["detector"]["status"] == "unreachable"
    assert rep["instructions"]["system_prompt"] == review.HAZARD_MODE.system_prompt
    assert rep["config"] == scan.CFG
    zone_ids = [z["zone_id"] for z in rep["zones"]]
    assert zone_ids == [f"Z{i:02d}" for i in range(1, len(zone_ids) + 1)]
    assert set(rep["pipeline"]["zone_sources"]) == set(zone_ids)
    assert any(z["kind"] == "movement" for z in rep["zones"])  # the moving square


def test_evidence_ids_hashes_and_timestamps(skip_model_run):
    run_dir, _, _ = skip_model_run
    evidence = json.loads((run_dir / "evidence_manifest.json").read_text())
    assert [e["evidence_id"] for e in evidence] == [
        f"E{i:03d}" for i in range(1, len(evidence) + 1)
    ]
    assert len(evidence) <= scan.CFG["max_total_images"]
    for e in evidence:
        assert e["path"] == f"evidence/{e['evidence_id']}.jpg"
        assert scan.sha256_file(run_dir / e["path"]) == e["sha256"]
        assert e["timestamp_s"] == e["frame_index"] / 10.0
        assert e["kind"] in (scan.EVIDENCE_FULL, scan.EVIDENCE_ZONE, scan.EVIDENCE_TILE)
        assert (e["zone_id"] is not None) is (e["kind"] == scan.EVIDENCE_ZONE)
    assert sorted(p.name for p in (run_dir / "evidence").iterdir()) == [
        f"{e['evidence_id']}.jpg" for e in evidence
    ]
    tiles = [e for e in evidence if e["kind"] == scan.EVIDENCE_TILE]
    assert len(tiles) == 4 and {e["frame_index"] for e in tiles} == {20}


def test_processed_video_is_browser_h264(skip_model_run):
    run_dir, _, _ = skip_model_run
    video = run_dir / "processed.mp4"
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,nb_read_frames,r_frame_rate",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
    assert int(stream["nb_read_frames"]) == 40
    assert (stream["width"], stream["height"]) == (768, 432 + scan.BANNER_PX)
    assert stream["r_frame_rate"] == "10/1"
    boxes = _top_level_boxes(video)
    assert boxes.index("moov") < boxes.index("mdat")  # +faststart
    rep = json.loads((run_dir / "hazard_report.json").read_text())
    assert rep["pipeline"]["processed_video"]["frames"] == 40


def test_progress_messages_and_file(skip_model_run):
    run_dir, _, calls = skip_model_run
    expected = [(i, 6, m) for i, m in enumerate(pipeline.STEP_MESSAGES, 1)]
    assert calls == expected
    stored = json.loads((run_dir / "progress.json").read_text())
    assert stored == [{"step": s, "total": t, "message": m} for s, t, m in expected]


def test_manifest_and_no_file_name_leak(skip_model_run):
    run_dir, _, _ = skip_model_run
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "preprocessing_only" and manifest["run_id"] == run_dir.name
    assert manifest["weights_sha256"] is None
    assert manifest["pipeline_version"] == "astra-1.1-gb10"
    assert "objects" not in manifest["detector"]
    assert set(manifest["timings_s"]) == {"scan", "review", "total"}
    for path in run_dir.glob("*.json"):
        assert "source.mp4" not in path.read_text(), path.name


def test_motion_npz_matches_the_report(skip_model_run):
    run_dir, _, _ = skip_model_run
    data = np.load(run_dir / "motion_data.npz")
    assert data["heatmap"].shape == (432, 768)
    np.testing.assert_array_equal(data["frame_times_s"], np.arange(40) / 10.0)


# --- with the local detector and a stub vLLM ------------------------------------------------


def test_detector_and_model_run_end_to_end(tmp_path, synthetic_video):
    stub_det = StubDetector(
        objects=[
            {"model": "yolo11s", "label": "suitcase", "conf": 0.61, "box": [420, 250, 470, 300]}
        ]
    ).start()
    stub_llm = StubVLLM()
    reviewer = review.HazardReviewer(
        gb10_like_endpoint(), profile_name="gb10", transport=stub_llm.transport, env={}
    )
    output_root = tmp_path / "hz_99"
    try:
        run_dir = pipeline.review_clip(
            synthetic_video,
            output_root,
            source_name="hz_99",
            detector=DetectorClient(stub_det.url),
            reviewer=reviewer,
        )
    finally:
        stub_det.stop()
    rep = json.loads((run_dir / "hazard_report.json").read_text())
    assert rep["status"] == review.STATUS_COMPLETE and rep["model_error"] is None
    assert rep["segmentation_method"] == (
        "local YOLO11s boxes on the temporal background + edge contours"
    )
    assert rep["segmentation_weights_sha256"] == {"yolo11s": stub_det.models["yolo11s"]}
    assert scan.WARN_STATIC_FALLBACK not in rep["pipeline"]["quality_warnings"]
    assert (
        rep["model"]["prompt_tokens"] == 1234 and rep["model"]["audit"]["completion_tokens"] == 321
    )
    assert rep["model"]["profile"] == "gb10" and rep["pipeline"]["profile"] == "gb10"
    assert rep["pipeline"]["images_sent"] == len(rep["evidence"])
    zones_json = json.loads((run_dir / "zones.json").read_text())
    assert zones_json["region_masks"]["yolo_boxes"] == 1
    assert zones_json["detector"]["objects"][0]["label"] == "suitcase"
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["weights_sha256"] == {"yolo11s": stub_det.models["yolo11s"]}
    source_sha = scan.sha256_file(synthetic_video)
    assert run_dir.name == pipeline.compute_run_id(source_sha, manifest["weights_sha256"])
    assert run_dir.name != pipeline.compute_run_id(source_sha, None)
    for f in rep["findings"]:
        assert f["finding_id"].startswith("H") and f["standard_links"]
        assert f["first_observed_s"] <= f["last_observed_s"]
    assert len(stub_llm.chat_payloads) == 2
    payload_text = json.dumps(stub_llm.chat_payloads[0])
    assert "source.mp4" not in payload_text and "hz_99" in payload_text

    # same clip, same detector weights: the review comes from the sha256 cache
    stub_det2 = StubDetector(objects=stub_det.objects).start()
    again = StubVLLM()
    try:
        run_dir2 = pipeline.review_clip(
            synthetic_video,
            output_root,
            source_name="hz_99",
            detector=DetectorClient(stub_det2.url),
            reviewer=review.HazardReviewer(
                gb10_like_endpoint(), profile_name="gb10", transport=again.transport, env={}
            ),
        )
    finally:
        stub_det2.stop()
    rep2 = json.loads((run_dir2 / "hazard_report.json").read_text())
    assert run_dir2 == run_dir and again.chat_payloads == []
    assert rep2["model"]["inference_source"] == "cache" and rep2["model"]["audit_source"] == "cache"


def test_model_failure_still_writes_the_report(tmp_path, synthetic_video):
    stub_llm = StubVLLM(status=400)
    run_dir = pipeline.review_clip(
        synthetic_video,
        tmp_path / "hz_99",
        source_name="hz_99",
        detector=DetectorClient(transport=unreachable_transport()),
        reviewer=review.HazardReviewer(gb10_like_endpoint(), transport=stub_llm.transport, env={}),
    )
    rep = json.loads((run_dir / "hazard_report.json").read_text())
    assert rep["status"] == review.STATUS_FAILED and "HTTP 400" in rep["model_error"]
    assert rep["findings"] == [] and rep["scene_summary"] == report.NO_REVIEW_SUMMARY
    latest = json.loads((tmp_path / "hz_99" / "latest_run.json").read_text())
    assert latest["status"] == review.STATUS_FAILED


def test_fixture_profile_is_refused_before_scanning(tmp_path, synthetic_video):
    with pytest.raises(ValueError, match="no model endpoint"):
        pipeline.review_clip(
            synthetic_video, tmp_path / "hz_99", source_name="hz_99", profile="fixture", env={}
        )
    assert not (tmp_path / "hz_99").exists()


@pytest.mark.parametrize("name", ["4_tr1.mp4", "../hz_01", "", "hz 01", "_hz", "x" * 65])
def test_source_name_must_be_a_neutral_id(tmp_path, synthetic_video, name):
    with pytest.raises(ValueError, match="neutral clip id"):
        pipeline.check_source_name(name, synthetic_video)


def test_source_name_must_not_be_the_file_stem(tmp_path):
    with pytest.raises(ValueError, match="must not be the video's file name"):
        pipeline.check_source_name("4_tr1", tmp_path / "4_tr1.mp4")
    assert pipeline.check_source_name("hz_00", tmp_path / "4_tr1.mp4") == "hz_00"
    assert pipeline.check_source_name("source", tmp_path / "source.mp4") == "source"


def test_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError, match="Missing input video: nope.mp4"):
        pipeline.review_clip(tmp_path / "nope.mp4", tmp_path, source_name="hz_01", skip_model=True)


def _load_cli():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "hazards_review_clip_cli",
        Path(__file__).resolve().parents[3] / "scripts/hazards/review_clip.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_review_clip_cli_skip_model(tmp_path, synthetic_video, monkeypatch, capsys):
    cli = _load_cli()
    monkeypatch.setenv("HAZARDS_DETECTOR_URL", "http://127.0.0.1:9")  # refused: fallback path
    code = cli.main(
        [
            "--video",
            str(synthetic_video),
            "--output-dir",
            str(tmp_path / "out"),
            "--source-name",
            "hz_99",
            "--skip-model",
        ]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "[1/6] Scanning video frames..." in printed and "[6/6]" in printed
    assert "Status:   preprocessing_only" in printed
    assert "Video:    hz_99 | 4.00s | 40 frames" in printed
    assert "Segments: edge-contour fallback" in printed


def test_review_clip_cli_needs_a_clip_or_video(monkeypatch):
    cli = _load_cli()
    with pytest.raises(SystemExit):
        cli.parse_args([])
    with pytest.raises(SystemExit):
        cli.parse_args(["--video", "x.mp4"])
    args = cli.parse_args(["hz_01", "--profile", "gb10"])
    assert args.clip_id == "hz_01" and args.profile == "gb10"

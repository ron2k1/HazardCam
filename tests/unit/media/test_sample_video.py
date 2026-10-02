"""P04: sample_video writes exactly the planned frames, with exact and deterministic seek
metadata. "Right frame" is proven from pixels: every generated source frame n carries the
binary code n (see conftest), so a JPEG's code must equal its manifest frame_id."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import pytest

from apps.api.schemas import REPO_ROOT, MediaManifest, validate_json
from tools.media.binaries import MediaToolError, ffprobe_bin, run_tool
from tools.media.extract import extract_frames
from tools.sample_video import main, manifest_json, portable_path, sample_video


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file(rel: str | None) -> Path:
    assert rel is not None
    return REPO_ROOT / rel  # repo-relative or absolute POSIX; both resolve this way


def _codes(manifest: MediaManifest, read_code) -> list[int]:
    return [read_code(_file(f.path)) for f in manifest.frames]


def _assert_frame_aligned(manifest: MediaManifest, fps: Fraction) -> None:
    assert [f.index for f in manifest.frames] == list(range(len(manifest.frames)))
    for f in manifest.frames:
        assert f.t == float(Fraction(f.frame_id) / fps)


def _clip_gray_frames(clip: Path) -> list[np.ndarray]:
    """Decode every clip frame with OpenCV (an independent decoder from the ffmpeg CLI)."""
    cap = cv2.VideoCapture(str(clip))
    frames = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    cap.release()
    return frames


def _ffprobe_streams(path: Path) -> list[dict]:
    out = run_tool(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,pix_fmt,nb_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        what="ffprobe clip",
    ).stdout
    return json.loads(out)["streams"]


def _top_level_atoms(path: Path) -> list[str]:
    data, pos, atoms = path.read_bytes(), 0, []
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        if size == 1:
            size = int.from_bytes(data[pos + 8 : pos + 16], "big")
        elif size == 0:
            size = len(data) - pos
        atoms.append(data[pos + 4 : pos + 8].decode("latin-1"))
        pos += size
    return atoms


# --- right frames, right timestamps ------------------------------------------------------


@pytest.mark.media
@pytest.mark.parametrize(
    ("fps", "expected"),
    [
        # candidates k/3 s -> frame floor(fps * k / 3)
        (10, [0, 3, 6, 10, 13, 16, 20, 23, 26, 30, 33, 36]),
        (25, [0, 8, 16, 25, 33, 41, 50, 58, 66, 75, 83, 91]),
    ],
)
def test_jpegs_are_the_planned_source_frames(make_cfr, read_code, tmp_path, fps, expected):
    m = sample_video(make_cfr(fps, 4.0), "cam_01", out_dir=tmp_path, sample_fps=3.0, max_frames=50)
    assert [f.frame_id for f in m.frames] == expected
    assert _codes(m, read_code) == expected
    _assert_frame_aligned(m, Fraction(fps))
    assert (m.src_fps, m.duration_s, m.width, m.height) == (float(fps), 4.0, 320, 240)


@pytest.mark.media
@pytest.mark.parametrize("fps", [10, 25])
def test_every_frame_when_sampling_at_source_rate(make_cfr, read_code, tmp_path, fps):
    m = sample_video(
        make_cfr(fps, 4.0), "cam_01", out_dir=tmp_path, sample_fps=float(fps), max_frames=1000
    )
    assert [f.frame_id for f in m.frames] == list(range(4 * fps))
    assert _codes(m, read_code) == list(range(4 * fps))  # includes the very last frame


@pytest.mark.media
def test_max_frames_spread_over_video(make_cfr, read_code, tmp_path):
    # 20 candidates at 5 Hz, keep 6: positions round_half_up(j * 19 / 5) = 0,4,8,11,15,19.
    m = sample_video(make_cfr(25, 4.0), "cam_01", out_dir=tmp_path, sample_fps=5.0, max_frames=6)
    assert [f.frame_id for f in m.frames] == [0, 20, 40, 55, 75, 95]
    assert _codes(m, read_code) == [0, 20, 40, 55, 75, 95]


@pytest.mark.media
def test_short_video_yields_fewer_than_max_frames(make_cfr, tmp_path):
    m = sample_video(make_cfr(10, 4.0), "cam_01", out_dir=tmp_path, max_frames=8)
    assert [f.frame_id for f in m.frames] == [0, 10, 20, 30]
    assert sorted(p.name for p in (tmp_path / "cam_01").iterdir()) == [
        "0000.jpg",
        "0001.jpg",
        "0002.jpg",
        "0003.jpg",
    ]


@pytest.mark.media
def test_start_end_window(make_cfr, read_code, tmp_path):
    m = sample_video(
        make_cfr(10, 4.0), "cam_01", out_dir=tmp_path, sample_fps=2.0, start_s=1.25, end_s=3.0
    )
    assert [f.frame_id for f in m.frames] == [12, 17, 22, 27]
    assert [f.t for f in m.frames] == [1.2, 1.7, 2.2, 2.7]
    assert _codes(m, read_code) == [12, 17, 22, 27]
    assert (m.start_s, m.end_s) == (1.25, 3.0)


@pytest.mark.media
def test_end_past_video_is_clamped(make_cfr, tmp_path):
    m = sample_video(make_cfr(10, 4.0), "cam_01", out_dir=tmp_path, end_s=100.0)
    assert m.end_s == 4.0
    assert [f.frame_id for f in m.frames] == [0, 10, 20, 30]


@pytest.mark.media
@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"start_s": 4.0}, "at or past the end"),
        ({"start_s": 30.0}, "at or past the end"),
        ({"start_s": -1.0}, "start_s must be >= 0"),
        ({"start_s": 2.0, "end_s": 1.5}, "empty window"),
        ({"start_s": 2.0, "end_s": 2.0}, "empty window"),
        ({"sample_fps": 0.0}, "sample_fps must be > 0"),
        ({"max_frames": 0}, "max_frames must be >= 1"),
    ],
)
def test_out_of_range_and_empty_windows_raise(make_cfr, tmp_path, kw, match):
    with pytest.raises(ValueError, match=match):
        sample_video(make_cfr(10, 4.0), "cam_01", out_dir=tmp_path, **kw)


# --- determinism -------------------------------------------------------------------------


@pytest.mark.media
def test_manifest_and_outputs_are_deterministic(make_cfr, tmp_path):
    video = make_cfr(25, 4.0)
    kw = {"sample_fps": 2.0, "max_frames": 5, "start_s": 0.3, "end_s": 3.7, "clip": True}

    first = sample_video(video, "cam_01", out_dir=tmp_path / "a", **kw)
    text_1 = manifest_json(first)
    hashes_1 = [_sha(_file(f.path)) for f in first.frames] + [_sha(_file(first.clip_path))]
    second = sample_video(video, "cam_01", out_dir=tmp_path / "a", **kw)
    assert manifest_json(second) == text_1  # byte-identical, same out_dir
    assert [_sha(_file(f.path)) for f in second.frames] + [_sha(_file(second.clip_path))] == (
        hashes_1
    )

    other = sample_video(video, "cam_01", out_dir=tmp_path / "b", **kw)
    assert [_sha(_file(f.path)) for f in other.frames] + [_sha(_file(other.clip_path))] == (
        hashes_1
    )

    def strip_paths(doc: dict) -> dict:
        doc = dict(doc, clip_path=None)
        doc["frames"] = [dict(f, path=None) for f in doc["frames"]]
        return doc

    assert strip_paths(json.loads(manifest_json(other))) == strip_paths(json.loads(text_1))
    assert first.source_sha256 == _sha(video)
    assert "time" not in text_1.replace('"t"', "")  # no wall-clock fields


@pytest.mark.media
def test_conform_path_is_identity_on_cfr(make_cfr, tmp_path):
    video, ids = make_cfr(25, 4.0), [0, 1, 7, 50, 98, 99]
    direct = extract_frames(video, ids, tmp_path / "direct")
    conformed = extract_frames(video, ids, tmp_path / "conform", conform_fps=Fraction(25))
    assert [_sha(p) for p in direct] == [_sha(p) for p in conformed]


@pytest.mark.media
def test_percent_in_output_dir_is_not_a_pattern(make_cfr, read_code, tmp_path):
    out = tmp_path / "run%03d"  # image2 would expand this if it were not escaped
    m = sample_video(make_cfr(10, 4.0), "cam_01", out_dir=out, max_frames=2)
    assert sorted(p.name for p in (out / "cam_01").iterdir()) == ["0000.jpg", "0001.jpg"]
    assert _codes(m, read_code) == [0, 30]


@pytest.mark.media
def test_stale_outputs_are_removed(make_cfr, tmp_path):
    video = make_cfr(25, 4.0)
    sample_video(video, "cam_01", out_dir=tmp_path, sample_fps=4.0, max_frames=8, clip=True)
    (tmp_path / "cam_01" / "notes.txt").write_text("keep me", encoding="utf-8")
    m = sample_video(video, "cam_01", out_dir=tmp_path, max_frames=3)
    assert len(m.frames) == 3
    assert sorted(p.name for p in (tmp_path / "cam_01").iterdir()) == [
        "0000.jpg",
        "0001.jpg",
        "0002.jpg",
        "notes.txt",
    ]


# --- clip mode ---------------------------------------------------------------------------


@pytest.mark.media
@pytest.mark.parametrize(
    ("start", "end", "first", "count"),
    [
        (0.5, 2.5, 12, 50),  # frame-aligned window: exactly 2.0 s
        (0.53, 2.2, 13, 42),  # 1.67 s window -> ceil(41.75) = 42 frames = 1.68 s
    ],
)
def test_clip_is_frame_exact_h264(make_cfr, read_code, tmp_path, start, end, first, count):
    m = sample_video(
        make_cfr(25, 4.0), "cam_01", out_dir=tmp_path, start_s=start, end_s=end, clip=True
    )
    clip = _file(m.clip_path)
    assert clip == tmp_path.resolve() / "cam_01" / "clip.mp4"
    assert m.frames[0].frame_id == first  # clip t=0 is frames[0].t on the media clock

    streams = _ffprobe_streams(clip)
    assert [s["codec_type"] for s in streams] == ["video"]  # no audio
    video = streams[0]
    assert (video["codec_name"], video["pix_fmt"]) == ("h264", "yuv420p")
    assert int(video["nb_frames"]) == count
    assert abs(float(video["duration"]) - (end - start)) < 1 / 25

    decoded = _clip_gray_frames(clip)
    assert [read_code(f) for f in decoded] == list(range(first, first + count))

    atoms = _top_level_atoms(clip)
    assert atoms.index("moov") < atoms.index("mdat")  # +faststart


# --- VFR, late start, rotation, scaling --------------------------------------------------


@pytest.mark.media
def test_vfr_frames_match_what_is_on_screen(vfr_video, read_code, tmp_path):
    path, pts = vfr_video
    m = sample_video(path, "cam_v", out_dir=tmp_path, sample_fps=4.0, max_frames=100, clip=True)
    fps = Fraction(m.src_fps).limit_denominator(100000)
    assert fps < 30  # average rate of the VFR stream
    _assert_frame_aligned(m, fps)

    def on_screen_at_mid_slot(slot: int) -> int:
        mid = (slot + Fraction(1, 2)) / fps
        return max(n for n, p in enumerate(pts) if p < mid)

    expected = [on_screen_at_mid_slot(f.frame_id) for f in m.frames]
    assert _codes(m, read_code) == expected
    assert len(set(expected)) > 10  # both the 30 fps and the 10 fps parts were sampled

    decoded = _clip_gray_frames(_file(m.clip_path))
    first = m.frames[0].frame_id
    assert [read_code(f) for f in decoded] == [
        on_screen_at_mid_slot(first + j) for j in range(len(decoded))
    ]


@pytest.mark.media
def test_late_video_start_keeps_media_clock(offset_video, read_code, tmp_path):
    # Video frames start at media time 0.5 s (audio leads): media frame k shows source k - 5.
    m = sample_video(offset_video, "cam_o", out_dir=tmp_path, sample_fps=2.0, max_frames=100)
    assert m.duration_s == pytest.approx(3.5)
    assert [f.t for f in m.frames] == [k / 2 for k in range(7)]
    assert _codes(m, read_code) == [max(0, f.frame_id - 5) for f in m.frames]


@pytest.mark.media
def test_rotated_source_is_upright_with_display_dims(rotated_video, read_code, tmp_path):
    m = sample_video(rotated_video, "cam_r", out_dir=tmp_path, sample_fps=1.0)
    assert (m.width, m.height) == (240, 320)
    for f in m.frames:
        gray = np.asarray(cv2.imread(str(_file(f.path)), cv2.IMREAD_GRAYSCALE))
        assert gray.shape == (320, 240)
        assert f.frame_id in {read_code(np.rot90(gray, k)) for k in (1, 3)}


@pytest.mark.media
@pytest.mark.parametrize(("max_width", "width"), [(100, 100), (101, 100), (768, 320)])
def test_downscale_keeps_aspect_and_even_dims(make_cfr, tmp_path, max_width, width):
    m = sample_video(
        make_cfr(25, 4.0), "cam_01", out_dir=tmp_path, max_width=max_width, max_frames=1
    )
    h, w = cv2.imread(str(_file(m.frames[0].path)), cv2.IMREAD_GRAYSCALE).shape
    assert w == width and w % 2 == 0 and h % 2 == 0
    assert abs(h - w * 240 / 320) <= 1
    assert (m.width, m.height) == (320, 240)  # manifest keeps source dims


# --- contract, paths, CLI ----------------------------------------------------------------


@pytest.mark.media
def test_manifest_validates_and_round_trips(make_cfr, tmp_path):
    m = sample_video(make_cfr(25, 4.0), "cam_01", out_dir=tmp_path, clip=True)
    doc = json.loads(manifest_json(m))
    validate_json("media_manifest", doc)
    assert MediaManifest.model_validate(doc) == m


def test_portable_paths():
    inside = REPO_ROOT / "data" / "runs" / "run_x" / "frames" / "cam_01" / "0000.jpg"
    assert portable_path(inside) == "data/runs/run_x/frames/cam_01/0000.jpg"
    outside = REPO_ROOT.parent / "elsewhere" / "v.mp4"
    assert portable_path(outside) == outside.resolve().as_posix()
    assert "\\" not in portable_path(outside)


@pytest.mark.parametrize("camera_id", ["", ".", "..", "../evil", "a/b", "a\\b", "-cam", "cam 1"])
def test_unsafe_camera_id_rejected(tmp_path, camera_id):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="camera_id"):
        sample_video(video, camera_id, out_dir=tmp_path)


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"jpeg_quality": 1}, "jpeg_quality"),
        ({"jpeg_quality": 32}, "jpeg_quality"),
        ({"max_width": 1}, "max_width"),
    ],
)
def test_bad_output_options_rejected(tmp_path, kw, match):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    with pytest.raises(ValueError, match=match):
        sample_video(video, "cam_01", out_dir=tmp_path, **kw)


def test_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        sample_video(tmp_path / "missing.mp4", "cam_01", out_dir=tmp_path)


@pytest.mark.media
def test_missing_ffmpeg_is_a_clear_error(make_cfr, monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG_BIN", str(tmp_path / "no-such-ffmpeg"))
    with pytest.raises(MediaToolError, match="FFMPEG_BIN"):
        sample_video(make_cfr(10, 4.0), "cam_01", out_dir=tmp_path)


@pytest.mark.media
def test_cli_prints_the_manifest(make_cfr, tmp_path, capsys):
    video = make_cfr(10, 4.0)
    argv = [
        "--video",
        str(video),
        "--camera-id",
        "cam_01",
        "--out",
        str(tmp_path),
        "--fps",
        "2",
        "--max-frames",
        "3",
        "--start",
        "0.5",
        "--end",
        "3.5",
        "--clip",
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    expected = sample_video(
        video,
        "cam_01",
        out_dir=tmp_path,
        sample_fps=2.0,
        max_frames=3,
        start_s=0.5,
        end_s=3.5,
        clip=True,
    )
    assert printed == manifest_json(expected)


@pytest.mark.media
def test_cli_reports_errors(make_cfr, tmp_path, capsys):
    argv = [
        "--video",
        str(make_cfr(10, 4.0)),
        "--camera-id",
        "cam_01",
        "--out",
        str(tmp_path),
        "--start",
        "50",
    ]
    assert main(argv) == 1
    assert "at or past the end" in capsys.readouterr().err


@pytest.mark.media
def test_cli_runs_as_module(make_cfr, tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.sample_video",
            "--video",
            str(make_cfr(10, 4.0)),
            "--camera-id",
            "cam_01",
            "--out",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    validate_json("media_manifest", doc)
    assert [f["frame_id"] for f in doc["frames"]] == [0, 10, 20, 30]

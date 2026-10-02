"""P04: probe_video facts and ffmpeg/ffprobe discovery."""

from __future__ import annotations

import pytest

from tools.media.binaries import MediaToolError, ffmpeg_bin, ffprobe_bin
from tools.media.probe import probe_video


@pytest.mark.media
@pytest.mark.parametrize(("fps", "frames"), [(10, 40), (25, 100)])
def test_probe_cfr(make_cfr, fps, frames):
    info = probe_video(make_cfr(fps, 4.0))
    assert info["codec"] == "h264"
    assert (info["width"], info["height"], info["rotation"]) == (320, 240, 0)
    assert info["src_fps"] == float(fps)
    assert (info["fps_num"], info["fps_den"]) == (fps, 1)
    assert info["duration_s"] == pytest.approx(4.0)
    assert info["nb_frames"] == frames
    assert info["vfr"] is False
    assert info["start_offset_s"] == 0.0


@pytest.mark.media
def test_probe_flags_vfr_and_uses_average_rate(vfr_video):
    path, pts = vfr_video
    info = probe_video(path)
    assert info["vfr"] is True
    assert info["r_frame_rate"] == "30/1"
    assert info["src_fps"] < 30.0  # mean rate, not the 30 fps burst
    assert info["nb_frames"] == len(pts)


@pytest.mark.media
def test_probe_reports_late_video_start(offset_video):
    info = probe_video(offset_video)
    assert info["start_offset_s"] == pytest.approx(0.5)
    assert info["duration_s"] == pytest.approx(3.0)
    assert info["vfr"] is False


@pytest.mark.media
def test_probe_swaps_dims_for_rotation(rotated_video):
    info = probe_video(rotated_video)
    assert info["rotation"] in (90, 270)
    assert (info["width"], info["height"]) == (240, 320)


@pytest.mark.media
def test_probe_rejects_audio_only(audio_only):
    with pytest.raises(ValueError, match="no video stream"):
        probe_video(audio_only)


@pytest.mark.media
def test_probe_rejects_non_media(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all")
    with pytest.raises(MediaToolError, match="ffprobe"):
        probe_video(junk)


def test_probe_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        probe_video(tmp_path / "nope.mp4")


@pytest.mark.parametrize(
    ("env_var", "resolver"),
    [
        ("FFMPEG_BIN", ffmpeg_bin),
        ("FFPROBE_BIN", ffprobe_bin),
    ],
)
def test_bad_binary_override_is_a_clear_error(monkeypatch, tmp_path, env_var, resolver):
    monkeypatch.setenv(env_var, str(tmp_path / "no-such-binary"))
    with pytest.raises(MediaToolError, match=env_var):
        resolver()


def test_missing_binary_on_path_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaToolError, match="ffprobe not found on PATH"):
        ffprobe_bin()


def test_probe_surfaces_missing_ffprobe(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setenv("FFPROBE_BIN", str(tmp_path / "no-such-binary"))
    with pytest.raises(MediaToolError, match="FFPROBE_BIN"):
        probe_video(video)


@pytest.mark.media
def test_binary_override_by_path_is_used(monkeypatch):
    real = ffprobe_bin()
    monkeypatch.setenv("FFPROBE_BIN", real)
    assert ffprobe_bin() == real

"""P04: the deterministic frame schedule (pure arithmetic, no ffmpeg)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from tools.media.binaries import parse_ffmpeg_version
from tools.media.schedule import (
    MAX_CANDIDATES,
    clip_frame_range,
    plan_frames,
    spread_indices,
)


def plan(fps, duration, *, last_frame=None, **kw):
    fps = Fraction(fps)
    if last_frame is None:
        last_frame = int(duration * fps) - 1
    return plan_frames(src_fps=fps, media_end_s=duration, last_frame=last_frame, **kw)


@pytest.mark.parametrize(
    ("fps", "expected_ids"),
    [(10, (0, 10, 20, 30)), (25, (0, 25, 50, 75))],
)
def test_one_hz_maps_to_whole_second_frames(fps, expected_ids):
    p = plan(fps, 4.0, sample_fps=1.0, max_frames=8)
    assert p.frame_ids == expected_ids
    assert p.times == (0.0, 1.0, 2.0, 3.0)
    assert (p.start_s, p.end_s) == (0.0, 4.0)


@pytest.mark.parametrize(
    ("fps", "start", "frame_id", "t"),
    [
        (10, 1.25, 12, 1.2),  # frame on screen at 1.25 s started at 1.2 s
        (25, 1.25, 31, 1.24),
        (25, 0.5, 12, 0.48),
    ],
)
def test_frame_on_screen_and_frame_aligned_t(fps, start, frame_id, t):
    p = plan(fps, 4.0, start_s=start, max_frames=1)
    assert p.frame_ids == (frame_id,)
    assert p.times == (t,)


def test_exact_decimal_arithmetic_beats_float_floor():
    # 0.29 * 100 == 28.999999999999996 in floats; the frame on screen at 0.29 s is 29.
    assert int(0.29 * 100) == 28
    assert plan(100, 1.0, start_s=0.29, max_frames=1).frame_ids == (29,)


def test_ntsc_rate_t_is_exact_frame_start():
    fps = Fraction(30000, 1001)
    p = plan_frames(src_fps=fps, media_end_s=10.0, last_frame=298, sample_fps=1.0, max_frames=20)
    assert p.frame_ids[:4] == (0, 29, 59, 89)  # floor(k * 29.97)
    for frame_id, t, k in zip(p.frame_ids, p.times, range(20), strict=False):
        assert t == float(Fraction(frame_id) / fps)
        assert k - float(1 / fps) < t <= k  # at or before the candidate, by < 1 frame


def test_spread_keeps_first_and_last_evenly():
    # 60 one-second candidates, keep 8: positions round_half_up(j * 59 / 7).
    p = plan(25, 60.0, sample_fps=1.0, max_frames=8)
    assert p.frame_ids == tuple(25 * i for i in (0, 8, 17, 25, 34, 42, 51, 59))


@pytest.mark.parametrize(("count", "keep"), [(1, 1), (5, 1), (5, 2), (10, 3), (59, 8), (7, 7)])
def test_spread_indices_properties(count, keep):
    idx = spread_indices(count, keep)
    assert len(idx) == min(count, keep)
    assert idx == sorted(set(idx))
    assert idx[0] == 0
    if keep > 1:
        assert idx[-1] == count - 1


def test_round_half_up_is_deterministic():
    # 6 candidates -> 5 kept: j * 5 / 4 = 0, 1.25, 2.5, 3.75, 5 -> 0, 1, 3, 4, 5
    assert spread_indices(6, 5) == [0, 1, 3, 4, 5]


def test_short_window_keeps_every_candidate():
    p = plan(10, 4.0, sample_fps=1.0, max_frames=8)
    assert len(p.frame_ids) == 4


def test_window_start_end_exclusive():
    p = plan(10, 4.0, sample_fps=2.0, start_s=1.5, end_s=3.0)
    assert p.frame_ids == (15, 20, 25)  # 3.0 itself is excluded
    assert (p.start_s, p.end_s) == (1.5, 3.0)


def test_end_past_video_is_clamped_and_recorded():
    p = plan(10, 4.0, sample_fps=1.0, end_s=100.0)
    assert p.end_s == 4.0
    assert p.frame_ids == (0, 10, 20, 30)


def test_oversampling_dedups_to_each_frame_once():
    p = plan(10, 4.0, sample_fps=25.0, end_s=1.0, max_frames=100)
    assert p.frame_ids == tuple(range(10))


def test_oversampling_spreads_over_unique_frames():
    p = plan(10, 4.0, sample_fps=25.0, end_s=1.0, max_frames=4)
    assert p.frame_ids == (0, 3, 6, 9)


def test_last_frame_clamp_dedups():
    # Metadata says 4 s but only 34 frames exist: candidates 3.0/3.25/3.5/3.75 s map to
    # 30/32/35/37, and the last two clamp onto frame 33 and collapse into one.
    p = plan(10, 4.0, last_frame=33, sample_fps=4.0, start_s=3.0)
    assert p.frame_ids == (30, 32, 33)


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"start_s": -0.1}, "start_s must be >= 0"),
        ({"start_s": 4.0}, "at or past the end"),
        ({"start_s": 9.0}, "at or past the end"),
        ({"start_s": 2.0, "end_s": 2.0}, "empty window"),
        ({"start_s": 2.0, "end_s": 1.0}, "empty window"),
        ({"sample_fps": 0.0}, "sample_fps must be > 0"),
        ({"sample_fps": -1.0}, "sample_fps must be > 0"),
        ({"sample_fps": float("nan")}, "finite"),
        ({"end_s": float("inf")}, "finite"),
        ({"max_frames": 0}, "max_frames must be >= 1"),
        ({"sample_fps": float(MAX_CANDIDATES)}, "candidate times exceed"),
    ],
)
def test_invalid_windows_raise(kw, match):
    with pytest.raises(ValueError, match=match):
        plan(25, 4.0, **kw)


def test_clip_range_starts_on_first_sample_and_is_within_one_frame():
    fps = Fraction(25)
    assert clip_frame_range(fps, 0.5, 2.5, 99) == (12, 62)  # 50 frames = exactly 2.0 s
    first, stop = clip_frame_range(fps, 0.53, 2.2, 99)  # window 1.67 s
    assert first == plan(25, 4.0, start_s=0.53, max_frames=1).frame_ids[0]
    assert 0 <= (stop - first) / 25 - 1.67 < 1 / 25
    assert clip_frame_range(fps, 3.5, 4.0, 99) == (87, 100)  # ceil(12.5) = 13 frames
    assert clip_frame_range(fps, 3.5, 4.5, 99) == (87, 100)  # 25 frames, clamped at frame 99


@pytest.mark.parametrize(
    ("banner", "version"),
    [
        ("ffmpeg version 8.1-full_build-www.gyan.dev Copyright (c) 2000-2026", (8, 1)),
        ("ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023", (6, 1)),
        ("ffmpeg version 4.4.2-0ubuntu0.22.04.1 Copyright", (4, 4)),
        ("ffmpeg version n7.0.2 Copyright", (7, 0)),
        ("ffmpeg version N-112345-gabcdef0 Copyright", None),
    ],
)
def test_parse_ffmpeg_version(banner, version):
    assert parse_ffmpeg_version(banner) == version

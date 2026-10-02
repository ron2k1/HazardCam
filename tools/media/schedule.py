"""Deterministic frame schedule: pure arithmetic, no ffmpeg. The rule is documented in
``tools/sample_video.py``; everything here is exact rational math so the same inputs give
the same frames on every machine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

# Guard against absurd sample_fps x window products (each candidate costs a little Python).
MAX_CANDIDATES = 1_000_000


@dataclass(frozen=True)
class FramePlan:
    frame_ids: tuple[int, ...]
    times: tuple[float, ...]
    start_s: float
    end_s: float


def exact(value: float, name: str) -> Fraction:
    """The decimal value as written (``0.29`` -> 29/100), not its binary float approximation."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return Fraction(repr(float(value)))


def frame_time(frame_id: int, src_fps: Fraction) -> float:
    """Start of ``frame_id`` on the media clock, correctly rounded from the exact rational."""
    return float(Fraction(frame_id) / src_fps)


def _window(start_s: float, end_s: float | None, media_end_s: float) -> tuple[Fraction, Fraction]:
    start, media_end = exact(start_s, "start_s"), exact(media_end_s, "media_end_s")
    if start < 0:
        raise ValueError(f"start_s must be >= 0, got {start_s}")
    if start >= media_end:
        raise ValueError(f"start_s={start_s} is at or past the end of the video ({media_end_s}s)")
    if end_s is None:
        return start, media_end
    end = exact(end_s, "end_s")
    if end <= start:
        raise ValueError(f"empty window: end_s={end_s} must be greater than start_s={start_s}")
    return start, min(end, media_end)


def spread_indices(count: int, keep: int) -> list[int]:
    """``keep`` evenly spaced positions in ``range(count)``: first and last always included,
    position j = round_half_up(j * (count - 1) / (keep - 1)), all integer arithmetic."""
    if keep >= count:
        return list(range(count))
    if keep == 1:
        return [0]
    span, gaps = count - 1, keep - 1
    return [(2 * j * span + gaps) // (2 * gaps) for j in range(keep)]


def plan_frames(
    *,
    src_fps: Fraction,
    media_end_s: float,
    last_frame: int,
    sample_fps: float = 1.0,
    max_frames: int = 8,
    start_s: float = 0.0,
    end_s: float | None = None,
) -> FramePlan:
    """Pick the frames to extract; see the module docstring of ``tools.sample_video``."""
    if src_fps <= 0:
        raise ValueError(f"src_fps must be > 0, got {src_fps}")
    if last_frame < 0:
        raise ValueError("video has no frames")
    rate = exact(sample_fps, "sample_fps")
    if rate <= 0:
        raise ValueError(f"sample_fps must be > 0, got {sample_fps}")
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1, got {max_frames}")
    start, end = _window(start_s, end_s, media_end_s)

    # Candidate k sits at start + k/rate and exists while it is < end.
    count = math.ceil((end - start) * rate)
    if count > MAX_CANDIDATES:
        raise ValueError(
            f"{count} candidate times exceed {MAX_CANDIDATES}; lower sample_fps or narrow the window"
        )
    # frame_id_k = floor((start + k/rate) * src_fps) as one integer floor division.
    base, step = start * src_fps, src_fps / rate
    a, b, c, d = base.numerator, base.denominator, step.numerator, step.denominator
    unique: list[int] = []
    for k in range(count):
        frame_id = min((a * d + k * c * b) // (b * d), last_frame)
        if not unique or frame_id != unique[-1]:  # non-decreasing in k, so adjacent dedup suffices
            unique.append(frame_id)

    chosen = tuple(unique[i] for i in spread_indices(len(unique), max_frames))
    return FramePlan(
        frame_ids=chosen,
        times=tuple(frame_time(f, src_fps) for f in chosen),
        start_s=float(start),
        end_s=float(end),
    )


def clip_frame_range(
    src_fps: Fraction, start_s: float, end_s: float, last_frame: int
) -> tuple[int, int]:
    """``[first, stop)`` frames for the short clip: it starts on the frame on screen at
    ``start_s`` (= ``frames[0].frame_id`` of the manifest) and holds
    ``ceil((end_s - start_s) * src_fps)`` frames, so its duration is within one frame of the
    window (clamped at the last frame)."""
    start, end = exact(start_s, "start_s"), exact(end_s, "end_s")
    first = min(math.floor(start * src_fps), last_frame)
    stop = min(first + math.ceil((end - start) * src_fps), last_frame + 1)
    return first, max(stop, first + 1)

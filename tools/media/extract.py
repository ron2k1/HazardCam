"""Frame-accurate JPEG extraction and short-clip encoding with ffmpeg.

Frames are chosen by decoded frame number (``select=eq(n,F)``), never by seeking, so the
output is exactly the planned frames. ``conform_fps`` first resamples the decoder output onto
a constant grid with ``fps=...:round=near:start_time=0``: grid slot k then holds the latest
source frame with pts < (k + 0.5) / fps, i.e. the frame on screen at the slot midpoint. On a
CFR stream that starts at 0 this is the identity, so it is only used for VFR sources and
streams that start late (audio leading video), where ``n`` and media time disagree.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from .binaries import MediaToolError, ffmpeg_bin, passthrough_args, run_tool

FRAME_NAME = re.compile(r"\d{4,}\.jpg")
CLIP_NAME = "clip.mp4"

_BASE_ARGS = ("-hide_banner", "-nostdin", "-loglevel", "error", "-y")
_VIDEO_ONLY = ("-map", "0:v:0", "-an", "-sn", "-dn")


def frame_name(index: int) -> str:
    return f"{index:04d}.jpg"


def conform_filter(fps: Fraction) -> str:
    return f"fps=fps={fps.numerator}/{fps.denominator}:round=near:start_time=0"


def select_filter(frame_ids: Sequence[int]) -> str:
    return "select=" + "+".join(f"eq(n\\,{f})" for f in frame_ids)


def scale_filter(max_width: int) -> str:
    """Downscale to at most ``max_width`` (never upscale), aspect kept, both dims even."""
    return f"scale=w=trunc(min(iw\\,{max_width})/2)*2:h=-2:flags=bicubic"


def _video_filter(*parts: str | None) -> str:
    return ",".join(p for p in parts if p)


def clear_outputs(dest: Path) -> None:
    """Remove frames/clip a previous run left in ``dest`` (only names this module writes)."""
    if not dest.is_dir():
        return
    for path in dest.iterdir():
        if path.is_file() and (FRAME_NAME.fullmatch(path.name) or path.name == CLIP_NAME):
            path.unlink()


def extract_frames(
    video: Path,
    frame_ids: Sequence[int],
    dest: Path,
    *,
    conform_fps: Fraction | None = None,
    max_width: int = 768,
    jpeg_quality: int = 3,
) -> list[Path]:
    """Write frame ``frame_ids[i]`` to ``dest/{i:04d}.jpg`` in one decode pass."""
    ids = list(frame_ids)
    if not ids or ids[0] < 0 or any(b <= a for a, b in pairwise(ids)):
        raise ValueError(f"frame_ids must be non-empty, >= 0 and strictly increasing: {ids}")
    dest.mkdir(parents=True, exist_ok=True)
    clear_outputs(dest)
    ffmpeg = ffmpeg_bin()
    vf = _video_filter(
        conform_filter(conform_fps) if conform_fps else None,
        select_filter(ids),
        scale_filter(max_width),
    )
    # image2 treats '%' as a pattern character, so escape it in the directory part.
    pattern = os.path.join(str(dest.resolve()).replace("%", "%%"), "%04d.jpg")
    run_tool(
        [
            ffmpeg,
            *_BASE_ARGS,
            "-i",
            str(video.resolve()),
            *_VIDEO_ONLY,
            "-vf",
            vf,
            *passthrough_args(ffmpeg),
            "-c:v",
            "mjpeg",
            "-q:v",
            str(jpeg_quality),
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-start_number",
            "0",
            pattern,
        ],
        what=f"ffmpeg frame extraction from {video.name}",
    )
    expected = [dest / frame_name(i) for i in range(len(ids))]
    written = sorted(p.name for p in dest.iterdir() if FRAME_NAME.fullmatch(p.name))
    if written != [p.name for p in expected]:
        why = (
            "the decoded stream is shorter than its metadata claims"
            if len(written) < len(ids)
            else "ffmpeg duplicated frames (output frame-rate mode is not passthrough)"
        )
        raise MediaToolError(
            f"{video.name}: planned {len(ids)} frames (last frame_id {ids[-1]}) but ffmpeg "
            f"wrote {len(written)}; {why}"
        )
    return expected


def write_clip(
    video: Path,
    dest_file: Path,
    *,
    first_frame: int,
    stop_frame: int,
    conform_fps: Fraction | None = None,
    max_width: int = 768,
) -> Path:
    """Encode frames ``[first_frame, stop_frame)`` as a browser/model-friendly H.264 mp4."""
    if not 0 <= first_frame < stop_frame:
        raise ValueError(f"bad clip frame range [{first_frame}, {stop_frame})")
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_bin()
    vf = _video_filter(
        conform_filter(conform_fps) if conform_fps else None,
        f"trim=start_frame={first_frame}:end_frame={stop_frame}",
        "setpts=PTS-STARTPTS",
        scale_filter(max_width),
    )
    run_tool(
        [
            ffmpeg,
            *_BASE_ARGS,
            "-i",
            str(video.resolve()),
            *_VIDEO_ONLY,
            "-vf",
            vf,
            *passthrough_args(ffmpeg),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-fflags",
            "+bitexact",
            str(dest_file.resolve()),
        ],
        what=f"ffmpeg clip encode from {video.name}",
    )
    if not dest_file.is_file() or dest_file.stat().st_size == 0:
        raise MediaToolError(f"ffmpeg reported success but wrote no clip at {dest_file}")
    return dest_file

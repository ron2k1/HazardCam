"""``probe_video``: the stream facts the sampler's frame schedule depends on (via ffprobe)."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from .binaries import ffprobe_bin, run_tool


def _rate(text: str | None) -> Fraction | None:
    """Parse an ffprobe rational like ``30000/1001``; ``0/0`` and junk mean unknown."""
    if not text:
        return None
    num, _, den = text.partition("/")
    try:
        rate = Fraction(int(num), int(den or "1"))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    """Display rotation in degrees [0, 360) from the display matrix (or a legacy ``rotate`` tag)."""
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return round(float(side["rotation"])) % 360
    rotate = _float((stream.get("tags") or {}).get("rotate"))
    return round(rotate) % 360 if rotate is not None else 0


def probe_video(video_path: Path) -> dict[str, Any]:
    """Describe the first video stream of ``video_path``.

    Keys: ``codec``, ``width``/``height`` (display orientation: swapped when the stream
    carries a 90/270 degree rotation, which ffmpeg applies while decoding), ``rotation``,
    ``src_fps`` (float) plus its exact ``fps_num``/``fps_den``, the raw ``r_frame_rate`` /
    ``avg_frame_rate``, ``vfr``, ``duration_s`` (video stream), ``start_offset_s`` (video start
    after the container start, e.g. when audio leads), and ``nb_frames`` (container count,
    else a demux packet count; None if neither is known).

    ``src_fps`` is ``avg_frame_rate`` when known (the true mean rate; for CFR it equals
    ``r_frame_rate``), else ``r_frame_rate``. ``vfr`` is True when both are known and differ.
    """
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"video not found: {path}")
    proc = run_tool(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-select_streams",
            "v:0",
            "-count_packets",
            str(path.resolve()),
        ],
        what=f"ffprobe {path.name}",
    )
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams") or []
    if not streams:
        raise ValueError(f"{path} has no video stream")
    stream, fmt = streams[0], info.get("format") or {}

    r_rate, avg_rate = _rate(stream.get("r_frame_rate")), _rate(stream.get("avg_frame_rate"))
    fps = avg_rate or r_rate
    if fps is None:
        raise ValueError(f"{path}: cannot determine the frame rate")

    stream_start, fmt_start = _float(stream.get("start_time")), _float(fmt.get("start_time"))
    offset = 0.0
    if stream_start is not None and fmt_start is not None:
        offset = max(0.0, stream_start - fmt_start)

    duration = _float(stream.get("duration"))
    if duration is None:
        fmt_duration = _float(fmt.get("duration"))
        duration = None if fmt_duration is None else max(0.0, fmt_duration - offset)
    if duration is None or duration <= 0:
        raise ValueError(f"{path}: cannot determine a positive video duration")

    nb_frames = None
    for key in ("nb_frames", "nb_read_packets"):
        count = _float(stream.get(key))
        if count is not None and count > 0:
            nb_frames = int(count)
            break

    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width < 1 or height < 1:
        raise ValueError(f"{path}: video stream has no frame size")
    rotation = _rotation(stream)
    if rotation in (90, 270):
        width, height = height, width

    return {
        "codec": stream.get("codec_name"),
        "width": width,
        "height": height,
        "rotation": rotation,
        "src_fps": float(fps),
        "fps_num": fps.numerator,
        "fps_den": fps.denominator,
        "r_frame_rate": stream.get("r_frame_rate"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "vfr": r_rate is not None and avg_rate is not None and r_rate != avg_rate,
        "duration_s": duration,
        "start_offset_s": offset,
        "nb_frames": nb_frames,
    }

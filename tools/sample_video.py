"""Deterministic media sampler: frames (and an optional short clip) with exact seek metadata.

Schedule (same inputs -> same frames on every machine; all arithmetic is exact rational math
on the decimal values passed in, so ``start_s=0.29`` at 100 fps is frame 29, not 28):

1. Window ``[start_s, end)``, ``end = min(end_s, video end)`` (``end_s=None`` -> video end).
   ``start_s < 0``, ``start_s`` at/after the video end, or ``end_s <= start_s`` raise
   ``ValueError``. An ``end_s`` past the video end is clamped and the clamped value recorded.
2. Candidate times ``t_k = start_s + k / sample_fps`` for k = 0, 1, ... while ``t_k < end``.
3. Each candidate maps to the frame on screen at that time:
   ``frame_id = floor(t_k * src_fps)``, clamped to the last frame. When ``sample_fps`` exceeds
   ``src_fps`` several candidates share a frame; duplicates are dropped so each frame appears
   once (frame_ids are strictly increasing).
4. If more than ``max_frames`` frames remain, keep ``max_frames`` of them evenly spread:
   position j = round_half_up(j * (n - 1) / (max_frames - 1)); the first and last are always
   kept. Fewer frames than ``max_frames`` (short video or window) are all kept.
5. ``t = frame_id / src_fps``: the exact start of that frame on the media clock (<= the
   candidate time, by less than one frame). ``index`` is the position in ``frames[]``. For a
   frame-exact UI seek, target the middle of the frame: ``t + 0.5 / src_fps``.

``src_fps`` is the stream's average frame rate (equal to ``r_frame_rate`` for CFR). For a
constant-frame-rate stream that starts at media time 0, ``frame_id`` is the literal source
frame number and frames are selected by decoded frame count. Variable-frame-rate streams (and
streams that start late, e.g. when audio leads) are first conformed to a constant ``src_fps``
grid: ``frame_id`` is then the grid slot and its JPEG is the source frame on screen at the slot
midpoint ``(frame_id + 0.5) / src_fps``, so ``t`` stays an exact, consistent seek target. See
``tools/media/extract.py``.

Outputs go to ``out_dir/<camera_id>/``: ``{index:04d}.jpg`` (downscaled to ``max_width``,
aspect kept, even dims, never upscaled) and, with ``clip=True``, ``clip.mp4`` (H.264 yuv420p,
faststart, no audio) starting at ``frames[0].frame_id`` and holding
``ceil((end - start_s) * src_fps)`` frames. Stale frames/clips from earlier runs are removed.
Manifest paths are repo-relative POSIX when inside the repo, else absolute POSIX; there are no
wall-clock fields, so the manifest JSON is byte-identical across runs.

CLI: ``python -m tools.sample_video --video V --camera-id cam_01 --out DIR [--fps 1 --max-frames
8 --start 0 --end 15 --clip]`` prints the manifest JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

from apps.api.schemas import REPO_ROOT, FrameRef, MediaManifest, validate_json
from tools.media.binaries import MediaToolError
from tools.media.extract import CLIP_NAME, extract_frames, write_clip
from tools.media.probe import probe_video
from tools.media.schedule import clip_frame_range, exact, plan_frames

CAMERA_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def portable_path(path: Path) -> str:
    """Repo-relative POSIX path when ``path`` is inside the repo, else absolute POSIX."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_json(manifest: MediaManifest) -> str:
    """Canonical JSON text of a manifest (what the CLI prints)."""
    return json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"


def sample_video(
    video_path: Path,
    camera_id: str,
    *,
    out_dir: Path,
    sample_fps: float = 1.0,
    max_frames: int = 8,
    start_s: float = 0.0,
    end_s: float | None = None,
    clip: bool = False,
    jpeg_quality: int = 3,
    max_width: int = 768,
) -> MediaManifest:
    """Sample ``video_path`` deterministically; see the module docstring for the rule."""
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"video not found: {video}")
    if not CAMERA_ID.fullmatch(camera_id):
        raise ValueError(f"camera_id {camera_id!r} is not a safe path component")
    if not 2 <= jpeg_quality <= 31:
        raise ValueError(f"jpeg_quality must be in 2..31 (lower is better), got {jpeg_quality}")
    if max_width < 2:
        raise ValueError(f"max_width must be >= 2, got {max_width}")

    info = probe_video(video)
    fps = Fraction(info["fps_num"], info["fps_den"])
    conform = info["vfr"] or info["start_offset_s"] * fps >= Fraction(1, 2)
    if conform:
        media_end = info["start_offset_s"] + info["duration_s"]
        last_frame = math.ceil(exact(media_end, "media_end") * fps) - 1
    else:
        media_end = info["duration_s"]
        nb_frames = info["nb_frames"] or math.ceil(exact(media_end, "media_end") * fps)
        last_frame = nb_frames - 1

    plan = plan_frames(
        src_fps=fps,
        media_end_s=media_end,
        last_frame=last_frame,
        sample_fps=sample_fps,
        max_frames=max_frames,
        start_s=start_s,
        end_s=end_s,
    )
    dest = Path(out_dir) / camera_id
    conform_fps = fps if conform else None
    paths = extract_frames(
        video,
        plan.frame_ids,
        dest,
        conform_fps=conform_fps,
        max_width=max_width,
        jpeg_quality=jpeg_quality,
    )
    clip_path = None
    if clip:
        first, stop = clip_frame_range(fps, plan.start_s, plan.end_s, last_frame)
        clip_path = write_clip(
            video,
            dest / CLIP_NAME,
            first_frame=first,
            stop_frame=stop,
            conform_fps=conform_fps,
            max_width=max_width,
        )

    manifest = MediaManifest(
        camera_id=camera_id,
        source=portable_path(video),
        source_sha256=file_sha256(video),
        duration_s=media_end,
        src_fps=float(fps),
        width=info["width"],
        height=info["height"],
        sample_fps=float(sample_fps),
        start_s=plan.start_s,
        end_s=plan.end_s,
        clip_path=portable_path(clip_path) if clip_path else None,
        frames=[
            FrameRef(index=i, frame_id=frame_id, t=t, path=portable_path(path))
            for i, (frame_id, t, path) in enumerate(
                zip(plan.frame_ids, plan.times, paths, strict=True)
            )
        ],
    )
    validate_json("media_manifest", manifest.model_dump(mode="json"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.sample_video",
        description="Deterministically sample frames (and an optional clip) from one camera.",
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--out", required=True, type=Path, help="frames go to OUT/<camera-id>/")
    parser.add_argument("--fps", type=float, default=1.0, help="candidate sample rate (Hz)")
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--start", type=float, default=0.0, help="window start (s)")
    parser.add_argument("--end", type=float, default=None, help="window end (s), exclusive")
    parser.add_argument("--clip", action="store_true", help="also write clip.mp4 of the window")
    parser.add_argument("--jpeg-quality", type=int, default=3, help="ffmpeg -q:v, 2 (best)..31")
    parser.add_argument("--max-width", type=int, default=768)
    args = parser.parse_args(argv)
    try:
        manifest = sample_video(
            args.video,
            args.camera_id,
            out_dir=args.out,
            sample_fps=args.fps,
            max_frames=args.max_frames,
            start_s=args.start,
            end_s=args.end,
            clip=args.clip,
            jpeg_quality=args.jpeg_quality,
            max_width=args.max_width,
        )
    except (ValueError, FileNotFoundError, MediaToolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(manifest_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage three synchronised warehouse segments as blind-spot clips ``bs_01..bs_03``.

Source: the operator's warehouse cameras (``Camera_0000..0019.mp4``, 1920x1080, 30 fps,
300 s, time-synchronised). The USB drive may be unplugged at any time, so the chosen
sources are copied to a local folder first (``/home/dell/factory-safety-agent/blind_spot``)
and every segment is cut from that local copy.

Each clip goes to the SAME clip store as the hazard clips:

* ``data/hazards/clips/<clip_id>/source.mp4`` -- a 15 s cut at the shared start time,
  re-encoded to browser H.264 (yuv420p, +faststart, no audio) at the source resolution
  and frame rate (the hazard clips are 1920x1080 H.264 too);
* ``data/hazards/clips/<clip_id>/clip.json`` -- the hazard clip fields
  ``{clip_id, title, duration_s, fps, width, height, source_sha256}`` plus
  ``kind: "blindspot"`` and ``review_mode: "blindspot"`` (the pipeline reads the latter);
* ``data/hazards/labels/<clip_id>.json`` -- judge-only: the original camera file name,
  the segment and (when the warehouse ground truth is present) what it shows. Titles stay
  neutral ("Aisle camera 1"); the model only ever sees the clip id.

Default selection (made from the ground truth, then checked on frame grabs at 30/90/150 s):
Camera_0003 (rack aisles with a forklift), Camera_0005 (a pallet stack in open floor) and
Camera_0014 (box stacks hiding walkers), all from 172.0 s. Those three cameras together
have the most people and vehicles entering or leaving view behind obstructions of any
visually distinct trio, and forklifts are in view in all three.

Usage::

    .venv/bin/python scripts/hazards/prepare_blindspot_clips.py
    .venv/bin/python scripts/hazards/prepare_blindspot_clips.py --cameras 3,5,14 --start 172
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hazards.scan import probe_video, save_json, sha256_file
from tools.media.binaries import ffmpeg_bin, passthrough_args, run_tool


def _load_prepare_clips() -> Any:
    """The hazard staging script's helpers (probe, copy, slot guard) without duplicating them."""
    path = Path(__file__).resolve().with_name("prepare_clips.py")
    spec = importlib.util.spec_from_file_location("_hazard_prepare_clips", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pc = _load_prepare_clips()

LOCAL_SOURCE_DIR = Path("/home/dell/factory-safety-agent/blind_spot")
DRIVE_SOURCE_DIR = Path("/media/dell/GB10_BUNDLE/blind_spot")
GROUND_TRUTH = Path(
    "/home/dell/factory-safety-agent/data/smartspaces/Warehouse_000/ground_truth.json"
)
DATASET_NAME = "Warehouse_000"
DEFAULT_CAMERAS = ("Camera_0003", "Camera_0005", "Camera_0014")
DEFAULT_START_S = 172.0
DEFAULT_DURATION_S = 15.0
CLIP_PREFIX = "bs_"
TITLE = "Aisle camera {n}"
KIND = "blindspot"
REVIEW_MODE = "blindspot"
MIN_BOX_PX = 40 * 40  # ground-truth boxes smaller than this are too small to count as "in view"


def camera_name(entry: str) -> str:
    """``"3"`` / ``"0003"`` / ``"Camera_0003"`` / ``"Camera_0003.mp4"`` -> ``"Camera_0003"``."""
    stem = entry.strip().removesuffix(".mp4")
    if stem.isdigit():
        return f"Camera_{int(stem):04d}"
    if not stem.startswith("Camera_") or not stem[7:].isdigit():
        raise SystemExit(f"unknown camera {entry!r}; use e.g. 3 or Camera_0003")
    return stem


def ensure_local(camera: str, local_dir: Path, drive_dir: Path) -> Path:
    """The camera's local copy, copied (verified) from the drive when it is missing."""
    local = local_dir / f"{camera}.mp4"
    drive = drive_dir / f"{camera}.mp4"
    if local.is_file() and (not drive.is_file() or drive.stat().st_size == local.stat().st_size):
        return local
    if not drive.is_file():
        raise SystemExit(f"{camera}.mp4 is neither in {local_dir} nor on the drive")
    print(f"  copying {camera}.mp4 to {local_dir}")
    pc.copy_verified(drive, local)
    return local


def cut_segment(src: Path, dest: Path, *, start_s: float, frames: int) -> dict[str, Any]:
    """``frames`` frames from ``start_s`` as browser H.264 at the source size and rate."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.mp4")
    ffmpeg = ffmpeg_bin()
    run_tool(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        + ["-ss", f"{start_s:.3f}", "-i", str(src), "-frames:v", str(frames)]
        + ["-map", "0:v:0", "-an", *passthrough_args(ffmpeg)]
        + ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast"]
        + ["-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
        what=f"segment cut of {src.name}",
        timeout_s=600,
    )
    probe = probe_video(tmp)
    if probe["codec"] != "h264" or probe["pix_fmt"] != "yuv420p":
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"{src.name} segment is not browser H.264: {probe}")
    if probe["frames"] != frames:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"{src.name} segment has {probe['frames']} frames, expected {frames}")
    tmp.replace(dest)
    return probe


def ground_truth_summary(
    truth: dict[str, list[dict[str, Any]]] | None, camera: str, start_frame: int, frames: int
) -> dict[str, Any] | None:
    """What the (judge-only) synthetic ground truth shows in this camera's segment."""
    if truth is None:
        return None
    seen: dict[str, set[int]] = {}
    previous: set[tuple[str, int]] = set()
    changes = 0
    for n in range(start_frame, start_frame + frames):
        now = set()
        for obj in truth.get(str(n), []):
            box = (obj.get("2d bounding box visible") or {}).get(camera)
            if box and (box[2] - box[0]) * (box[3] - box[1]) >= MIN_BOX_PX:
                now.add((obj["object type"], int(obj["object id"])))
        if n > start_frame:
            changes += len(now ^ previous)
        previous = now
        for kind, oid in now:
            seen.setdefault(kind, set()).add(oid)
    return {
        "in_view": {kind: len(ids) for kind, ids in sorted(seen.items())},
        "enter_or_leave_view_events": changes,
        "note": f"objects with a visible box of at least {MIN_BOX_PX} px in this camera",
    }


def load_ground_truth(path: Path | None) -> dict[str, list[dict[str, Any]]] | None:
    if path is None or not path.is_file():
        return None
    print(f"  reading ground truth {path.name} (judge-only)")
    return json.loads(path.read_text())


def already_staged(
    data_dir: Path, clip_id: str, *, camera: str, start_s: float, frames: int
) -> bool:
    """The slot already holds this exact segment (re-encoding again would change the sha)."""
    clip_path = data_dir / "clips" / clip_id / "clip.json"
    label_path = data_dir / "labels" / f"{clip_id}.json"
    source = data_dir / "clips" / clip_id / "source.mp4"
    if not (clip_path.is_file() and label_path.is_file() and source.is_file()):
        return False
    clip = json.loads(clip_path.read_text())
    label = json.loads(label_path.read_text())
    segment = label.get("segment") or {}
    return (
        label.get("original_name") == f"{camera}.mp4"
        and segment.get("start_s") == start_s
        and segment.get("frames") == frames
        and clip.get("review_mode") == REVIEW_MODE
        and sha256_file(source) == clip.get("source_sha256")
    )


def stage_clip(
    data_dir: Path,
    *,
    clip_id: str,
    title: str,
    src: Path,
    camera: str,
    start_s: float,
    frames: int,
    truth: dict[str, list[dict[str, Any]]] | None,
    sync_group: str,
    force: bool,
) -> dict[str, Any]:
    clip_dir = data_dir / "clips" / clip_id
    if not force and already_staged(
        data_dir, clip_id, camera=camera, start_s=start_s, frames=frames
    ):
        print(f"  {clip_id} already holds {frames} frames of this camera from {start_s:g} s")
        return json.loads((clip_dir / "clip.json").read_text())
    work = clip_dir / "source.next.mp4"
    cut_segment(src, work, start_s=start_s, frames=frames)
    info = pc.probe_clip(work)
    if info is None or info.frames != frames:
        work.unlink(missing_ok=True)
        raise SystemExit(f"{clip_id}: the cut does not decode cleanly")
    sha = sha256_file(work)
    try:
        pc.guard_clip_slot(data_dir, clip_id, sha, force)
    except SystemExit:
        work.unlink(missing_ok=True)
        raise
    work.replace(clip_dir / "source.mp4")
    clip = {
        "clip_id": clip_id,
        "title": title,
        "duration_s": info.duration_s,
        "fps": info.fps,
        "width": info.width,
        "height": info.height,
        "source_sha256": sha,
        "kind": KIND,
        "review_mode": REVIEW_MODE,
    }
    save_json(clip_dir / "clip.json", clip)
    fps = info.fps
    start_frame = round(start_s * fps)
    label = {
        "dataset_label": f"{DATASET_NAME} {camera}, {start_s:g}-{start_s + frames / fps:g} s",
        "dataset_split": DATASET_NAME,
        "original_name": f"{camera}.mp4",
        "source_sha256": sha,
        "kind": KIND,
        "segment": {
            "start_s": start_s,
            "start_frame": start_frame,
            "frames": frames,
            "end_s": round(start_s + frames / fps, 3),
            "sync_group": sync_group,
            "source_file_sha256": sha256_file(src),
        },
        "ground_truth": ground_truth_summary(truth, camera, start_frame, frames),
    }
    (data_dir / "labels").mkdir(parents=True, exist_ok=True)
    save_json(data_dir / "labels" / f"{clip_id}.json", label)
    return clip


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--cameras",
        default=",".join(DEFAULT_CAMERAS),
        help="three cameras, e.g. 3,5,14 or Camera_0003,... (default: %(default)s)",
    )
    parser.add_argument("--start", type=float, default=DEFAULT_START_S, help="shared start, s")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S, help="seconds")
    parser.add_argument("--data-dir", type=Path, default=None, help="default $HAZARDS_DIR")
    parser.add_argument("--local-dir", type=Path, default=LOCAL_SOURCE_DIR)
    parser.add_argument("--drive-dir", type=Path, default=DRIVE_SOURCE_DIR)
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH)
    parser.add_argument("--no-ground-truth", action="store_true")
    parser.add_argument("--fps", type=float, default=30.0, help="source frame rate")
    parser.add_argument("--force", action="store_true", help="replace a different staged video")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cameras = [camera_name(c) for c in args.cameras.split(",") if c.strip()]
    if len(cameras) != len(set(cameras)) or not cameras:
        raise SystemExit("pass distinct cameras")
    if not 2 / args.fps <= args.duration <= 60:
        raise SystemExit("duration must be between 2 frames and 60 s")
    data_dir = args.data_dir or pc.default_data_dir()
    frames = round(args.duration * args.fps)
    sync_group = f"{DATASET_NAME.lower()}_t{args.start:g}"
    truth = None if args.no_ground_truth else load_ground_truth(args.ground_truth)
    for n, camera in enumerate(cameras, 1):
        clip_id = f"{CLIP_PREFIX}{n:02d}"
        src = ensure_local(camera, args.local_dir, args.drive_dir)
        clip = stage_clip(
            data_dir,
            clip_id=clip_id,
            title=TITLE.format(n=n),
            src=src,
            camera=camera,
            start_s=args.start,
            frames=frames,
            truth=truth,
            sync_group=sync_group,
            force=args.force,
        )
        print(f"  {clip_id} {clip['title']} {clip['duration_s']}s {clip['width']}x{clip['height']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

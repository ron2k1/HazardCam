"""Media path and URL conventions shared by the API routes and the run harness.

Sampled frames for a run live at ``<run_dir>/frames/<camera_id>/<index:04d>.jpg``
where ``index`` is ``FrameRef.index``; ``frame_url`` is the API path the
``camera.frames.sampled`` payload should carry for each frame.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

FRAMES_DIRNAME = "frames"
# One URL/path segment: no separators, no leading dot (so never "." or "..").
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def frames_dir(run_dir: Path, camera_id: str) -> Path:
    return run_dir / FRAMES_DIRNAME / camera_id


def frame_filename(index: int) -> str:
    return f"{index:04d}.jpg"


def frame_url(run_id: str, camera_id: str, index: int) -> str:
    return f"/media/runs/{quote(run_id, safe='')}/frames/{quote(camera_id, safe='')}/{index}.jpg"


def is_safe_segment(value: str) -> bool:
    return bool(SAFE_SEGMENT_RE.match(value))


def video_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"

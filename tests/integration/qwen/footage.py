"""Real-footage helpers for live-model tests: pick a clip, extract frames with ffmpeg.

App-side frame sampling belongs to ``tools/sample_video.py`` (P04); these tests call
ffmpeg directly so they do not depend on it. Only model-input camera clips are ever
read here; the hidden ground-truth clip is never opened.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from apps.api.schemas import REPO_ROOT, MediaManifest, ModelScenarioView, Scenario
from inference.health import check_endpoint
from inference.profiles import EndpointConfig

SCENARIO_FILE = REPO_ROOT / "data" / "manifests" / "scenario_001.json"
MEVA_FALLBACK = Path.home() / "aum-data" / "raw" / "smoke" / "ex003-close-trunk.mp4"
FRAMES_PER_CLIP = 8
EXTRACT_WIDTH = 768
FFMPEG_TIMEOUT_S = 60


def require_model(endpoint: EndpointConfig) -> None:
    health = check_endpoint(endpoint, env={})
    if not health.ok:
        pytest.skip(f"{endpoint.model} at {endpoint.base_url} unavailable: {health.error}")


def require_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not on PATH")


def scenario_view() -> ModelScenarioView | None:
    if not SCENARIO_FILE.is_file():
        return None
    return Scenario.model_validate_json(SCENARIO_FILE.read_text(encoding="utf-8")).model_view()


def clip_for(view: ModelScenarioView | None, camera_id: str) -> Path | None:
    if view is None:
        return None
    path = REPO_ROOT / (view.camera(camera_id).file or "")
    return path if path.is_file() else None


def first_clip() -> tuple[str, Path]:
    """``(camera_id, path)``: scenario_001's first model camera, else the MEVA smoke clip."""
    view = scenario_view()
    if view is not None:
        clip = clip_for(view, view.cameras[0].id)
        if clip is not None:
            return view.cameras[0].id, clip
    if MEVA_FALLBACK.is_file():
        return "cam_meva", MEVA_FALLBACK
    pytest.skip("no real footage: run data preparation or the MEVA smoke download")


def _probe(src: Path) -> tuple[float, float, int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate:format=duration",
            "-of",
            "default=noprint_wrappers=1",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=FFMPEG_TIMEOUT_S,
    ).stdout
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    num, den = fields["r_frame_rate"].split("/")
    return (
        float(fields["duration"]),
        float(num) / float(den),
        int(fields["width"]),
        int(fields["height"]),
    )


def extract_manifest(
    src: Path, camera_id: str, out_dir: Path, n: int = FRAMES_PER_CLIP
) -> MediaManifest:
    """``n`` frames at evenly spaced bin centres across the whole clip (no event prior)."""
    require_ffmpeg()
    duration, fps, width, height = _probe(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        t = round((i + 0.5) * duration / n, 3)
        path = out_dir / f"{i:04d}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{t}",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({EXTRACT_WIDTH},iw)':-2",
                "-q:v",
                "3",
                str(path),
            ],
            check=True,
            timeout=FFMPEG_TIMEOUT_S,
        )
        frames.append({"index": i, "frame_id": round(t * fps), "t": t, "path": str(path)})
    return MediaManifest(
        camera_id=camera_id,
        source=str(src),
        duration_s=duration,
        src_fps=fps,
        width=width,
        height=height,
        sample_fps=n / duration,
        frames=frames,
    )

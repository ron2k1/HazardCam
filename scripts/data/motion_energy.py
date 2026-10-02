#!/usr/bin/env python3
"""CPU-cheap motion-energy timelines for synchronized videos.

ffmpeg decodes each video at a low sample rate into small grayscale frames
piped as raw bytes; numpy computes the mean absolute frame difference. A 5
minute 1080p30 clip at 2 fps / 320 px wide takes seconds and a few MB of RAM.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


@dataclass
class Timeline:
    camera: str
    fps: float
    t0: float  # scenario time of sample 0 (seconds)
    energy: np.ndarray  # raw mean |diff| per sample (sample 0 = 0)

    @property
    def times(self) -> np.ndarray:
        return self.t0 + np.arange(len(self.energy)) / self.fps

    def robust_z(self) -> np.ndarray:
        """Per-camera normalization: (e - median) / (1.4826 * MAD)."""
        e = self.energy[1:] if len(self.energy) > 1 else self.energy
        med = float(np.median(e))
        mad = float(np.median(np.abs(e - med))) * 1.4826
        scale = mad if mad > 1e-6 else (float(np.std(e)) or 1.0)
        z = (self.energy - med) / scale
        if len(z):
            z[0] = 0.0
        return z


def decode_gray(
    video: Path, fps: float, width: int = 320, start_s: float = 0.0, duration_s: float | None = None
) -> np.ndarray:
    """Return (N, H, W) uint8 grayscale frames sampled at `fps`."""
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    w0, h0 = (int(x) for x in probe.stdout.strip().split(",")[:2])
    height = round(h0 * width / w0 / 2) * 2
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", str(video)]
    if duration_s is not None:
        cmd += ["-t", f"{duration_s:.3f}"]
    cmd += [
        "-vf",
        f"fps={fps},scale={width}:{height}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(out) // (width * height)
    return np.frombuffer(out[: n * width * height], dtype=np.uint8).reshape(n, height, width)


def frame_diff_energy(frames: np.ndarray, blur: int = 5) -> np.ndarray:
    """Mean absolute difference between consecutive (box-blurred) frames, 0..255 scale."""
    if len(frames) == 0:
        return np.zeros(0)
    f = frames.astype(np.float32)
    if blur > 1:
        import cv2

        f = np.stack([cv2.blur(x, (blur, blur)) for x in f])
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    return np.concatenate([[0.0], d])


def timeline_for(
    video: Path,
    camera: str,
    fps: float,
    t0: float = 0.0,
    width: int = 320,
    start_s: float = 0.0,
    duration_s: float | None = None,
) -> Timeline:
    frames = decode_gray(video, fps, width, start_s, duration_s)
    return Timeline(camera=camera, fps=fps, t0=t0 + start_s, energy=frame_diff_energy(frames))


def resample(tl: Timeline, grid: np.ndarray, z: bool = True) -> np.ndarray:
    """Values of a timeline on a common scenario-time grid (nearest sample, NaN outside)."""
    vals = tl.robust_z() if z else tl.energy
    idx = np.rint((grid - tl.t0) * tl.fps).astype(int)
    out = np.full(len(grid), np.nan)
    ok = (idx >= 0) & (idx < len(vals))
    out[ok] = vals[idx[ok]]
    return out


def best_lag(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[int, float]:
    """Lag (in samples) maximizing the normalized cross-correlation of b shifted vs a."""
    best = (0, -1.0)
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = a[lag:], b[: len(b) - lag] if lag else b
        else:
            x, y = a[: len(a) + lag], b[-lag:]
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 8:
            continue
        xs, ys = x[m] - x[m].mean(), y[m] - y[m].mean()
        den = float(np.sqrt((xs**2).sum() * (ys**2).sum()))
        r = float((xs * ys).sum() / den) if den > 0 else 0.0
        if r > best[1]:
            best = (lag, r)
    return best

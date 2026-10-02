"""Generated test media for the P04 sampler.

These videos are GENERATED TEST MEDIA (ffmpeg lavfi sources), used only to unit-test
deterministic code; they are never scenario data. Each one encodes its source frame number n
as a 10-bit code: the picture is split into 10 vertical bands and band b is white when bit b
of n is set. The code survives H.264, JPEG and downscaling, so a test can prove exactly which
source frame a JPEG (or clip frame) came from.
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.media.binaries import (
    MediaToolError,
    ffmpeg_bin,
    ffprobe_bin,
    passthrough_args,
    run_tool,
)

CODE_BITS = 10
_CODE_GEQ = "geq=lum='if(mod(floor(N/pow(2\\,floor(X*10/W)))\\,2)\\,235\\,16)':cb=128:cr=128"
_X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def _have_ffmpeg() -> bool:
    try:
        ffmpeg_bin()
        ffprobe_bin()
    except MediaToolError:
        return False
    return True


HAVE_FFMPEG = _have_ffmpeg()


@pytest.fixture(autouse=True)
def _skip_media_without_ffmpeg(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("media") and not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not available (set FFMPEG_BIN / FFPROBE_BIN)")


def _coded_source(fps: int, seconds: float, size: str = "320x240") -> str:
    return f"color=c=black:s={size}:r={fps}:d={seconds},format=yuv420p,{_CODE_GEQ}"


def _ffmpeg(*args: str) -> None:
    run_tool(
        [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
        what="generate test media",
    )


def code_of(image: np.ndarray) -> int:
    """Frame number encoded in a grayscale image by the generator above."""
    h, w = image.shape
    code = 0
    for bit in range(CODE_BITS):
        x0, x1 = bit * w // CODE_BITS, (bit + 1) * w // CODE_BITS
        inner = image[h // 4 : 3 * h // 4, x0 + (x1 - x0) // 4 : x1 - (x1 - x0) // 4]
        if inner.mean() > 128:
            code |= 1 << bit
    return code


@pytest.fixture(scope="session")
def read_code() -> Callable[[Path | np.ndarray], int]:
    """Decode the frame code from a JPEG path or a grayscale array."""

    def _read(source: Path | np.ndarray) -> int:
        if isinstance(source, np.ndarray):
            return code_of(source.astype(np.float64))
        return code_of(np.asarray(Image.open(source).convert("L"), dtype=np.float64))

    return _read


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not available")
    return tmp_path_factory.mktemp("generated_media")


@pytest.fixture(scope="session")
def make_cfr(media_dir: Path) -> Callable[[int, float], Path]:
    """CFR H.264 mp4 (with B-frames) of ``seconds`` at integer ``fps``; frame n shows code n."""
    cache: dict[tuple[int, float], Path] = {}

    def _make(fps: int, seconds: float = 4.0) -> Path:
        if (fps, seconds) not in cache:
            out = media_dir / f"cfr_{fps}fps_{seconds}s.mp4"
            _ffmpeg("-f", "lavfi", "-i", _coded_source(fps, seconds), *_X264, str(out))
            cache[(fps, seconds)] = out
        return cache[(fps, seconds)]

    return _make


@pytest.fixture(scope="session")
def vfr_video(media_dir: Path) -> tuple[Path, list[Fraction]]:
    """VFR mp4: frames 0..29 every 1/30 s, then frames 30..89 every 1/10 s from t=1.0.
    Returns the path and the exact pts of every source frame."""
    out = media_dir / "vfr.mp4"
    warp = "setpts='if(lt(N\\,30)\\,N/30\\,1+(N-30)/10)/TB'"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"{_coded_source(30, 3)},{warp}",
        *passthrough_args(ffmpeg_bin()),
        *_X264,
        str(out),
    )
    pts = [Fraction(n, 30) if n < 30 else 1 + Fraction(n - 30, 10) for n in range(90)]
    return out, pts


@pytest.fixture(scope="session")
def offset_video(media_dir: Path) -> Path:
    """10 fps, 3 s of video starting at media time 0.5 s behind 4 s of audio."""
    out = media_dir / "offset.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=4",
        "-itsoffset",
        "0.5",
        "-f",
        "lavfi",
        "-i",
        _coded_source(10, 3),
        "-map",
        "1:v",
        "-map",
        "0:a",
        *_X264,
        "-c:a",
        "aac",
        str(out),
    )
    return out


@pytest.fixture(scope="session")
def rotated_video(media_dir: Path, make_cfr: Callable[[int, float], Path]) -> Path:
    """The 25 fps video with a 90 degree display-matrix rotation (stream copy)."""
    out = media_dir / "rotated.mp4"
    try:
        _ffmpeg("-display_rotation", "90", "-i", str(make_cfr(25, 4.0)), "-c", "copy", str(out))
    except MediaToolError as exc:  # -display_rotation needs ffmpeg >= 6.1
        pytest.skip(f"this ffmpeg cannot write rotation metadata: {exc}")
    return out


@pytest.fixture(scope="session")
def audio_only(media_dir: Path) -> Path:
    out = media_dir / "audio_only.m4a"
    _ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", "aac", str(out))
    return out

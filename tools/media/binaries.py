"""Locate and run ffmpeg/ffprobe.

Binaries come from ``$FFMPEG_BIN`` / ``$FFPROBE_BIN`` when set (a path or a command name),
otherwise from ``PATH``. Every call uses an argument list (never a shell), closes stdin so a
harness thread can never block on it, and has a timeout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache

DEFAULT_TIMEOUT_S = 600.0
_STDERR_TAIL = 2000


class MediaToolError(RuntimeError):
    """ffmpeg/ffprobe is missing, failed, or produced output that breaks a sampler invariant."""


def _resolve(name: str, env_var: str) -> str:
    override = os.environ.get(env_var, "").strip()
    if override:
        found = shutil.which(override)
        if found is None:
            raise MediaToolError(f"{env_var}={override!r} is not an executable {name}")
        return found
    found = shutil.which(name)
    if found is None:
        raise MediaToolError(
            f"{name} not found on PATH; install ffmpeg (it ships {name}) "
            f"or set {env_var} to the binary"
        )
    return found


def ffmpeg_bin() -> str:
    return _resolve("ffmpeg", "FFMPEG_BIN")


def ffprobe_bin() -> str:
    return _resolve("ffprobe", "FFPROBE_BIN")


def run_tool(
    args: list[str], *, what: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """Run ``args``; raise ``MediaToolError`` (with the stderr tail) on failure or timeout."""
    try:
        proc = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"{what} timed out after {timeout_s:.0f}s") from exc
    except OSError as exc:
        raise MediaToolError(f"{what}: could not start {args[0]!r}: {exc}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.strip()[-_STDERR_TAIL:]
        raise MediaToolError(f"{what} failed (exit {proc.returncode}): {tail}")
    return proc


def parse_ffmpeg_version(banner: str) -> tuple[int, int] | None:
    """``(major, minor)`` from ``ffmpeg -version`` output; None for git builds (``N-1234-g..``)."""
    match = re.search(r"ffmpeg version n?(\d+)\.(\d+)", banner)
    return (int(match.group(1)), int(match.group(2))) if match else None


@lru_cache(maxsize=8)
def passthrough_args(ffmpeg: str) -> tuple[str, ...]:
    """Output option that writes each filtered frame exactly once (no CFR dup/drop).

    ``-fps_mode`` exists from ffmpeg 5.1; older distro builds (Ubuntu 22.04 ships 4.4) only
    know the now-deprecated ``-vsync``. Unparseable versions are git builds, i.e. recent.
    """
    banner = run_tool([ffmpeg, "-hide_banner", "-version"], what="ffmpeg -version").stdout
    version = parse_ffmpeg_version(banner)
    if version is not None and version < (5, 1):
        return ("-vsync", "passthrough")
    return ("-fps_mode", "passthrough")

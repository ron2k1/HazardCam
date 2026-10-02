"""Frame selection, image encoding and prompt-size estimates for vision requests."""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

from PIL import Image

from apps.api.schemas import REPO_ROOT, FrameRef

CHARS_PER_TOKEN = 3  # conservative for prompt text + JSON
FRAME_LABEL_TOKENS = 16
JPEG_QUALITY = 85


def uniform_subset(items: list[Any], k: int) -> list[Any]:
    """``k`` evenly spaced items, always keeping the first and last when ``k >= 2``."""
    n = len(items)
    if k >= n:
        return list(items)
    if k <= 0:
        return []
    if k == 1:
        return [items[n // 2]]
    return [items[int(i * (n - 1) / (k - 1) + 0.5)] for i in range(k)]


def frame_label(frame: FrameRef) -> str:
    return f"Frame index={frame.index} t={frame.t:.2f}s"


def text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def image_tokens(width: int, height: int, px: int) -> int:
    """Rough visual-token cost (Qwen-VL family: 16 px patches merged 2x2 -> 32 px).

    Measured on Ollama qwen3-vl:4b-instruct: 768x432 ~ 355 tokens, 512x288 ~ 155.
    """
    return math.ceil(width / px) * math.ceil(height / px) + 2


def resolve_frame_path(path: str | None) -> Path | None:
    """Absolute paths as-is; relative paths against the repo root, then the CWD."""
    if not path:
        return None
    p = Path(path)
    for candidate in (p,) if p.is_absolute() else (REPO_ROOT / p, Path.cwd() / p):
        if candidate.is_file():
            return candidate
    return None


def encode_image(path: Path, max_width: int | None) -> tuple[str, int, int]:
    """``(data_url, width, height)``; downscales frames wider than ``max_width``."""
    with Image.open(path) as im:
        w, h = im.size
        fmt = (im.format or "").upper()
        if max_width and w > max_width:
            h = max(1, round(h * max_width / w))
            w = max_width
            data = _jpeg_bytes(im.convert("RGB").resize((w, h), Image.Resampling.LANCZOS))
            mime = "image/jpeg"
        elif fmt in ("JPEG", "PNG"):
            data, mime = path.read_bytes(), f"image/{fmt.lower()}"
        else:
            data, mime = _jpeg_bytes(im.convert("RGB")), "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", w, h


def _jpeg_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()

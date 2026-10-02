"""Lenient scalar coercion for model JSON (numbers as strings, percents, word scores)."""

from __future__ import annotations

import math
import re
from typing import Any

DEFAULT_CONFIDENCE = 0.5
_WORD_CONFIDENCE = {"high": 0.8, "medium": 0.5, "moderate": 0.5, "low": 0.3}
_INT_TEXT = re.compile(r"\s*(?:frame\s*)?#?\s*(\d+)\s*", re.IGNORECASE)


def as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        m = _INT_TEXT.fullmatch(v)
        return int(m.group(1)) if m else None
    return None


def as_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        try:
            x = float(v.strip().rstrip("s%").strip())
        except ValueError:
            return None
        return x if math.isfinite(x) else None
    return None


def coerce_confidence(v: Any, default: float = DEFAULT_CONFIDENCE) -> float:
    """Clamp to [0, 1]; ``85``/``"85%"`` -> 0.85 (grammars do not enforce numeric ranges)."""
    if isinstance(v, str) and v.strip().lower() in _WORD_CONFIDENCE:
        return _WORD_CONFIDENCE[v.strip().lower()]
    x = as_float(v)
    if x is None:
        return default
    if (isinstance(v, str) and v.strip().endswith("%")) or 1 < x <= 100:
        x /= 100
    return min(1.0, max(0.0, x))

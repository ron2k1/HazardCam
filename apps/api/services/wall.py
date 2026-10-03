"""The home camera wall (``GET /api/wall``): which clips fill the six CCTV tiles.

``config/wall.yaml`` (editable without code) names them:

- ``hazard_clips``: CAM 1-3, factory clips (clip kind ``hazard``). Empty or missing: the
  first three hazard clips by id.
- ``blindspot_clips``: CAM 4-6, warehouse clips (clip kind ``blindspot``). Empty or
  missing: every blind-spot clip, in id order (at most three).
- titles and the staggered check start times (seconds after the wall loads).

Clips come from the same clip store as ``/hazards`` (``$HAZARDS_DIR/clips``); a configured
id that is not staged is skipped. Tiles carry only neutral clip ids and titles plus the
raw ``source.mp4`` route (no AI markings, no results).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from apps.api.schemas import REPO_ROOT
from apps.api.services.hazards import HazardService, media_base

logger = logging.getLogger(__name__)

DEFAULT_WALL_CONFIG = REPO_ROOT / "config" / "wall.yaml"
TILES_PER_ROW = 3
DEFAULT_WALL: dict[str, Any] = {
    "title": "Site cameras · Factory floor",
    "hazard_title": "Hazard watch",
    "blindspot_title": "Blind spot watch · Warehouse",
    "hazard_watch_label": "HAZARD WATCH",
    "blindspot_watch_label": "BLIND SPOT",
    "hazard_clips": [],
    "blindspot_clips": [],
    "hazard_check_after_s": [2.0, 5.0, 8.0],
    "blindspot_check_after_s": [3.5, 6.5, 9.5],
}


def load_wall_config(path: Path | None = None) -> dict[str, Any]:
    """``config/wall.yaml`` over :data:`DEFAULT_WALL`; never raises."""
    config = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_WALL.items()}
    path = DEFAULT_WALL_CONFIG if path is None else path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        if not isinstance(exc, FileNotFoundError):
            logger.warning("wall config %s unreadable; using defaults: %s", path, exc)
        return config
    if not isinstance(raw, dict):
        return config
    for key, default in DEFAULT_WALL.items():
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(default, str) and isinstance(value, str) and value.strip():
            config[key] = value.strip()
        elif key.endswith("_clips") and isinstance(value, list):
            config[key] = [str(v).strip() for v in value if str(v).strip()]
        elif key.endswith("_after_s") and isinstance(value, list):
            nums = [float(v) for v in value if isinstance(v, int | float) and v >= 0]
            if nums:
                config[key] = nums
    return config


def _pick(
    clips: Sequence[Mapping[str, Any]], kind: str, wanted: Sequence[str]
) -> list[Mapping[str, Any]]:
    of_kind = [c for c in clips if c.get("kind") == kind]
    if wanted:
        by_id = {c["clip_id"]: c for c in of_kind}
        chosen = [by_id[i] for i in wanted if i in by_id]
    else:
        chosen = of_kind
    return chosen[:TILES_PER_ROW]


def _tiles(
    chosen: Sequence[Mapping[str, Any]],
    *,
    first_cam: int,
    kind: str,
    watch: str,
    after: Sequence[float],
) -> list[dict[str, Any]]:
    tiles = []
    for i, clip in enumerate(chosen):
        cam = first_cam + i
        delay = after[i] if i < len(after) else (after[-1] + 5.0 * (i - len(after) + 1))
        tiles.append(
            {
                "cam": cam,
                "label": f"CAM {cam}",
                "watch": watch,
                "kind": kind,
                "clip_id": clip["clip_id"],
                "title": clip["title"],
                "duration_s": clip.get("duration_s", 0.0),
                "source_url": f"{media_base(clip['clip_id'])}/source.mp4",
                "check_after_s": delay,
            }
        )
    return tiles


def compose_wall(clips: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    """``GET /api/wall``. Pure: ``clips`` are the store's clip records (with ``kind``)."""
    hazard = _pick(clips, "hazard", config["hazard_clips"])
    blindspot = _pick(clips, "blindspot", config["blindspot_clips"])
    return {
        "title": config["title"],
        "hazard_title": config["hazard_title"],
        "blindspot_title": config["blindspot_title"],
        "hazard_tiles": _tiles(
            hazard,
            first_cam=1,
            kind="hazard",
            watch=config["hazard_watch_label"],
            after=config["hazard_check_after_s"],
        ),
        "blindspot_tiles": _tiles(
            blindspot,
            first_cam=1 + TILES_PER_ROW,
            kind="blindspot",
            watch=config["blindspot_watch_label"],
            after=config["blindspot_check_after_s"],
        ),
    }


def wall(service: HazardService, config_path: Path | None = None) -> dict[str, Any]:
    return compose_wall(service.clips(), load_wall_config(config_path))

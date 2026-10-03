"""Scenario manifests: load, validate, and render judge-safe public views.

Every ``data/manifests/*.json`` (except ``*.provenance.json``) is validated with
``Scenario``; invalid manifests are skipped with a warning. Public responses are
built from ``Scenario.model_view()`` and never carry the ground-truth camera id
or file path. Judge-only data has its own renderer, used only by the judge routes.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from apps.api.schemas import Camera, Scenario

from .alert_messages import camera_display_names, scenario_start_wallclock
from .gt_guard import GtGuard

logger = logging.getLogger(__name__)

PROVENANCE_SUFFIX = ".provenance.json"
# Scalar provenance fields that are safe to show next to a scenario (attribution).
PUBLIC_PROVENANCE_KEYS = (
    "kind",
    "source",
    "dataset",
    "dataset_url",
    "url",
    "source_url",
    "license",
    "license_url",
    "attribution",
    "citation",
    "note",
)


@dataclass(frozen=True)
class LoadedScenario:
    scenario: Scenario
    manifest_path: Path
    guard: GtGuard

    @property
    def id(self) -> str:
        return self.scenario.id


def camera_media_url(scenario_id: str, camera_id: str) -> str:
    return f"/media/scenarios/{quote(scenario_id, safe='')}/cameras/{quote(camera_id, safe='')}"


def judge_video_url(scenario_id: str) -> str:
    return f"/api/judge/scenarios/{quote(scenario_id, safe='')}/video"


class ScenarioStore:
    """Caches validated scenarios; reloads when the manifest directory changes."""

    def __init__(self, manifests_dir: Path, media_root: Path, prepared_dir: Path) -> None:
        self.manifests_dir = manifests_dir
        self.media_root = media_root
        self.prepared_dir = prepared_dir
        self._lock = threading.Lock()
        self._signature: object = None
        self._items: dict[str, LoadedScenario] = {}
        self.invalid: list[str] = []

    def _manifest_files(self) -> list[Path]:
        if not self.manifests_dir.is_dir():
            return []
        return sorted(
            p
            for p in self.manifests_dir.glob("*.json")
            if p.is_file() and not p.name.endswith(PROVENANCE_SUFFIX)
        )

    def refresh(self) -> None:
        files = self._manifest_files()
        try:
            signature: object = tuple(
                (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files
            )
        except OSError:  # a manifest vanished mid-scan; force a reload
            signature = object()
        with self._lock:
            if signature == self._signature:
                return
            items: dict[str, LoadedScenario] = {}
            invalid: list[str] = []
            for path in files:
                try:
                    scenario = Scenario.model_validate_json(path.read_bytes())
                except (OSError, ValidationError) as exc:
                    logger.warning("skipping scenario manifest %s: %s", path.name, _short(exc))
                    invalid.append(path.name)
                    continue
                if scenario.id in items:
                    logger.warning(
                        "skipping scenario manifest %s: duplicate id %r", path.name, scenario.id
                    )
                    invalid.append(path.name)
                    continue
                items[scenario.id] = LoadedScenario(scenario, path, GtGuard.for_scenario(scenario))
            self._items, self.invalid, self._signature = items, invalid, signature

    def list(self) -> list[LoadedScenario]:
        self.refresh()
        return list(self._items.values())

    def get(self, scenario_id: str) -> LoadedScenario | None:
        self.refresh()
        return self._items.get(scenario_id)

    def media_path(self, camera: Camera) -> Path:
        path = Path(camera.file)
        return path if path.is_absolute() else self.media_root / path

    def expected_path(self, scenario_id: str) -> Path:
        return self.prepared_dir / scenario_id / "expected.json"

    # -- renderers -----------------------------------------------------------------

    def public_view(self, loaded: LoadedScenario) -> dict[str, Any]:
        """Judge-safe scenario JSON for the dashboard and any non-judge client."""
        scenario = loaded.scenario
        view = scenario.model_view()
        visible = {cam.id: cam for cam in scenario.visible_cameras}
        names = camera_display_names(cam.id for cam in view.cameras)
        start = scenario_start_wallclock(scenario.provenance)
        cameras = [
            {
                "id": cam.id,
                # The friendly name the worker view and alert messages use ("Camera B").
                "display_name": names[cam.id],
                "label": cam.label,
                "position": cam.position,
                "heading_deg": cam.heading_deg,
                "fov_deg": cam.fov_deg,
                "time_offset_s": cam.time_offset_s,
                "media_url": camera_media_url(view.id, cam.id),
                "media_available": self.media_path(visible[cam.id]).is_file(),
            }
            for cam in view.cameras
        ]
        doc = {
            "id": view.id,
            "title": view.title,
            "duration_seconds": view.duration_seconds,
            "coordinate_frame": view.coordinate_frame,
            # Wall-clock time of scenario t = 0 (ISO 8601, as recorded), or null.
            "start_wallclock": start.isoformat() if start else None,
            "cameras": cameras,
            "zones": [zone.model_dump(mode="json") for zone in view.zones],
            "has_ground_truth": True,
            "provenance": _provenance_summary(scenario.provenance),
        }
        return loaded.guard.redact_obj(doc)

    def judge_view(self, loaded: LoadedScenario) -> dict[str, Any]:
        """Ground-truth metadata for the judge comparison panel. Never model-facing."""
        scenario = loaded.scenario
        gt = scenario.ground_truth_camera
        expected_path = self.expected_path(scenario.id)
        expected = None
        if expected_path.is_file():
            try:
                expected = json.loads(expected_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("unreadable expected.json for %s: %s", scenario.id, _short(exc))
        return {
            "judge_only": True,
            "scenario_id": scenario.id,
            "ground_truth_camera": {
                "id": gt.id,
                "label": gt.label,
                "position": gt.position,
                "heading_deg": gt.heading_deg,
                "fov_deg": gt.fov_deg,
                "time_offset_s": gt.time_offset_s,
                "video_url": judge_video_url(scenario.id),
                "video_available": self.media_path(gt).is_file(),
            },
            "expected": expected,
            "provenance": scenario.provenance or {},
        }


def _provenance_summary(provenance: dict[str, Any] | None) -> dict[str, str]:
    """Whitelisted string fields only; always an object (the web types it that way)."""
    provenance = provenance or {}
    return {
        key: provenance[key]
        for key in PUBLIC_PROVENANCE_KEYS
        if isinstance(provenance.get(key), str)
    }


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()[:3]
        parts = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in errors]
        return f"{exc.error_count()} validation error(s): " + "; ".join(parts)
    return f"{type(exc).__name__}: {exc}"

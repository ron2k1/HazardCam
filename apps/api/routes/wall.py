"""``GET /api/wall``: the home camera wall's six tiles (see ``services/wall.py``), and the
site runs: one lead agent plus six concurrent camera checkers (``services/site_runs.py``).

* ``POST /api/wall/run`` ``{"mode": "live"|"replay"}``: start a site run; 202 with
  ``site_run_id``. Omitted mode: replay when the hazard service replays by default.
  503 when live mode has no lead agent, 404 when replay has no stored run (the wall
  then falls back to its six direct per-camera checks).
* ``GET /api/wall/runs/{id}``: snapshot (checkers, timings, lead trace, alerts).
* ``GET /api/wall/runs/{id}/events``: SSE ``lead`` / ``checker`` / ``alerts`` / ``done``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from apps.api.deps import get_settings
from apps.api.routes.hazards import get_hazards
from apps.api.services.hazards import DEFAULT_CONFIG_PATH, data_dir_from_env
from apps.api.services.site_runs import SiteService
from apps.api.services.wall import wall

router = APIRouter(prefix="/api", tags=["wall"])
_site_lock = threading.Lock()


class SiteRunRequest(BaseModel):
    mode: Literal["live", "replay"] | None = None


@router.get("/wall")
def camera_wall(request: Request) -> dict[str, Any]:
    """``{title, hazard_title, blindspot_title, hazard_tiles: [...], blindspot_tiles:
    [...]}``; each tile ``{cam, label, watch, kind, clip_id, title, duration_s,
    source_url, check_after_s}``. Config: ``config/wall.yaml``."""
    config_path = getattr(request.app.state, "wall_config_path", None)
    return wall(get_hazards(request), config_path)


def _replay_seconds() -> float:
    try:
        cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return float((cfg.get("demo_replay") or {}).get("total_seconds") or 12.0)
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return 12.0


def get_sites(request: Request) -> SiteService:
    state = request.app.state
    service = getattr(state, "site_runs", None)
    if service is None:
        with _site_lock:
            service = getattr(state, "site_runs", None)
            if service is None:
                hazards = get_hazards(request)
                config_path = getattr(state, "wall_config_path", None)

                def tiles() -> list[dict[str, Any]]:
                    w = wall(hazards, config_path)
                    return [*w["hazard_tiles"], *w["blindspot_tiles"]]

                service = SiteService(
                    hazards,
                    tiles,
                    getattr(state, "site_runs_root", None) or data_dir_from_env() / "site_runs",
                    lead_runner=getattr(state, "site_lead_runner", None),
                    checker_runner=getattr(state, "hazard_review_runner", None),
                    checker_runner_name=getattr(state, "hazard_review_runner_name", None),
                    replay_seconds=_replay_seconds(),
                )
                state.site_runs = service
    return service


@router.post("/wall/run", status_code=202)
def start_site_run(request: Request, body: SiteRunRequest | None = None) -> JSONResponse:
    sites = get_sites(request)
    mode = body.mode if body and body.mode else None
    if mode is None:
        mode = "replay" if sites.hazards.replays_by_default else "live"
    try:
        run = sites.start(mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return JSONResponse(
        {
            "site_run_id": run.site_run_id,
            "mode": run.mode,
            "events_url": f"/api/wall/runs/{run.site_run_id}/events",
            "cams": [{"cam": c, "clip_id": k["clip_id"]} for c, k in sorted(run.checkers.items())],
        },
        status_code=202,
    )


@router.get("/wall/runs/{site_run_id}")
def site_run(request: Request, site_run_id: str) -> dict[str, Any]:
    sites = get_sites(request)
    run = sites.run(site_run_id)
    if run is not None:
        return run.snapshot()
    stored = sites.stored(site_run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="unknown site run")
    return stored


@router.get("/wall/runs/{site_run_id}/events")
async def site_run_events(
    request: Request, site_run_id: str, last_event_id: str | None = Header(default=None)
) -> EventSourceResponse:
    run = get_sites(request).run(site_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown site run")
    try:
        start = max(int(last_event_id or 0), 0)
    except ValueError:
        start = 0

    async def messages() -> AsyncIterator[dict[str, str]]:
        async for seq, event, data in run.stream(start):
            yield {"id": str(seq), "event": event, "data": json.dumps(data)}

    return EventSourceResponse(messages(), ping=get_settings(request).sse_ping_s, sep="\n")

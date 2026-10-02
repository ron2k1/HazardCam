"""Request-scoped accessors for the objects ``create_app`` stores on ``app.state``."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from apps.api.services.media import video_media_type
from apps.api.services.runs import RunManager
from apps.api.services.scenarios import LoadedScenario, ScenarioStore
from apps.api.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_scenarios(request: Request) -> ScenarioStore:
    return request.app.state.scenarios


def get_runs(request: Request) -> RunManager:
    return request.app.state.runs


def require_scenario(request: Request, scenario_id: str) -> LoadedScenario:
    loaded = get_scenarios(request).get(scenario_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="unknown scenario")
    return loaded


def video_file(path: Path) -> FileResponse:
    """Stream a video file; Starlette's FileResponse answers Range requests with 206."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail="media file not found")
    return FileResponse(path, media_type=video_media_type(path))

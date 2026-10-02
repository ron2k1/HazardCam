"""FastAPI app factory.

Run: ``python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080``.
``app.state.executor`` is the run executor (see ``services.runs.RunExecutor``);
tests and the P10 harness swap it after ``create_app()``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import health, judge, media, runs, scenarios
from apps.api.services.fixture_executor import FixtureReplayExecutor
from apps.api.services.runs import RunManager
from apps.api.services.scenarios import ScenarioStore
from apps.api.settings import Settings

API_VERSION = "0.3.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Ambient Urban Mirror API", version=API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Accept-Ranges", "Content-Length", "Content-Range", "Location"],
    )
    app.state.settings = settings
    app.state.scenarios = ScenarioStore(
        settings.manifests_dir, settings.media_root, settings.prepared_dir
    )
    app.state.runs = RunManager(settings.runs_dir)
    app.state.executor = FixtureReplayExecutor()  # TEMPORARY until P10 installs its harness
    for module in (health, scenarios, runs, media, judge):
        app.include_router(module.router)
    return app


app = create_app()

"""Service health and model-endpoint health."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from apps.api.deps import get_scenarios, get_settings
from apps.api.services.model_health import models_health

router = APIRouter(tags=["health"])


def _binary(name: str) -> dict[str, Any]:
    found = shutil.which(name)
    return {"ok": found is not None, "path": found}


def _writable(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".healthz-"):
            pass
    except OSError as exc:
        return {"ok": False, "path": str(path), "error": type(exc).__name__}
    return {"ok": True, "path": str(path)}


@router.get("/healthz")
def healthz(request: Request) -> dict[str, Any]:
    settings, store = get_settings(request), get_scenarios(request)
    manifests_dir = store.manifests_dir
    readable = manifests_dir.is_dir() and os.access(manifests_dir, os.R_OK)
    dependencies = {
        "manifests_dir": {
            "ok": readable,
            "path": str(manifests_dir),
            "scenario_count": len(store.list()) if readable else 0,
            "invalid_manifests": list(store.invalid) if readable else [],
        },
        "ffmpeg": _binary("ffmpeg"),
        "ffprobe": _binary("ffprobe"),
        "runs_dir": _writable(settings.runs_dir),
        "profile": {
            "ok": settings.profile_config(settings.model_profile) is not None,
            "name": settings.model_profile,
        },
    }
    return {
        "status": "ok" if all(d["ok"] for d in dependencies.values()) else "degraded",
        "service": "ambient-urban-mirror-api",
        "version": request.app.version,
        "profile": settings.model_profile,
        "dependencies": dependencies,
    }


@router.get("/api/models/health")
async def api_models_health(request: Request, profile: str | None = None) -> dict[str, Any]:
    settings = get_settings(request)
    name = profile or settings.model_profile
    if settings.profile_config(name) is None:
        raise HTTPException(status_code=404, detail="unknown profile")
    return await models_health(name, settings.models_dir, settings.model_probe_timeout_s)

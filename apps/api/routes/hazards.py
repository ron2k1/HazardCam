"""Safety hazard review routes (``/hazards`` page): clips, views, review jobs, media.

Shapes: ``contracts/hazard_view.schema.json``. The service is created on first use from
the app settings (``$HAZARDS_DIR``, the active model profile); tests may set
``app.state.hazards`` before the first request.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from sse_starlette import EventSourceResponse

from apps.api.deps import get_settings, video_file
from apps.api.services.hazards import HazardService, JobConflict

router = APIRouter(prefix="/api/hazards", tags=["hazards"])

_create_lock = threading.Lock()


class ReviewRequest(BaseModel):
    """``refresh`` re-runs the model instead of using its cached answer; ``mode`` "live"
    forces a real run through the review runner even in demo replay mode ("replay" forces
    a replay of the stored run). Omitted: replay when ``HAZARDS_DEMO_REPLAY=1`` or in a
    fixture profile, else live."""

    model_config = ConfigDict(extra="forbid")

    refresh: bool = False
    mode: Literal["live", "replay"] | None = None


def get_hazards(request: Request) -> HazardService:
    service = getattr(request.app.state, "hazards", None)
    if service is None:
        with _create_lock:
            service = getattr(request.app.state, "hazards", None)
            if service is None:
                service = HazardService.from_settings(get_settings(request))
                request.app.state.hazards = service
    return service


@router.get("/clips")
def list_clips(request: Request) -> dict[str, Any]:
    return {"clips": get_hazards(request).list_clips()}


@router.get("/instructions")
def instructions(request: Request) -> dict[str, Any]:
    return get_hazards(request).instructions()


@router.get("/clips/{clip_id}/report")
def clip_report(request: Request, clip_id: str) -> dict[str, Any]:
    """The clip's current raw ``hazard_report.json`` (judge view / reasoning tab)."""
    report = get_hazards(request).report(clip_id)
    if report is None:
        raise HTTPException(status_code=404, detail="no report for this clip")
    return report


@router.get("/clips/{clip_id}/jobs/latest")
def latest_job(request: Request, clip_id: str) -> dict[str, Any]:
    """``{job_id, state, ...}`` of the clip's most recent check in this API process; 404
    when the clip is unknown or has had no check since the API started."""
    service = get_hazards(request)
    if service.store.clip(clip_id) is None:
        raise HTTPException(status_code=404, detail="unknown clip")
    job = service.latest_job(clip_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no check of this clip yet")
    return job.summary()


@router.get("/clips/{clip_id}")
def clip_view(request: Request, clip_id: str) -> dict[str, Any]:
    view = get_hazards(request).view(clip_id)
    if view is None:
        raise HTTPException(status_code=404, detail="unknown clip")
    return view


@router.post("/clips/{clip_id}/review", status_code=202)
def start_review(request: Request, clip_id: str, body: ReviewRequest | None = None) -> JSONResponse:
    # The live review runner is looked up per request: the OpenClaw agent runner that
    # agent.event_day.app:create_agent_app sets, else the direct review_clip runner.
    state = request.app.state
    runner = getattr(state, "hazard_review_runner", None)
    runner_name = getattr(state, "hazard_review_runner_name", None) if runner else None
    try:
        job = get_hazards(request).start_review(
            clip_id,
            refresh=bool(body and body.refresh),
            mode=body.mode if body else None,
            runner=runner,
            runner_name=runner_name,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown clip") from None
    except JobConflict as conflict:
        return JSONResponse(
            {"detail": "a check of this clip is already running", "job_id": conflict.job_id},
            status_code=409,
        )
    events_url = f"/api/hazards/jobs/{job.job_id}/events"
    return JSONResponse(
        {"job_id": job.job_id, "events_url": events_url, "mode": job.mode, "runner": job.runner},
        status_code=202,
    )


def _seq(value: str | None) -> int:
    try:
        return max(int(value or 0), 0)
    except ValueError:
        return 0


@router.get("/jobs/{job_id}/events")
async def job_events(
    request: Request, job_id: str, last_event_id: str | None = Header(default=None)
) -> EventSourceResponse:
    """Named SSE events ``progress`` / ``agent`` / ``done`` / ``failed`` with ``id: <seq>``.
    A late subscriber gets every event from the start of the job (or after
    ``Last-Event-ID``), then the live ones; the stream closes after the terminal event."""
    job = get_hazards(request).job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")

    async def messages() -> AsyncIterator[dict[str, str]]:
        async for seq, event, data in job.stream(_seq(last_event_id)):
            yield {"id": str(seq), "event": event, "data": json.dumps(data)}

    return EventSourceResponse(messages(), ping=get_settings(request).sse_ping_s, sep="\n")


@router.get("/clips/{clip_id}/media/{name:path}")
def clip_media(request: Request, clip_id: str, name: str) -> FileResponse:
    """``source.mp4``, ``processed.mp4``, ``evidence/E###.jpg`` (raw, as sent to the model)
    or ``evidence_clean/E###.jpg`` (worker copy without the burned-in label strip) of the
    clip's current run. Anything else is 404; FileResponse answers Range requests with 206."""
    found = get_hazards(request).media_path(clip_id, name)
    if found is None:
        raise HTTPException(status_code=404, detail="media file not found")
    path, media_type = found
    if media_type == "video/mp4":
        return video_file(path)
    return FileResponse(path, media_type=media_type)

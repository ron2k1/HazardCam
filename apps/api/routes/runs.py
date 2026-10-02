"""Run creation, run state, and the per-run SSE stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse

from apps.api.deps import get_runs, get_settings, require_scenario
from apps.api.schemas import RunRequest
from apps.api.services.runs import RunHandle

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _require_run(request: Request, run_id: str) -> RunHandle:
    handle = get_runs(request).get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return handle


def _seq(value: str | None) -> int:
    try:
        return max(int(value or 0), 0)
    except ValueError:
        return 0


@router.post("", status_code=202)
async def create_run(request: Request, body: RunRequest) -> JSONResponse:
    settings = get_settings(request)
    loaded = require_scenario(request, body.scenario_id)
    profile = body.profile or settings.model_profile
    if settings.profile_config(profile) is None:
        raise HTTPException(status_code=422, detail="unknown profile")
    pace_s = settings.default_pace_s if body.pace_s is None else body.pace_s
    handle = get_runs(request).start(loaded, profile, pace_s, request.app.state.executor)
    record = handle.public_record()
    return JSONResponse(record, status_code=202, headers={"Location": record["run_url"]})


@router.get("/{run_id}")
async def get_run(request: Request, run_id: str) -> dict[str, Any]:
    return _require_run(request, run_id).public_record()


@router.get("/{run_id}/events")
async def run_events(
    request: Request,
    run_id: str,
    after_seq: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None),
) -> EventSourceResponse:
    """Replay the log after ``max(after_seq, Last-Event-ID)``, then stream live events.

    Each message is ``id: <seq>`` + ``data: <envelope JSON>`` with no ``event:`` field;
    the stream closes after ``run.complete`` or ``run.failed``.
    """
    handle = _require_run(request, run_id)
    start = max(after_seq or 0, _seq(last_event_id))

    async def messages() -> AsyncIterator[dict[str, str]]:
        async for seq, line in handle.stream(start):
            yield {"id": str(seq), "data": line}

    return EventSourceResponse(messages(), ping=get_settings(request).sse_ping_s, sep="\n")

"""JUDGE-ONLY routes: withheld ground-truth camera metadata, expected outcome, GT video.

Only the dashboard's judge-comparison panel calls these. The harness, adapters and
the event-day agent never receive these URLs or anything they return.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from apps.api.deps import get_scenarios, require_scenario, video_file

router = APIRouter(prefix="/api/judge", tags=["judge-only"])


@router.get("/scenarios/{scenario_id}")
def judge_scenario(request: Request, scenario_id: str) -> dict[str, Any]:
    return get_scenarios(request).judge_view(require_scenario(request, scenario_id))


@router.get("/scenarios/{scenario_id}/video")
def judge_video(request: Request, scenario_id: str) -> FileResponse:
    scenario = require_scenario(request, scenario_id).scenario
    return video_file(get_scenarios(request).media_path(scenario.ground_truth_camera))

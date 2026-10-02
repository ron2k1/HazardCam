"""Visible-camera video and sampled-frame routes. The ground-truth camera is refused."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from apps.api.deps import get_runs, get_scenarios, get_settings, require_scenario, video_file
from apps.api.services.media import frame_filename, frames_dir, is_safe_segment

router = APIRouter(prefix="/media", tags=["media"])

GT_REFUSED = "the ground-truth camera is judge-only"


@router.get("/scenarios/{scenario_id}/cameras/{camera_id}")
def camera_video(request: Request, scenario_id: str, camera_id: str) -> FileResponse:
    scenario = require_scenario(request, scenario_id).scenario
    if camera_id == scenario.ground_truth_camera.id:
        raise HTTPException(status_code=403, detail=GT_REFUSED)
    camera = next((c for c in scenario.visible_cameras if c.id == camera_id), None)
    if camera is None:
        raise HTTPException(status_code=404, detail="unknown camera")
    return video_file(get_scenarios(request).media_path(camera))


def _run_gt_camera_id(request: Request, run_id: str) -> str:
    """GT camera id of the run's scenario, from memory or the run's ``run.json``."""
    handle = get_runs(request).get(run_id)
    if handle is not None:
        return handle.gt_camera_id
    record_path = get_settings(request).runs_dir / run_id / "run.json"
    try:
        scenario_id = json.loads(record_path.read_text(encoding="utf-8"))["scenario_id"]
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=404, detail="unknown run") from None
    return require_scenario(request, scenario_id).scenario.ground_truth_camera.id


@router.get("/runs/{run_id}/frames/{camera_id}/{index}.jpg")
def run_frame(
    request: Request,
    run_id: str,
    camera_id: str,
    index: int = PathParam(ge=0, le=99_999),
) -> FileResponse:
    if not (is_safe_segment(run_id) and is_safe_segment(camera_id)):
        raise HTTPException(status_code=404, detail="frame not found")
    if camera_id == _run_gt_camera_id(request, run_id):
        raise HTTPException(status_code=403, detail=GT_REFUSED)
    root = get_settings(request).runs_dir.resolve()
    path = (frames_dir(root / run_id, camera_id) / frame_filename(index)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(path, media_type="image/jpeg")

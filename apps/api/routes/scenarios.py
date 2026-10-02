"""Public scenario routes. Responses never contain the ground-truth camera id or path."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.api.deps import get_scenarios, require_scenario

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios(request: Request) -> dict[str, Any]:
    store = get_scenarios(request)
    return {"scenarios": [store.public_view(loaded) for loaded in store.list()]}


@router.get("/{scenario_id}")
def get_scenario(request: Request, scenario_id: str) -> dict[str, Any]:
    return get_scenarios(request).public_view(require_scenario(request, scenario_id))

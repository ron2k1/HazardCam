"""``GET /api/runtime/status``: the local stack (NemoClaw sandbox, OpenClaw agent,
OpenShell gateway, tool server, Qwen, detector, network) as plain status rows.

See ``apps/api/services/runtime_status.py``. The prober is created on first use and
cached on ``app.state.runtime_status`` (tests may set it before the first request).
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Request

from apps.api.deps import get_settings
from apps.api.services.runtime_status import RuntimeStatus

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

_create_lock = threading.Lock()


def get_runtime_status(request: Request) -> RuntimeStatus:
    prober = getattr(request.app.state, "runtime_status", None)
    if prober is None:
        with _create_lock:
            prober = getattr(request.app.state, "runtime_status", None)
            if prober is None:
                prober = RuntimeStatus(profile=get_settings(request).model_profile)
                request.app.state.runtime_status = prober
    return prober


@router.get("/status")
def runtime_status(request: Request) -> dict[str, Any]:
    """``{checked_at, local_only, rows: [{key, label, status, value, detail}]}``; cached
    for 15 s; never fails (a probe that errors reports "unknown")."""
    return get_runtime_status(request).status(request.app.state)

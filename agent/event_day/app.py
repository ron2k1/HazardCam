"""The API with the OpenClaw agent as its run executor (event day, D01).

    uvicorn --factory agent.event_day.app:create_agent_app --host 127.0.0.1 --port 8088

``create_agent_app`` builds the normal API (``apps.api.main.create_app``), starts the
``mirror`` MCP server in the same process, and swaps ``app.state.executor`` for
``OpenClawAgentExecutor``. Settings come from the environment:

- ``AUM_OPENCLAW_CMD``: the command that runs the ``openclaw`` CLI, split like a shell
  line. Inside NemoClaw that is ``openshell sandbox exec -n ambient-mirror -- openclaw``
  (D02 sets it). Required.
- ``AUM_OPENCLAW_LOCAL=1``: pass ``--local`` (embedded run, for host-side checks).
- ``AUM_TOOLS_BIND``: comma-separated ``host:port`` listeners for the tool server
  (default ``127.0.0.1:8090``). The sandbox needs the bridge gateway address too.
- ``AUM_TOOLS_TOKEN``: the bearer token the server requires. Required for any listener
  beyond loopback. It is never logged or written.

It also sets the safety hazard review seam: ``app.state.hazard_review_runner`` is an
``AgentHazardRunner`` (``hazard_runner.py``) on the same launcher and tool gateway, and
``app.state.hazard_review_runner_name`` is ``"openclaw-agent"``, so every live
``/hazards`` review runs as an OpenClaw turn with the ``mirror__hazard_*`` tools.

The dev-sequence app (``apps.api.main:app``) stays the fallback.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence

from fastapi import FastAPI

from apps.api.main import create_app
from apps.api.services.hazards import HazardService
from apps.api.settings import Settings

from .executor import AgentLauncher, OpenClawAgentExecutor, OpenClawCliLauncher
from .hazard_runner import RUNNER_NAME, AgentHazardRunner
from .mcp_server import McpServer, ToolGateway, parse_binds
from .registration import DEFAULT_PORT, LEAD_AGENT_ID, TOKEN_ENV
from .site_lead import AgentSiteLead

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def lead_launcher_for(launcher: AgentLauncher, env: Mapping[str, str]) -> AgentLauncher:
    """The same launcher, pointed at the ``site-lead`` agent."""
    if isinstance(launcher, OpenClawCliLauncher):
        return OpenClawCliLauncher(
            launcher.command,
            agent_id=LEAD_AGENT_ID,
            local=launcher.local,
            env=launcher.env,
            cwd=launcher.cwd,
        )
    return launcher


def create_agent_app(
    settings: Settings | None = None,
    *,
    launcher: AgentLauncher | None = None,
    binds: Sequence[tuple[str, int]] | None = None,
    token: str | None = None,
    env: Mapping[str, str] | None = None,
) -> FastAPI:
    env = os.environ if env is None else env
    if binds is None:
        spec = env.get("AUM_TOOLS_BIND", "")
        binds = parse_binds(spec, DEFAULT_PORT) if spec.strip() else [("127.0.0.1", DEFAULT_PORT)]
    binds = list(binds)
    token = token if token is not None else (env.get(TOKEN_ENV) or None)
    if token is None and any(host not in LOOPBACK for host, _ in binds):
        raise RuntimeError(f"{TOKEN_ENV} is required when the tool server listens beyond loopback")
    if launcher is None:
        command = shlex.split(env.get("AUM_OPENCLAW_CMD", ""))
        if not command:
            raise RuntimeError("set AUM_OPENCLAW_CMD to the command that runs the openclaw CLI")
        launcher = OpenClawCliLauncher(command, local=env.get("AUM_OPENCLAW_LOCAL") == "1")

    app = create_app(settings)
    gateway = ToolGateway()
    server = McpServer(gateway, binds, token=token).start()
    app.state.tool_server = server
    app.state.executor = OpenClawAgentExecutor(
        launcher, gateway, media_root=app.state.settings.media_root
    )
    # Site runs (event day 14:30): one site-lead turn over six concurrent checkers.
    # AUM_CHECKERS_PARALLEL (default 6) reviews may run at once; 1 keeps the old
    # one-at-a-time behaviour for the per-camera endpoints too.
    parallel = max(1, int(env.get("AUM_CHECKERS_PARALLEL", "6") or 1))
    hazards = HazardService.from_settings(app.state.settings)
    hazards.set_max_parallel(parallel)
    app.state.hazards = hazards
    app.state.hazard_review_runner = AgentHazardRunner(
        launcher, gateway, profile=app.state.settings.model_profile, concurrent=parallel > 1
    )
    app.state.hazard_review_runner_name = RUNNER_NAME
    lead_launcher = lead_launcher_for(launcher, env)
    app.state.site_lead_runner = AgentSiteLead(lead_launcher, gateway)
    app.router.add_event_handler("shutdown", server.close)
    return app


__all__ = ["create_agent_app"]

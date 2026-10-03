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

The dev-sequence app (``apps.api.main:app``) stays the fallback.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence

from fastapi import FastAPI

from apps.api.main import create_app
from apps.api.settings import Settings

from .executor import AgentLauncher, OpenClawAgentExecutor, OpenClawCliLauncher
from .mcp_server import McpServer, ToolGateway, parse_binds
from .registration import DEFAULT_PORT, TOKEN_ENV

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


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
    app.router.add_event_handler("shutdown", server.close)
    return app


__all__ = ["create_agent_app"]

"""D01, live: the real OpenClaw CLI with the registration, against the local brain.

Opt in with ``AUM_OPENCLAW_CLI``, the command that runs the ``openclaw`` CLI on this host
(split like a shell line), for example::

    AUM_OPENCLAW_CLI="node /path/to/node_modules/openclaw/openclaw.mjs" \\
        .venv/bin/python -m pytest tests/integration/agent/test_openclaw_live.py

The brain is the local vLLM endpoint (``AUM_AGENT_BRAIN_URL``, default
``http://127.0.0.1:8000/v1``) serving the agent's model; without it these tests skip.
Each test gets its own OpenClaw home under ``tmp_path``: a minimal ``openclaw.json``
with NemoClaw's global ``bundle-mcp`` grant, the D01 registration merged in, and a copy
of the agent workspace. Turns run embedded (``--local``). The brain is reached through a
recording proxy, so the tests see exactly which tools OpenClaw offered the model.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent.event_day.app import create_agent_app
from agent.event_day.executor import OpenClawCliLauncher, reply_text
from agent.event_day.mcp_server import McpServer, ToolGateway
from agent.event_day.policy import ALERTS_SETTING, Budget
from agent.event_day.registration import (
    TOKEN_ENV,
    WORKSPACE_DIR,
    agent_entry,
    merge_registration,
    openclaw_name,
)
from apps.api.settings import Settings
from inference.profiles import ModelProfile
from tools.session import TOOL_NAMES

from .conftest import CLAIM, FINAL_LINE, VISIBLE, AgentApi, wait_for

pytestmark = pytest.mark.live_model

CLI = shlex.split(os.environ.get("AUM_OPENCLAW_CLI", ""))
BRAIN_URL = os.environ.get("AUM_AGENT_BRAIN_URL", "http://127.0.0.1:8000/v1").rstrip("/")
MODEL_REF = agent_entry()["model"]["primary"]  # "inference/<served model id>"
PROVIDER, _, MODEL_ID = MODEL_REF.partition("/")
MIRROR_TOOLS = {openclaw_name(t) for t in TOOL_NAMES}
TURN_TIMEOUT_S = 300


def _brain_serves_the_model() -> bool:
    try:
        listed = httpx.get(f"{BRAIN_URL}/models", timeout=3).json()
    except (httpx.HTTPError, ValueError):
        return False
    return any(m.get("id") == MODEL_ID for m in listed.get("data", []))


if not CLI:
    pytest.skip("set AUM_OPENCLAW_CLI to run the live OpenClaw checks", allow_module_level=True)
if not _brain_serves_the_model():
    pytest.skip(f"{BRAIN_URL} does not serve {MODEL_ID}", allow_module_level=True)


# -- a recording proxy in front of the brain -------------------------------------------


@dataclass
class BrainProxy:
    upstream: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def offered(self) -> list[set[str]]:
        """The tool names offered in each recorded chat request."""
        return [
            {t["function"]["name"] for t in r.get("tools") or [] if t.get("type") == "function"}
            for r in self.requests
        ]

    def start(self) -> BrainProxy:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _forward(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if method == "POST" and self.path.endswith("/chat/completions"):
                    proxy.requests.append(json.loads(body))
                upstream = proxy.upstream + self.path.removeprefix("/v1")
                headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
                response = httpx.request(
                    method, upstream, content=body, headers=headers, timeout=600
                )
                self.send_response(response.status_code)
                self.send_header("Content-Type", response.headers.get("content-type", "text/plain"))
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)

            def do_GET(self) -> None:
                self._forward("GET")

            def do_POST(self) -> None:
                self._forward("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture
def brain() -> Iterator[BrainProxy]:
    proxy = BrainProxy(BRAIN_URL).start()
    yield proxy
    proxy.close()


# -- an isolated OpenClaw home -----------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class OpenClaw:
    home: Path
    env: dict[str, str]

    @property
    def config_path(self) -> Path:
        return self.home / ".openclaw" / "openclaw.json"

    def configure(self, tools_url: str, brain_url: str) -> None:
        state = self.home / ".openclaw"
        workspace = state / "workspace-urban-mirror"
        shutil.copytree(WORKSPACE_DIR, workspace, dirs_exist_ok=True)
        base = {
            "agents": {
                "defaults": {
                    "model": {"primary": MODEL_REF},
                    "timeoutSeconds": TURN_TIMEOUT_S,
                    "skipBootstrap": True,
                    "thinkingDefault": "off",
                    "workspace": str(state / "workspace"),
                },
                "list": [{"id": "main", "default": True}],
            },
            "models": {
                "mode": "replace",
                "providers": {
                    PROVIDER: {
                        "baseUrl": brain_url,
                        "apiKey": "local-no-auth",  # placeholder: the local vLLM takes none
                        "api": "openai-completions",
                        "timeoutSeconds": TURN_TIMEOUT_S,
                        "models": [
                            {
                                "id": MODEL_ID,
                                "name": MODEL_REF,
                                "reasoning": False,
                                "input": ["text"],
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                                "contextWindow": 262144,
                                "maxTokens": 4096,
                            }
                        ],
                    }
                },
            },
            "tools": {"alsoAllow": ["bundle-mcp"]},  # NemoClaw's global grant
            "update": {"checkOnStart": False},
            "gateway": {"mode": "local", "port": free_port()},
        }
        merged = merge_registration(base, tools_url, workspace=str(workspace))
        self.config_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    def run(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*CLI, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **self.env},
            check=False,
        )

    def launcher(self) -> OpenClawCliLauncher:
        return OpenClawCliLauncher(CLI, local=True, env=self.env)


@pytest.fixture
def openclaw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OpenClaw:
    monkeypatch.delenv(ALERTS_SETTING, raising=False)
    home = tmp_path / "oc-home"
    (home / ".openclaw").mkdir(parents=True)
    env = {
        "HOME": str(home),
        "OPENCLAW_HOME": str(home),
        "OPENCLAW_STATE_DIR": str(home / ".openclaw"),
        "OPENCLAW_CONFIG_PATH": str(home / ".openclaw" / "openclaw.json"),
        "OPENCLAW_NO_AUTO_UPDATE": "1",
        "DO_NOT_TRACK": "1",
        TOKEN_ENV: os.urandom(24).hex(),
    }
    return OpenClaw(home, env)


class CountingGateway(ToolGateway):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def call(self, tool: str, arguments: Any) -> dict[str, Any]:
        self.calls.append(tool)
        return super().call(tool, arguments)


@pytest.fixture
def tool_server_for(openclaw: OpenClaw) -> Iterator[McpServer]:
    with McpServer(CountingGateway(), [("127.0.0.1", 0)], token=openclaw.env[TOKEN_ENV]) as s:
        yield s


# -- the checks ------------------------------------------------------------------------------


def test_openclaw_validates_the_config_and_lists_the_seven_tools(
    openclaw: OpenClaw, tool_server_for: McpServer, brain: BrainProxy
):
    openclaw.configure(tool_server_for.url(), brain.url)
    validate = openclaw.run("config", "validate")
    assert validate.returncode == 0, validate.stderr[-2000:]
    assert "valid" in (validate.stdout + validate.stderr).lower()

    probe = openclaw.run("mcp", "probe", "mirror", "--json")
    assert probe.returncode == 0, probe.stderr[-2000:]
    report = json.loads(probe.stdout[probe.stdout.index("{") :])
    assert sorted(report["tools"]) == sorted(MIRROR_TOOLS)
    assert report["servers"]["mirror"]["tools"] == len(TOOL_NAMES)
    assert not report["diagnostics"]


def test_the_main_agent_gets_no_mirror_tool(
    openclaw: OpenClaw, tool_server_for: McpServer, brain: BrainProxy
):
    openclaw.configure(tool_server_for.url(), brain.url)
    turn = openclaw.run(
        "agent",
        "--agent",
        "main",
        "--session-key",
        "d01-main-denied",
        "--local",
        "--json",
        "--timeout",
        "120",
        "--message",
        "List every tool you can call, then call mirror__sample_video with camera_id cam_01 "
        "if you have it.",
        timeout=240,
    )
    assert turn.returncode == 0, turn.stderr[-2000:]
    assert reply_text(turn.stdout)
    offered = brain.offered()
    assert offered, "the main agent's turn never reached the brain"
    assert all(not names & MIRROR_TOOLS for names in offered), offered
    assert tool_server_for.gateway.calls == []


@pytest.fixture
async def live_api(
    settings: Settings,
    fixture_profile: ModelProfile,
    openclaw: OpenClaw,
    brain: BrainProxy,
) -> AsyncIterator[AgentApi]:
    token = openclaw.env[TOKEN_ENV]
    launcher = openclaw.launcher()
    app = create_agent_app(
        settings, launcher=launcher, binds=[("127.0.0.1", 0)], token=token, env={}
    )
    app.state.executor.profile_loader = lambda name: fixture_profile
    app.state.executor.budget = Budget(deadline_s=TURN_TIMEOUT_S)
    openclaw.configure(app.state.tool_server.url(), brain.url)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield AgentApi(app, c, launcher, settings, token)
    finally:
        app.state.tool_server.close()


async def test_a_live_openclaw_turn_runs_the_whole_run(live_api: AgentApi, brain: BrainProxy):
    run_id, envelopes = await live_api.run(timeout=TURN_TIMEOUT_S + 120)
    assert envelopes[-1]["type"] == "run.complete", envelopes[-1]
    final = envelopes[-1]["payload"]["hypothesis"]
    assert final["event_type"] == CLAIM["event_type"]

    assert wait_for(lambda: live_api.gateway.active_run_id is None, timeout=120)
    run_dir = live_api.run_dir(run_id)
    turn = json.loads((run_dir / "agent_turn.json").read_text())
    assert turn["ok"] is True, turn
    assert FINAL_LINE.search(turn["reply"].splitlines()[-1]), turn["reply"]
    policy = json.loads((run_dir / "agent_policy.json").read_text())
    assert policy["closed"] is True and policy["finalized_by_policy"] is False
    assert policy["per_tool"]["sample_video"] == len(VISIBLE)
    assert policy["per_tool"]["inspect_camera"] == len(VISIBLE)
    assert policy["per_tool"]["submit_hypothesis"] == 1
    assert {"correlate_observations", "triangulate_region", "reason_hypothesis"} <= set(
        policy["per_tool"]
    )
    assert policy["alert"]["enabled"] is False

    offered = brain.offered()
    assert offered and all(names == MIRROR_TOOLS for names in offered), offered

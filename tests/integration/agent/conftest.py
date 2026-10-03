"""Fixtures for the D01 agent integration tests (event day, 2026-10-03).

Camera media is TEST MEDIA (ffmpeg lavfi ``testsrc2``) written at the contract example
scenario's camera paths. The withheld clip is generated too, so the ground-truth path
tests aim at a file that really exists. The fixture profile reads the D00 test cues and
claim (``agent/event_day/tests/conftest.py``), whose bearings cross in ``blind_zone_02``.

``McpClient`` is a plain JSON-RPC client for the ``mirror`` server, and ``ScriptedAgent``
follows the playbook through it. Together they stand in for OpenClaw where a test needs
determinism. ``test_openclaw_live.py`` runs the real OpenClaw agent.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from agent.event_day.app import create_agent_app
from agent.event_day.executor import AgentTurn, OpenClawAgentExecutor, OpenClawCliLauncher
from agent.event_day.mcp_server import McpServer, ToolGateway
from agent.event_day.policy import ALERTS_SETTING
from agent.event_day.tests.conftest import CLAIM, OBSERVATIONS
from apps.api.schemas import REPO_ROOT, Scenario
from apps.api.settings import Settings
from inference.profiles import ModelProfile, load_profile

FFMPEG = shutil.which("ffmpeg")
EXAMPLE = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"
EXAMPLE_DOC = json.loads(EXAMPLE.read_text(encoding="utf-8"))
VISIBLE = [c["id"] for c in EXAMPLE_DOC["visible_cameras"]]
GT_ID = EXAMPLE_DOC["ground_truth_camera"]["id"]
GT_FILE = EXAMPLE_DOC["ground_truth_camera"]["file"]
GT_BASENAME = Path(GT_FILE).name
CLIP_SECONDS = 4
PROTOCOL = "2025-06-18"

__all__ = ["CLAIM", "OBSERVATIONS"]


def make_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=160x90:rate=10:duration={CLIP_SECONDS}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


@pytest.fixture(scope="session")
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not on PATH")
    root = tmp_path_factory.mktemp("agent_d01_media")
    for cam in [*EXAMPLE_DOC["visible_cameras"], EXAMPLE_DOC["ground_truth_camera"]]:
        make_clip(root / cam["file"])
    return root


@pytest.fixture
def scenario() -> Scenario:
    return Scenario.model_validate_json(EXAMPLE.read_bytes())


@pytest.fixture
def fixture_profile(tmp_path: Path) -> ModelProfile:
    """The fixture profile reading the D00 test cues and ``CLAIM`` as the reasoner's."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    paths = {
        "perception": fixtures / "qwen_observations.json",
        "reasoning": fixtures / "final_hypothesis.json",
    }
    paths["perception"].write_text(json.dumps(OBSERVATIONS), encoding="utf-8")
    paths["reasoning"].write_text(json.dumps(CLAIM), encoding="utf-8")
    base = load_profile("fixture", env={})
    return base.model_copy(
        update={
            role: getattr(base, role).model_copy(
                update={"fixture": str(path), "fixture_dir": str(fixtures)}
            )
            for role, path in paths.items()
        }
    )


# -- the MCP server and a client ------------------------------------------------------


@dataclass
class ToolServer:
    server: McpServer
    gateway: ToolGateway
    token: str

    @property
    def url(self) -> str:
        return self.server.url()

    def client(self, token: str | None = None) -> McpClient:
        return McpClient(self.url, self.token if token is None else token)


@pytest.fixture
def tool_server() -> Iterator[ToolServer]:
    token = secrets.token_hex(24)
    gateway = ToolGateway()
    with McpServer(gateway, [("127.0.0.1", 0)], token=token) as server:
        yield ToolServer(server, gateway, token)


class McpClient:
    """A minimal Streamable HTTP MCP client (JSON responses only, as the server sends)."""

    def __init__(self, url: str, token: str | None) -> None:
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(headers=headers, timeout=60)
        self.url = url
        self.session_id: str | None = None
        self._ids = iter(range(1, 1_000_000))
        self.replies: list[str] = []  # every tool reply text, for leak checks

    def post(self, payload: Any, *, session: bool = True) -> httpx.Response:
        headers = {}
        if session and self.session_id:
            headers = {"Mcp-Session-Id": self.session_id, "MCP-Protocol-Version": PROTOCOL}
        return self.http.post(self.url, json=payload, headers=headers)

    def rpc(self, method: str, params: dict | None = None) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            message["params"] = params
        response = self.post(message)
        assert response.status_code == 200, response.text
        return response.json()

    def initialize(self) -> dict[str, Any]:
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "d01-test", "version": "0"},
                },
            },
            session=False,
        )
        assert response.status_code == 200, response.text
        self.session_id = response.headers["mcp-session-id"]
        note = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert note.status_code == 202
        return response.json()["result"]

    def list_tools(self) -> list[dict[str, Any]]:
        return self.rpc("tools/list")["result"]["tools"]

    def call(self, name: str, arguments: dict | None = None) -> dict[str, Any]:
        """The tool's reply envelope ``{"ok": ..., ...}``; checks ``isError`` agrees."""
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})["result"]
        text = result["content"][0]["text"]
        self.replies.append(text)
        reply = json.loads(text)
        assert result["isError"] is (not reply["ok"])
        return reply

    def close(self) -> None:
        self.http.close()


# -- a scripted stand-in for the agent -------------------------------------------------


def brief_cameras(brief: str) -> list[str]:
    """Camera ids listed in a run brief, in order."""
    lines = brief.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("visible cameras"))
    cams = []
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        cams.append(line.split()[0])
    return cams


@dataclass
class ScriptedAgent:
    """Follows the playbook over MCP. ``before`` runs with the client before the playbook,
    ``after`` once it has submitted (to probe or linger)."""

    url: str
    token: str
    before: Callable[[McpClient], None] | None = None
    after: Callable[[McpClient], None] | None = None
    submit: bool = True
    client: McpClient | None = field(default=None, init=False)

    def run(self, brief: str) -> str:
        client = self.client = McpClient(self.url, self.token)
        try:
            client.initialize()
            client.list_tools()
            if self.before is not None:
                self.before(client)
            for cam in brief_cameras(brief):
                client.call("sample_video", {"camera_id": cam})
                client.call("inspect_camera", {"camera_id": cam})
            client.call("correlate_observations")
            bundle = client.call("triangulate_region")
            reasoned = client.call("reason_hypothesis")
            if bundle["ok"] and reasoned["ok"]:
                cited = set(reasoned["result"]["evidence_ids"])
                frames: dict[str, set[int]] = {}
                for item in bundle["result"]["evidence"]:
                    if item["id"] in cited and item["supporting_frames"]:
                        frames.setdefault(item["camera_id"], set()).update(
                            item["supporting_frames"]
                        )
                for cam, indices in frames.items():
                    client.call(
                        "get_supporting_frames",
                        {"camera_id": cam, "frame_indices": sorted(indices)},
                    )
            if not self.submit:
                return "FINAL event=unknown region=unknown confidence=0 alert=none"
            final = client.call("submit_hypothesis")["result"]
            if self.after is not None:
                self.after(client)
            return (
                f"FINAL event={final['event_type']} region={final['region']} "
                f"confidence={final['confidence']} alert=none"
            )
        finally:
            client.close()


@dataclass
class ScriptedLauncher:
    """``AgentLauncher`` that runs a ``ScriptedAgent`` instead of ``openclaw agent``."""

    url: str
    token: str
    before: Callable[[McpClient], None] | None = None
    after: Callable[[McpClient], None] | None = None
    submit: bool = True
    fail_before_calls: bool = False
    briefs: list[str] = field(default_factory=list)
    agents: list[ScriptedAgent] = field(default_factory=list)

    def __call__(self, brief: str, *, run_id: str, timeout_s: float) -> AgentTurn:
        self.briefs.append(brief)
        started = time.monotonic()
        if self.fail_before_calls:
            return AgentTurn(ok=False, error="exit code 1: sandbox not running", exit_code=1)
        agent = ScriptedAgent(
            self.url, self.token, before=self.before, after=self.after, submit=self.submit
        )
        self.agents.append(agent)
        reply = agent.run(brief)
        return AgentTurn(ok=True, reply=reply, duration_s=time.monotonic() - started, exit_code=0)


def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


FINAL_LINE = re.compile(r"^FINAL event=\S+ region=\S+ confidence=\S+ alert=(sent|skipped|none)$")


# -- the API with the agent executor ---------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path, media_root: Path) -> Settings:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "scenario_001.json").write_text(json.dumps(EXAMPLE_DOC), encoding="utf-8")
    return Settings(
        manifests_dir=manifests,
        prepared_dir=tmp_path / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=media_root,
    )


@dataclass
class AgentApi:
    """The API from ``create_agent_app`` with a scripted launcher, plus SSE helpers."""

    app: FastAPI
    client: httpx.AsyncClient
    launcher: ScriptedLauncher | OpenClawCliLauncher
    settings: Settings
    token: str

    @property
    def gateway(self) -> ToolGateway:
        return self.app.state.tool_server.gateway

    @property
    def executor(self) -> OpenClawAgentExecutor:
        return self.app.state.executor

    @property
    def mcp_url(self) -> str:
        return self.app.state.tool_server.url()

    def mcp_client(self) -> McpClient:
        return McpClient(self.mcp_url, self.token)

    async def run(self, timeout: float = 60.0, **body: Any) -> tuple[str, list[dict[str, Any]]]:
        """Start a run and read its whole SSE stream: ``(run_id, envelopes)``."""
        created = await self.client.post("/api/runs", json={"scenario_id": "scenario_001", **body})
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        events = await asyncio.wait_for(
            self.client.get(f"/api/runs/{run_id}/events"), timeout=timeout
        )
        assert events.status_code == 200
        return run_id, parse_sse(events.text)

    def run_dir(self, run_id: str) -> Path:
        return self.settings.runs_dir / run_id


def parse_sse(text: str) -> list[dict[str, Any]]:
    """The envelopes of an SSE body (``data:`` lines), comments dropped."""
    envelopes = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = [ln[5:].removeprefix(" ") for ln in block.split("\n") if ln.startswith("data:")]
        if data:
            envelopes.append(json.loads("\n".join(data)))
    return envelopes


@pytest.fixture
async def agent_api(
    settings: Settings, fixture_profile: ModelProfile, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AgentApi]:
    monkeypatch.delenv(ALERTS_SETTING, raising=False)  # alerts stay at their default: off
    token = secrets.token_hex(24)
    launcher = ScriptedLauncher(url="", token=token)
    app = create_agent_app(
        settings, launcher=launcher, binds=[("127.0.0.1", 0)], token=token, env={}
    )
    launcher.url = app.state.tool_server.url()
    app.state.executor.profile_loader = lambda name: fixture_profile
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield AgentApi(app, c, launcher, settings, token)
    finally:
        app.state.tool_server.close()

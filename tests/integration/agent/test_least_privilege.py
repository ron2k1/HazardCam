"""D01: least privilege on the registered tool surface.

Acceptance: "Only allowed cameras accessible" and "Generic ground-truth filesystem path
inaccessible". During a live run the agent probes the ``mirror`` server with the withheld
camera, its file path (relative, absolute, traversal), other host paths and extra
arguments. Each probe is refused or rejected without echoing what it asked for, the run
still completes, and no reply, event or run file names the withheld camera or a host path.
The server itself serves one JSON-RPC path; it is not a file server.
"""

from __future__ import annotations

import http.client
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from agent.event_day.mcp_server import INVALID_PARAMS, MAX_BODY_BYTES, METHOD_NOT_FOUND
from agent.event_day.policy import Budget
from agent.event_day.registration import agent_entry
from apps.api.schemas import REPO_ROOT

from .conftest import (
    CLAIM,
    GT_BASENAME,
    GT_FILE,
    GT_ID,
    VISIBLE,
    AgentApi,
    McpClient,
    ToolServer,
    wait_for,
)

CAMERA_TOOLS = ("sample_video", "inspect_camera", "get_supporting_frames")
GT_TOKENS = (GT_ID, GT_BASENAME, "hidden_ground_truth")


def camera_probes(media_root: Path) -> list[str]:
    return [
        GT_ID,
        GT_FILE,
        str(media_root / GT_FILE),
        f"../{GT_BASENAME}",
        f"cam_01/../{GT_ID}",
        f"file://{media_root / GT_FILE}",
        "/etc/passwd",
        "cam_04",
        "CAM_01",
        "*",
    ]


def contract_probes(media_root: Path) -> list[tuple[str, dict]]:
    """Calls the contract rejects; the values must not come back."""
    absolute = str(media_root / GT_FILE)
    return [
        ("sample_video", {"camera_id": "cam_01", "file": GT_FILE}),
        ("sample_video", {"camera_id": "cam_01", "path": absolute}),
        ("inspect_camera", {"camera_id": [GT_ID]}),
        ("get_supporting_frames", {"camera_id": "cam_01", "frame_indices": [GT_ID]}),
        ("correlate_observations", {"camera_id": GT_ID}),
        ("triangulate_region", {"cameras": [GT_ID]}),
        ("reason_hypothesis", {"ground_truth": absolute}),
        ("submit_hypothesis", {"hypothesis": {"event_type": GT_ID}}),
    ]


def camera_arguments(tool: str, camera_id: str) -> dict:
    if tool == "get_supporting_frames":
        return {"camera_id": camera_id, "frame_indices": [0]}
    return {"camera_id": camera_id}


def assert_no_echo(text: str, *values: str) -> None:
    for value in (*GT_TOKENS, *values):
        assert value not in text, f"{value!r} came back in {text[:200]!r}"


async def test_the_agent_reaches_only_the_visible_cameras(agent_api: AgentApi):
    media_root = agent_api.settings.media_root
    agent_api.executor.budget = Budget(spare_calls=200, max_consecutive_failures=200)
    probed: list[tuple[str, dict, dict]] = []
    rpc_errors: list[tuple[int, dict]] = []

    def probe(client: McpClient) -> None:
        for tool in CAMERA_TOOLS:
            for camera_id in camera_probes(media_root):
                arguments = camera_arguments(tool, camera_id)
                probed.append((tool, arguments, client.call(tool, arguments)))
        for tool, arguments in contract_probes(media_root):
            probed.append((tool, arguments, client.call(tool, arguments)))
        for name in ("read_file", "message", "mirror__sample_video", f"../{GT_BASENAME}"):
            reply = client.rpc("tools/call", {"name": name, "arguments": {"path": GT_FILE}})
            rpc_errors.append((INVALID_PARAMS, reply))
        for method, params in [
            ("resources/list", {}),
            ("resources/read", {"uri": f"file://{media_root / GT_FILE}"}),
            ("resources/templates/list", {}),
            ("prompts/list", {}),
            ("completion/complete", {}),
        ]:
            rpc_errors.append((METHOD_NOT_FOUND, client.rpc(method, params)))

    agent_api.launcher.before = probe
    run_id, envelopes = await agent_api.run()

    # The run itself still completes on the visible cameras.
    assert envelopes[-1]["type"] == "run.complete"
    final = envelopes[-1]["payload"]["hypothesis"]
    assert (final["event_type"], final["region"]) == (CLAIM["event_type"], CLAIM["region"])

    camera_refusals = len(CAMERA_TOOLS) * len(camera_probes(media_root))
    for tool, arguments, reply in probed[:camera_refusals]:
        assert reply["ok"] is False and reply["refused"] is True, (tool, arguments, reply)
        assert "not a visible camera" in reply["error"]
        assert "use one of: " + ", ".join(VISIBLE) in reply["error"]
    for tool, arguments, reply in probed[camera_refusals:]:
        assert reply["ok"] is False and "result" not in reply, (tool, arguments, reply)
    for tool, arguments, reply in probed:
        assert_no_echo(json.dumps(reply), *[str(v) for v in arguments.values()])

    for expected, reply in rpc_errors:
        assert reply["error"]["code"] == expected and "result" not in reply
        assert_no_echo(json.dumps(reply), GT_FILE, "read_file", "resources", "file://")

    # The policy saw every camera probe as a camera outside the run.
    policy = json.loads((agent_api.run_dir(run_id) / "agent_policy.json").read_text())
    assert policy["refusals"] == camera_refusals
    shown = {e["camera_id"] for e in policy["trace"] if "camera_id" in e}
    assert shown == {*VISIBLE, "not_visible"}
    assert policy["per_tool"]["sample_video"] == len(VISIBLE)


async def test_nothing_the_agent_or_the_run_keeps_names_the_withheld_camera_or_a_host_path(
    agent_api: AgentApi,
):
    media_root = agent_api.settings.media_root
    agent_api.executor.budget = Budget(spare_calls=200, max_consecutive_failures=200)
    agent_api.launcher.before = lambda client: [
        client.call(tool, camera_arguments(tool, cam))
        for tool in CAMERA_TOOLS
        for cam in camera_probes(media_root)
    ]
    run_id, envelopes = await agent_api.run()
    assert envelopes[-1]["type"] == "run.complete"
    run_dir = agent_api.run_dir(run_id)

    (agent,) = agent_api.launcher.agents
    replies = "\n".join(agent.client.replies)
    assert '"ok":true' in replies  # the playbook calls really returned results
    hosts = (str(media_root), str(agent_api.settings.runs_dir), str(REPO_ROOT), str(Path.home()))
    assert_no_echo(replies, *hosts, "/etc/passwd", "file://")
    for reply in agent.client.replies:
        doc = json.loads(reply)
        result = doc.get("result") or {}
        if "clip_path" in result:  # sample_video's media manifest
            assert result["clip_path"] is None
            assert result["source"] == f"camera:{result['camera_id']}"
        for frame in result.get("frames", []):
            assert frame["path"] is None

    assert wait_for(lambda: agent_api.gateway.active_run_id is None)  # the turn has ended
    files = [p for p in run_dir.rglob("*") if p.is_file()]
    assert {"events.jsonl", "run.json", "agent_policy.json", "agent_turn.json"} <= {
        p.name for p in files
    }
    assert not any(token in str(p.relative_to(run_dir)) for p in files for token in GT_TOKENS)
    for path in files:
        if path.suffix in (".json", ".jsonl"):
            assert_no_echo(path.read_text(encoding="utf-8"), "/etc/passwd", str(Path.home()))
    assert (agent_api.launcher.briefs[0]).count("\n  cam_") == len(VISIBLE)


def raw_get(url: str, path: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """A GET with ``path`` sent exactly as written (no client-side normalization)."""
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    try:
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_the_server_is_no_file_server(tool_server: ToolServer, media_root: Path):
    auth = {"Authorization": f"Bearer {tool_server.token}"}
    secret = (media_root / GT_FILE).read_bytes()[:64]
    paths = [
        f"/{GT_FILE}",
        f"/mcp/../{GT_FILE}",
        f"/mcp/%2e%2e/{GT_FILE}",
        f"/mcp?file={GT_FILE}",
        f"/{media_root / GT_FILE}",
        "/../../etc/passwd",
        "/mcp/",
        "/",
    ]
    for path in paths:
        status, body = raw_get(tool_server.url, path, auth)
        assert status == 404, path
        assert secret not in body and GT_BASENAME.encode() not in body
    status, _ = raw_get(tool_server.url, "/mcp", auth)
    assert status == 405  # no server-initiated stream either


def test_the_server_admits_only_its_own_authenticated_clients(tool_server: ToolServer):
    url = tool_server.url
    hello = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
    }
    with httpx.Client(timeout=10) as http:
        assert http.post(url, json=hello).status_code == 401
        wrong = http.post(url, json=hello, headers={"Authorization": "Bearer " + "x" * 48})
        assert wrong.status_code == 401 and wrong.headers["www-authenticate"] == "Bearer"
        auth = {"Authorization": f"Bearer {tool_server.token}"}
        rebound = http.post(url, json=hello, headers={**auth, "Origin": "http://evil.example"})
        assert rebound.status_code == 403
        listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        assert http.post(url, json=listing, headers=auth).status_code == 400  # no session
        unknown = http.post(url, json=listing, headers={**auth, "Mcp-Session-Id": "f" * 32})
        assert unknown.status_code == 404
        big = http.post(
            url,
            content=b"[" + b" " * MAX_BODY_BYTES + b"]",
            headers={**auth, "Content-Type": "application/json"},
        )
        assert big.status_code == 413
        garbled = http.post(url, content=b"{not json", headers=auth)
        assert garbled.status_code == 400 and garbled.json()["error"]["code"] == -32700

    client = tool_server.client()
    try:
        client.initialize()
        assert client.rpc("ping")["result"] == {}
        deleted = client.http.delete(url, headers={"Mcp-Session-Id": client.session_id})
        assert deleted.status_code == 200
        gone = client.post({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
        assert gone.status_code == 404  # a closed session stays closed
    finally:
        client.close()


@pytest.mark.parametrize("group", ["group:fs", "group:runtime", "group:web", "group:messaging"])
def test_the_agent_has_no_filesystem_shell_web_or_messaging_tool(group):
    tools = agent_entry()["tools"]
    assert tools["profile"] == "minimal"
    assert group in tools["deny"]
    assert all(re.fullmatch(r"mirror__[a-z_]+", name) for name in tools["alsoAllow"])

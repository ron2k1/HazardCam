"""D01: a run through the API with the agent executor and the ``mirror`` MCP server.

Acceptance: "Agent integration test passes". ``create_agent_app`` builds the real API,
starts the real MCP server and swaps in ``OpenClawAgentExecutor``. Only the agent's model
is replaced: a ``ScriptedAgent`` follows the playbook over MCP, as OpenClaw does. The
live OpenClaw turn is in ``test_openclaw_live.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest

from agent.event_day.app import create_agent_app
from agent.event_day.executor import HARNESS_ID, OpenClawCliLauncher
from agent.event_day.mcp_server import NO_RUN
from agent.event_day.policy import AGENT_ID
from agent.event_day.registration import REGISTERED_TOOLS
from apps.api.schemas import validate_json
from tools.session import TOOL_NAMES

from .conftest import CLAIM, FINAL_LINE, GT_ID, VISIBLE, AgentApi, McpClient, wait_for

PLAYBOOK = [
    *[tool for _ in VISIBLE for tool in ("sample_video", "inspect_camera")],
    "correlate_observations",
    "triangulate_region",
    "reason_hypothesis",
    *["get_supporting_frames"] * len(VISIBLE),
    "submit_hypothesis",
]


def types(envelopes: list[dict]) -> list[str]:
    return [e["type"] for e in envelopes]


def payloads(envelopes: list[dict], kind: str) -> list[dict]:
    return [e["payload"] for e in envelopes if e["type"] == kind]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


async def test_the_agent_runs_a_whole_run_through_the_api(agent_api: AgentApi):
    run_id, envelopes = await agent_api.run()

    for envelope in envelopes:
        validate_json("sse_envelope", envelope)
        assert envelope["run_id"] == run_id
    assert [e["seq"] for e in envelopes] == list(range(1, len(envelopes) + 1))
    assert types(envelopes)[:2] == ["run.started", "orchestrator.started"]
    assert types(envelopes)[-1] == "run.complete"
    started = payloads(envelopes, "run.started")[0]
    assert started["harness"] == HARNESS_ID
    assert started["camera_ids"] == VISIBLE
    orchestrator = payloads(envelopes, "orchestrator.started")[0]
    assert orchestrator == {"harness": HARNESS_ID, "agent": True, "sequence": list(TOOL_NAMES)}

    # The agent's calls, in playbook order, all through the real session.
    calls = payloads(envelopes, "tool.started")
    assert [c["tool"] for c in calls] == PLAYBOOK
    assert all(c["call_id"].startswith("call_") for c in calls)
    assert all(c["ok"] for c in payloads(envelopes, "tool.completed"))

    final = payloads(envelopes, "run.complete")[0]["hypothesis"]
    assert (final["event_type"], final["region"]) == (CLAIM["event_type"], CLAIM["region"])
    assert payloads(envelopes, "hypothesis.updated")[-1]["final"] is True

    # One brief, from the model view, with no alert line while alerts are off.
    (brief,) = agent_api.launcher.briefs
    assert brief.startswith("RUN BRIEF\n") and f"run: {run_id}" in brief
    assert all(f"  {cam}" in brief for cam in VISIBLE)
    assert GT_ID not in brief and "alert" not in brief and "message" not in brief

    # The turn ends, frees the tool surface and leaves its record.
    assert wait_for(lambda: agent_api.gateway.active_run_id is None)
    run_dir = agent_api.run_dir(run_id)
    turn = read_json(run_dir / "agent_turn.json")
    assert turn["harness"] == HARNESS_ID and turn["ok"] is True
    assert FINAL_LINE.match(turn["reply"]), turn["reply"]
    policy = read_json(run_dir / "agent_policy.json")
    assert policy["agent"] == AGENT_ID and policy["run_id"] == run_id
    assert (policy["calls"], policy["refusals"], policy["failures"]) == (len(PLAYBOOK), 0, 0)
    assert policy["closed"] is True and policy["finalized_by_policy"] is False
    assert policy["alert"]["enabled"] is False and policy["alert"]["grants"] == 0

    record = (await agent_api.client.get(f"/api/runs/{run_id}")).json()
    assert record["state"] == "complete"


async def test_without_a_run_every_tool_call_is_refused(agent_api: AgentApi):
    client = agent_api.mcp_client()
    try:
        client.initialize()
        assert [t["name"] for t in client.list_tools()] == list(REGISTERED_TOOLS)
        for tool, arguments in [
            ("sample_video", {"camera_id": "cam_01"}),
            ("submit_hypothesis", {}),
            ("hazard_scan_clip", {"clip_id": "hz_01"}),
        ]:
            assert client.call(tool, arguments) == {"ok": False, "error": NO_RUN, "refused": True}
    finally:
        client.close()


async def test_runs_are_independent_and_a_finished_turn_reaches_no_later_run(
    agent_api: AgentApi,
):
    first, _ = await agent_api.run()
    assert wait_for(lambda: agent_api.gateway.active_run_id is None)
    # The first turn's agent connects again after its run: nothing is bound.
    stale = McpClient(agent_api.mcp_url, agent_api.token)
    try:
        stale.initialize()
        assert stale.call("sample_video", {"camera_id": "cam_01"})["error"] == NO_RUN
    finally:
        stale.close()

    second, envelopes = await agent_api.run()
    assert second != first and types(envelopes)[-1] == "run.complete"
    assert [b.split("\n")[1] for b in agent_api.launcher.briefs] == [
        f"run: {first}",
        f"run: {second}",
    ]
    policy = read_json(agent_api.run_dir(second) / "agent_policy.json")
    assert policy["calls"] == len(PLAYBOOK) and policy["refusals"] == 0


async def test_the_next_run_waits_until_the_previous_turn_has_ended(agent_api: AgentApi):
    gate = threading.Event()
    late: list[dict] = []

    def linger(client: McpClient) -> None:
        if gate.is_set():
            return
        late.append(client.call("sample_video", {"camera_id": "cam_01"}))
        gate.wait(20)
        late.append(client.call("inspect_camera", {"camera_id": "cam_02"}))

    agent_api.launcher.after = linger
    first, envelopes = await agent_api.run()
    assert types(envelopes)[-1] == "run.complete"  # the run closed on submit
    assert agent_api.gateway.active_run_id == first  # the turn still holds the surface

    created = await agent_api.client.post("/api/runs", json={"scenario_id": "scenario_001"})
    second = created.json()["run_id"]
    await asyncio.sleep(0.5)
    assert len(agent_api.launcher.briefs) == 1  # the second run waits for the lease
    gate.set()
    events = await asyncio.wait_for(agent_api.client.get(f"/api/runs/{second}/events"), timeout=60)
    assert '"type":"run.complete"' in events.text

    # The first turn's late calls went to its own closed run, never to the second one.
    assert len(late) == 2
    assert all(not r["ok"] and r["refused"] and "run is closed" in r["error"] for r in late)
    later = read_json(agent_api.run_dir(second) / "agent_policy.json")
    assert later["per_tool"]["inspect_camera"] == len(VISIBLE)
    assert later["trace"][0]["tool"] == "sample_video" and later["trace"][0]["ok"]


async def test_a_turn_that_never_ran_fails_the_run_at_stage_agent(agent_api: AgentApi):
    agent_api.launcher.fail_before_calls = True
    run_id, envelopes = await agent_api.run()
    assert types(envelopes) == ["run.started", "orchestrator.started", "run.failed"]
    failed = payloads(envelopes, "run.failed")[0]
    assert failed["stage"] == "agent"
    assert "did not run" in failed["error"] and "sandbox not running" in failed["error"]
    assert wait_for(lambda: agent_api.gateway.active_run_id is None)
    assert read_json(agent_api.run_dir(run_id) / "agent_policy.json")["calls"] == 0


async def test_a_turn_that_ends_without_submitting_abstains(agent_api: AgentApi):
    agent_api.launcher.submit = False
    run_id, envelopes = await agent_api.run()
    assert types(envelopes)[-1] == "run.complete"
    final = payloads(envelopes, "run.complete")[0]["hypothesis"]
    assert final["event_type"] == "unknown"
    assert any("without submitting" in note for note in final["limitations"])
    policy = read_json(agent_api.run_dir(run_id) / "agent_policy.json")
    assert (
        policy["finalized_by_policy"] is True
        and policy["per_tool"].get("submit_hypothesis") is None
    )


# -- the openclaw CLI launcher and the app factory ------------------------------------

FAKE_CLI = """\
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"argv": sys.argv[2:], "stdin": sys.stdin.read()}))
if "--fail" in sys.argv[1]:
    sys.stderr.write("boot\\nError: cannot open /home/someone/.openclaw/openclaw.json\\n")
    sys.exit(3)
print("[plugins] ready")
print(json.dumps({"payloads": [{"text": "FINAL event=vehicle_stop region=blind_zone_02 "
                                         "confidence=0.74 alert=none"}], "meta": {}}))
"""


@pytest.fixture
def fake_cli(tmp_path: Path) -> Path:
    script = tmp_path / "fake_openclaw.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    return script


def test_the_cli_launcher_runs_one_isolated_agent_turn(tmp_path: Path, fake_cli: Path):
    record = tmp_path / "argv.json"
    launcher = OpenClawCliLauncher([sys.executable, str(fake_cli), str(record)])
    turn = launcher("RUN BRIEF\nrun: run_x", run_id="run_x", timeout_s=30)
    assert turn.ok and turn.exit_code == 0
    assert FINAL_LINE.match(turn.reply)
    seen = read_json(record)
    assert seen["stdin"] == ""  # stdin is closed, so the CLI never waits on it
    assert seen["argv"] == [
        "agent",
        "--agent",
        AGENT_ID,
        "--session-key",
        "run_x",
        "--message",
        "RUN BRIEF\nrun: run_x",
        "--json",
        "--timeout",
        "30",
    ]


def test_a_failing_cli_turn_reports_without_host_paths(tmp_path: Path, fake_cli: Path):
    record = tmp_path / "argv--fail.json"
    launcher = OpenClawCliLauncher([sys.executable, str(fake_cli), str(record)], local=True)
    turn = launcher("RUN BRIEF", run_id="run_y", timeout_s=5)
    assert not turn.ok and turn.exit_code == 3
    assert "exit code 3" in turn.error and "cannot open <path>" in turn.error
    assert "/home/someone" not in turn.error
    assert read_json(record)["argv"][-1] == "--local"


def test_the_app_factory_requires_the_cli_and_a_token_beyond_loopback(settings):
    with pytest.raises(RuntimeError, match="AUM_OPENCLAW_CMD"):
        create_agent_app(settings, binds=[("127.0.0.1", 0)], env={})
    with pytest.raises(RuntimeError, match="AUM_TOOLS_TOKEN"):
        create_agent_app(settings, binds=[("0.0.0.0", 0)], env={"AUM_OPENCLAW_CMD": "openclaw"})

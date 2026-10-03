"""D00/D01: the OpenClaw agent definition and playbook files.

``agent.json`` is an ``agents.list[]`` entry for the OpenClaw inside the NemoClaw
sandbox (2026.7.1). The schema next to it was extracted from that build's
``openclaw config schema``. D01 registered the seven contract tools as the ``mirror``
MCP server and removed D00's ``message`` grant (the Telegram alert is switched off).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from agent.event_day.policy import AGENT_ID, ALERT_TOOL
from apps.api.schemas.contracts import def_validator
from tools.session import TOOL_NAMES

EVENT_DAY = Path(__file__).resolve().parents[1]
OPENCLAW = EVENT_DAY / "openclaw"
AGENT = json.loads((OPENCLAW / "agent.json").read_text(encoding="utf-8"))
SCHEMA = OPENCLAW / "schema" / "openclaw-2026.7.1.agents-list-entry.schema.json"
WORKSPACE = OPENCLAW / "workspace"
PLAYBOOK = (WORKSPACE / "AGENTS.md").read_text(encoding="utf-8")

# Every OpenClaw 2026.7.1 tool group, messaging included (its only tool is ``message``).
DENIED_GROUPS = {
    "group:messaging",
    "group:fs",
    "group:runtime",
    "group:web",
    "group:ui",
    "group:sessions",
    "group:memory",
    "group:nodes",
    "group:automation",
    "group:media",
    "group:agents",
}
TOKEN_SHAPE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}")


def test_agent_json_is_a_valid_openclaw_2026_7_1_agent_entry():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [e.message for e in jsonschema.Draft7Validator(schema).iter_errors(AGENT)]
    assert errors == []
    assert AGENT["id"] == AGENT_ID


def test_the_brain_is_the_local_inference_route_with_no_fallback():
    assert AGENT["model"] == {"primary": "inference/nvidia/Qwen3.6-35B-A3B-NVFP4", "fallbacks": []}
    assert AGENT["memorySearch"] == {"enabled": False}  # no embedding calls (runtime pitfall P2)
    assert AGENT["skills"] == [] and AGENT["subagents"] == {"allowAgents": []}
    assert AGENT["heartbeat"] == {"every": "0m"}


def test_only_the_seven_mirror_tools_are_added_and_every_group_is_denied():
    tools = AGENT["tools"]
    assert tools["profile"] == "minimal"
    assert "allow" not in tools  # OpenClaw rejects allow next to alsoAllow
    assert tools["alsoAllow"] == [f"mirror__{name}" for name in TOOL_NAMES]
    assert DENIED_GROUPS <= set(tools["deny"])
    assert "session_status" in tools["deny"]  # the one tool the minimal profile grants


def test_no_messaging_capability_is_granted():
    tools = AGENT["tools"]
    assert ALERT_TOOL not in tools["alsoAllow"] and "message" not in tools
    assert "group:messaging" in tools["deny"]
    assert "telegram" not in json.dumps(AGENT).lower()


def test_loop_detection_is_on_with_ordered_thresholds():
    loop = AGENT["tools"]["loopDetection"]
    assert loop["enabled"] is True
    assert (
        loop["warningThreshold"] < loop["criticalThreshold"] < loop["globalCircuitBreakerThreshold"]
    )


def test_the_playbook_covers_every_registered_tool_and_keeps_the_alert_off():
    for name in TOOL_NAMES:
        assert f"`mirror__{name}`" in PLAYBOOK, name
    assert "FINAL event=" in PLAYBOOK
    # The alert section stays, inert unless the brief arms it.
    alert = PLAYBOOK.split("## Alert (switched off)", 1)[1].split("\n## ", 1)[0]
    for phrase in (
        "only when the RUN BRIEF",
        "never call it",
        "alert.arguments",
        "never send twice",
    ):
        assert phrase in alert, phrase


def test_the_playbooks_abstention_is_a_valid_submit_call():
    block = re.search(r"```json\n(.*?)```", PLAYBOOK, re.DOTALL)
    assert block is not None
    args = json.loads(block.group(1))
    def_validator("tool_call", "submit_hypothesis_args").validate(args)
    assert args["hypothesis"]["event_type"] == "unknown" == args["hypothesis"]["region"]


@pytest.mark.parametrize("name", ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md"])
def test_workspace_files_fit_openclaws_bootstrap_budget(name):
    assert len((WORKSPACE / name).read_text(encoding="utf-8")) < 20_000  # bootstrapMaxChars


def test_no_event_day_file_holds_a_token_or_a_withheld_camera_reference():
    for path in EVENT_DAY.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".md"} and "schema" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert not TOKEN_SHAPE.search(text), path
            if "tests" not in path.parts:
                assert "cam_gt" not in text and "expected.json" not in text, path

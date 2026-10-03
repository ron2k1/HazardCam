"""D01: the tools registered into OpenClaw are the prebuild contract's, unchanged.

Acceptance: "Tool schemas match prebuild contracts". The ``mirror`` MCP server's
``tools/list`` is compared with ``contracts/tools.schema.json`` (each tool's
``$defs/<tool>_args``) and ``contracts/hypothesis.schema.json``. The inlined schema must
give the same verdict as the contract's own validator on valid and invalid arguments.
The OpenClaw side (``agent.json`` grants, the server's tool filter, the ``main`` deny)
must name the same seven tools.
"""

from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from agent.event_day.registration import (
    SERVER_NAME,
    TOKEN_ENV,
    TOOL_PREFIX,
    agent_entry,
    merge_registration,
    openclaw_name,
    registration,
    server_url,
)
from apps.api.schemas.contracts import is_valid, load_schema
from tools.session import TOOL_NAMES, args_def

from .conftest import CLAIM, GT_ID, ToolServer

CONTRACT = load_schema("tool_call")
HYPOTHESIS = load_schema("hypothesis")
CAMERA_ID = CONTRACT["$defs"]["camera_id"]
META = {"$id", "$schema", "$comment"}


def strip_meta(node):
    if isinstance(node, dict):
        return {k: strip_meta(v) for k, v in node.items() if k not in META}
    if isinstance(node, list):
        return [strip_meta(v) for v in node]
    return node


@pytest.fixture
def listed(tool_server: ToolServer) -> dict[str, dict]:
    client = tool_server.client()
    try:
        info = client.initialize()
        assert info["serverInfo"]["name"] == "urban-mirror-tools"
        assert info["capabilities"] == {"tools": {"listChanged": False}}
        return {tool["name"]: tool for tool in client.list_tools()}
    finally:
        client.close()


def test_the_server_lists_exactly_the_seven_contract_tools_in_order(listed):
    assert list(listed) == list(TOOL_NAMES)
    assert len(TOOL_NAMES) == 7


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_each_input_schema_is_the_contract_args_def(listed, tool):
    contract_def = CONTRACT["$defs"][args_def(tool)]
    schema = listed[tool]["inputSchema"]
    assert "$ref" not in json.dumps(schema)
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is contract_def.get("additionalProperties") is False
    assert schema.get("required", []) == contract_def.get("required", [])
    assert set(schema.get("properties", {})) == set(contract_def.get("properties", {}))
    assert listed[tool]["description"]
    if "camera_id" in contract_def.get("properties", {}):
        assert schema["properties"]["camera_id"] == CAMERA_ID


def test_submit_takes_the_hypothesis_contract_as_its_optional_argument(listed):
    schema = listed["submit_hypothesis"]["inputSchema"]
    contract_def = CONTRACT["$defs"][args_def("submit_hypothesis")]
    assert set(schema["properties"]) == set(contract_def["properties"]) == {"hypothesis"}
    assert schema["properties"]["hypothesis"] == strip_meta(HYPOTHESIS)


def corpus() -> list[tuple[str, dict]]:
    """Arguments the contract accepts and rejects, for every tool."""
    bad_cams = [GT_ID, "cam_1", "../cam_01", "/etc/passwd", "", "CAM_01"]
    cases: list[tuple[str, dict]] = []
    for tool in ("sample_video", "inspect_camera"):
        cases += [(tool, {"camera_id": "cam_01"}), (tool, {})]
        cases += [(tool, {"camera_id": cam}) for cam in bad_cams]
        cases += [(tool, {"camera_id": "cam_01", "path": "/etc/passwd"})]
    cases += [
        ("sample_video", {"camera_id": "cam_02", "max_frames": 4}),
        ("sample_video", {"camera_id": "cam_02", "max_frames": 0}),
        ("sample_video", {"camera_id": "cam_02", "max_frames": "4"}),
    ]
    for tool in ("correlate_observations", "triangulate_region", "reason_hypothesis"):
        cases += [(tool, {}), (tool, {"camera_id": "cam_01"}), (tool, {"file": "x.mp4"})]
    cases += [
        ("get_supporting_frames", {"camera_id": "cam_01", "frame_indices": [1, 2]}),
        ("get_supporting_frames", {"camera_id": "cam_01", "frame_indices": []}),
        ("get_supporting_frames", {"camera_id": "cam_01", "frame_indices": [-1]}),
        ("get_supporting_frames", {"camera_id": "cam_01"}),
        ("get_supporting_frames", {"camera_id": GT_ID, "frame_indices": [1]}),
        ("submit_hypothesis", {}),
        ("submit_hypothesis", {"hypothesis": CLAIM}),
        ("submit_hypothesis", {"hypothesis": {**CLAIM, "confidence": 2}}),
        ("submit_hypothesis", {"hypothesis": {**CLAIM, "ground_truth": "x"}}),
        ("submit_hypothesis", {"hypothesis": {k: v for k, v in CLAIM.items() if k != "reason"}}),
        ("submit_hypothesis", {"verdict": "vehicle_stop"}),
    ]
    return cases


def contract_accepts(tool: str, arguments: dict) -> bool:
    return is_valid("tool_call", {"name": tool, "arguments": arguments})


@pytest.mark.parametrize(("tool", "arguments"), corpus())
def test_the_listed_schema_and_the_contract_agree(listed, tool, arguments):
    inline = Draft202012Validator(listed[tool]["inputSchema"])
    assert inline.is_valid(arguments) is contract_accepts(tool, arguments)


def test_the_corpus_has_both_verdicts_for_every_tool():
    verdicts: dict[str, set[bool]] = {}
    for tool, arguments in corpus():
        verdicts.setdefault(tool, set()).add(contract_accepts(tool, arguments))
    assert set(verdicts) == set(TOOL_NAMES)
    assert all(v == {True, False} for v in verdicts.values()), verdicts


def test_the_openclaw_side_names_the_same_seven_tools():
    fragment = registration(server_url())
    server = fragment["mcp"]["servers"][SERVER_NAME]
    assert server["toolFilter"]["include"] == list(TOOL_NAMES)
    assert server["transport"] == "streamable-http"
    assert server["url"] == "http://host.openshell.internal:8090/mcp"
    assert server["headers"] == {"Authorization": f"Bearer ${{{TOKEN_ENV}}}"}
    assert fragment["agents"]["list"] == [agent_entry()]
    granted = [n for n in agent_entry()["tools"]["alsoAllow"] if n.startswith(TOOL_PREFIX)]
    assert granted == [openclaw_name(t) for t in TOOL_NAMES]
    assert agent_entry()["tools"]["alsoAllow"] == granted  # nothing else is added


def test_the_fragment_carries_no_credential():
    text = json.dumps(registration(server_url()))
    assert "${" + TOKEN_ENV + "}" in text
    for marker in ("apiKey", 'token":', "password", "secret", "telegram"):
        assert marker not in text


def test_merging_denies_the_mirror_tools_to_every_other_agent():
    base = {
        "gateway": {"auth": {"mode": "token", "token": "kept-as-is"}},
        "tools": {"profile": "minimal", "alsoAllow": ["bundle-mcp"]},
        "agents": {
            "list": [
                {"id": "main", "default": True, "tools": {"deny": ["group:web"]}},
                {"id": "urban-mirror", "workspace": "/stale"},
                {"id": "helper"},
            ]
        },
    }
    before = copy.deepcopy(base)
    merged = merge_registration(base, server_url(), workspace="/sandbox/ws")
    assert base == before  # the input is not mutated
    agents = {a["id"]: a for a in merged["agents"]["list"]}
    assert list(agents) == ["main", "helper", "urban-mirror"]
    assert agents["main"]["tools"]["deny"] == ["group:web", "mirror__*"]
    assert agents["helper"]["tools"]["deny"] == ["mirror__*"]
    assert agents["urban-mirror"]["workspace"] == "/sandbox/ws"
    assert agents["urban-mirror"]["tools"] == agent_entry()["tools"]
    assert merged["gateway"] == base["gateway"]
    assert merged["tools"] == base["tools"]
    again = merge_registration(merged, server_url())
    assert {a["id"]: a for a in again["agents"]["list"]}["main"]["tools"]["deny"] == [
        "group:web",
        "mirror__*",
    ]


def test_merging_into_a_config_without_agents_adds_a_denied_main():
    merged = merge_registration({}, server_url())
    main, mirror = merged["agents"]["list"]
    assert main == {"id": "main", "default": True, "tools": {"deny": ["mirror__*"]}}
    assert mirror["id"] == "urban-mirror"

"""P12: the single-turn tool-call probe's definitions, cases and scoring (no model calls).

The transcript steps here are hand-built inputs shaped like the session's own
``result_summary`` payloads; the probe itself records a real fixture run.
"""

from __future__ import annotations

import json
import re

import pytest
from jsonschema import Draft202012Validator

from apps.api.schemas import REPO_ROOT
from apps.api.schemas.contracts import def_validator
from eval.tool_probe import (
    RECOVERY_CASE,
    Step,
    acceptable_calls,
    build_cases,
    score_reply,
    summarize_probe,
    tool_definitions,
)
from tools.session import TOOL_NAMES, args_def

CAMS = ["cam_a", "cam_b", "cam_c"]
HYPOTHESIS = json.loads(
    (REPO_ROOT / "data" / "fixtures" / "eval_001" / "final_hypothesis.json").read_text("utf-8")
)


def _steps() -> list[Step]:
    steps = []
    for cam in CAMS:
        steps += [
            Step("sample_video", {"camera_id": cam}, {"ok": True, "frames": 8, "duration_s": 30.0}),
            Step("inspect_camera", {"camera_id": cam}, {"ok": True, "observations": 2}),
        ]
    claim = {"event_type": "vehicle_stop", "region": "z_north_lot", "confidence": 0.6}
    return [
        *steps,
        Step("correlate_observations", {}, {"ok": True, "evidence": 6, "clusters": 2}),
        Step("triangulate_region", {}, {"ok": True, "status": "ok", "candidates": 2}),
        Step("reason_hypothesis", {}, {"ok": True, **claim}),
        Step(
            "get_supporting_frames", {"camera_id": "cam_b", "frame_indices": [2, 3]}, {"ok": True}
        ),
        Step("submit_hypothesis", {}, {"ok": True, **claim}),
    ]


def _call(name: str, arguments: object) -> dict:
    return {"tool_calls": [{"id": "call00000", "function": {"name": name, "arguments": arguments}}]}


def test_tool_definitions_cover_the_contract():
    tools = tool_definitions()
    assert [t["function"]["name"] for t in tools] == list(TOOL_NAMES)
    assert "$ref" not in json.dumps(tools)
    for tool in tools:
        assert tool["type"] == "function" and tool["function"]["description"]
        Draft202012Validator.check_schema(tool["function"]["parameters"])


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"camera_id": "cam_a"},
        {"camera_id": ["cam_a"]},
        {"camera_id": ""},
        {"camera_id": "cam_a", "extra": 1},
        {"camera_id": "cam_a", "frame_indices": [0, 2]},
        {"camera_id": "cam_a", "frame_indices": []},
        {"camera_id": "cam_a", "frame_indices": [-1]},
        {"hypothesis": HYPOTHESIS},
        {"hypothesis": {**HYPOTHESIS, "event_type": ""}},
        {"hypothesis": {**HYPOTHESIS, "confidence": 1.5}},
    ],
)
def test_inlined_parameters_judge_arguments_like_the_contract(arguments):
    for tool in tool_definitions():
        name = tool["function"]["name"]
        inlined = Draft202012Validator(tool["function"]["parameters"]).is_valid(arguments)
        assert inlined == def_validator("tool_call", args_def(name)).is_valid(arguments), name


def test_acceptable_calls_follow_the_tool_prerequisites():
    steps = _steps()
    start = acceptable_calls(CAMS, [])
    assert set(start) == {"sample_video"}
    assert start["sample_video"]({"camera_id": "cam_a"})
    assert not start["sample_video"]({"camera_id": "cam_gt"})

    one = acceptable_calls(CAMS, steps[:1])
    assert set(one) == {"sample_video", "inspect_camera"}
    assert one["inspect_camera"]({"camera_id": "cam_a"})
    assert not one["inspect_camera"]({"camera_id": "cam_b"})
    assert not one["sample_video"]({"camera_id": "cam_a"})  # already sampled

    assert set(acceptable_calls(CAMS, steps[:6])) == {"correlate_observations"}
    assert set(acceptable_calls(CAMS, steps[:7])) == {"triangulate_region"}
    assert set(acceptable_calls(CAMS, steps[:8])) == {"reason_hypothesis"}
    end = acceptable_calls(CAMS, steps[:9])
    assert set(end) == {"get_supporting_frames", "submit_hypothesis"}
    assert end["get_supporting_frames"]({"camera_id": "cam_b", "frame_indices": [0, 7]})
    assert not end["get_supporting_frames"]({"camera_id": "cam_b", "frame_indices": [8]})


def test_cases_cover_every_prefix_and_the_recovery():
    steps = _steps()
    cases = build_cases("eval_001", CAMS, steps)
    assert len(cases) == len(steps) + 1
    assert cases[0].name == "00_next_after_start"
    assert [m["role"] for m in cases[0].messages] == ["system", "user"]
    assert "cam_a, cam_b, cam_c" in cases[0].messages[1]["content"]

    last = cases[len(steps) - 1].messages
    ids = [m["tool_call_id"] for m in last if m["role"] == "tool"]
    assert len(ids) == len(steps) - 1 and all(re.fullmatch(r"[A-Za-z0-9]{9}", i) for i in ids)

    recovery = cases[-1]
    assert recovery.name == RECOVERY_CASE
    rejection = json.loads(recovery.messages[-1]["content"])
    assert rejection == {"ok": False, "error": "inspect_camera: camera_id: must be a string"}
    # The rejected call did not count: cam_a still needs inspecting.
    assert recovery.acceptable["inspect_camera"]({"camera_id": "cam_a"})


@pytest.mark.parametrize(
    ("prefix", "message", "outcome", "invisible"),
    [
        (0, {"content": "I will sample cam_a."}, "no_tool_call", False),
        (0, _call("sample_video", '{"camera_id": "cam_a"}'), "ok", False),
        (0, _call("sample_video", {"camera_id": "cam_a"}), "ok", False),
        (0, _call("sample_video", '{"camera_id": '), "bad_json", False),
        (0, _call("sample_video", '["cam_a"]'), "bad_json", False),
        (0, _call("delete_everything", "{}"), "invalid_call", False),
        (0, _call("sample_video", '{"camera_id": ["cam_a"]}'), "invalid_call", True),
        (0, _call("correlate_observations", "{}"), "wrong_tool", False),
        (0, _call("sample_video", '{"camera_id": "cam_gt"}'), "bad_arguments", True),
        (
            9,
            _call("get_supporting_frames", '{"camera_id": "cam_b", "frame_indices": [9]}'),
            "bad_arguments",
            False,
        ),
        (9, _call("submit_hypothesis", "{}"), "ok", False),
    ],
)
def test_score_reply(prefix, message, outcome, invisible):
    case = build_cases("eval_001", CAMS, _steps())[prefix]
    row = score_reply(case, message)
    assert row["outcome"] == outcome
    assert row["invisible_camera"] is invisible
    assert "cam_gt" not in (row["error"] or "")


def test_summary_counts_and_recovery():
    cases = build_cases("eval_001", CAMS, _steps())
    rows = [score_reply(c, _call("sample_video", '{"camera_id": "cam_c"}')) for c in cases]
    for row in rows:
        row["latency_s"] = 1.0
    summary = summarize_probe(rows, meta={})
    assert summary["n"] == len(cases)
    assert summary["pass"]["k"] == sum(r["outcome"] == "ok" for r in rows) > 0
    assert summary["recovered"] is True  # sampling cam_c is productive after the rejection
    assert summary["median_latency_s"] == 1.0

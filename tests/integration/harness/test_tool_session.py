"""P10: the run-scoped tool bindings (``tools/session.py``) and their JSON contract.

Media and fixture profiles come from ``conftest.py`` (TEST MEDIA, TEST FIXTURES).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.api.schemas import load_schema
from apps.api.schemas.contracts import def_validator
from apps.api.services.gt_guard import GtGuard
from tools.session import (
    NOT_VISIBLE,
    TOOL_NAMES,
    UNKNOWN_TOOL,
    ToolCallError,
    ToolSession,
    args_def,
)

pytestmark = pytest.mark.media

Events = list[tuple[str, dict[str, Any]]]


@pytest.fixture
def events() -> Events:
    return []


@pytest.fixture
def session(scenario, consistent, media_root, tmp_path, events) -> ToolSession:
    """A session whose emit applies the API's ground-truth guard to every payload."""
    guard = GtGuard.for_scenario(scenario)

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        text = json.dumps(payload)
        assert not guard.leaks(text), f"{event_type} leaked the ground-truth camera"
        events.append((event_type, json.loads(text)))

    return ToolSession(
        scenario.model_view(), consistent, emit, run_dir=tmp_path / "run", media_root=media_root
    )


def _failed_call(events: Events) -> dict[str, Any]:
    (last_type, last) = events[-1]
    assert last_type == "tool.completed" and last["ok"] is False
    (started_type, started) = events[-2]
    assert started_type == "tool.started" and started["call_id"] == last["call_id"]
    return last


def test_tool_names_match_the_contract():
    schema = load_schema("tool_call")
    assert list(TOOL_NAMES) == schema["properties"]["name"]["enum"]
    for name in TOOL_NAMES:
        assert args_def(name) in schema["$defs"], name
        assert f"{name}_result" in schema["$defs"], name


def test_every_result_round_trips_through_its_schema(session):
    results: list[tuple[str, dict[str, Any]]] = []

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = session.call_tool(name, arguments)
        results.append((name, result))
        return result

    for camera_id in session.camera_ids:
        call("sample_video", {"camera_id": camera_id})
        call("inspect_camera", {"camera_id": camera_id})
    call("correlate_observations", {})
    call("triangulate_region", {})
    raw = call("reason_hypothesis", {})
    call("get_supporting_frames", {"camera_id": "cam_03", "frame_indices": [3, 2, 3]})
    final = call("submit_hypothesis", {})

    assert {name for name, _ in results} == set(TOOL_NAMES)
    for name, result in results:
        def_validator("tool_call", f"{name}_result").validate(result)
    assert raw["event_type"] == final["event_type"] == "vehicle_stop"
    frames = dict(results)["get_supporting_frames"]
    assert [f["index"] for f in frames["frames"]] == [3, 2]


@pytest.mark.parametrize(
    ("name", "arguments", "stage", "message"),
    [
        ("sample_video", {}, "sample_video", "'camera_id' is a required property"),
        ("sample_video", {"camera_id": "cam_01", "fps": 2}, "sample_video", "'fps' was unexpected"),
        (
            "inspect_camera",
            {"camera_id": 1},
            "inspect_camera",
            "camera_id: 1 is not of type 'string'",
        ),
        ("inspect_camera", None, "inspect_camera", "None is not of type 'object'"),
        ("correlate_observations", {"all": True}, "correlate_observations", "'all' was unexpected"),
        (
            "get_supporting_frames",
            {"camera_id": "cam_01", "frame_indices": []},
            "get_supporting_frames",
            "frame_indices",
        ),
        ("teleport", {}, UNKNOWN_TOOL, "unknown tool 'teleport'"),
    ],
)
def test_invalid_calls_fail_their_pair_with_a_corrective_error(
    session, events, name, arguments, stage, message
):
    with pytest.raises(ToolCallError) as info:
        session.call_tool(name, arguments)
    assert info.value.stage == stage
    failed = _failed_call(events)
    assert failed["tool"] == stage and message in failed["error"]
    assert len(events) == 2  # nothing ran


@pytest.mark.parametrize(
    ("tool", "arguments", "missing"),
    [
        ("inspect_camera", {"camera_id": "cam_01"}, "call sample_video for 'cam_01' first"),
        (
            "get_supporting_frames",
            {"camera_id": "cam_01", "frame_indices": [0]},
            "call sample_video",
        ),
        ("correlate_observations", {}, "call inspect_camera"),
        ("triangulate_region", {}, "call correlate_observations first"),
        ("reason_hypothesis", {}, "call triangulate_region first"),
        ("submit_hypothesis", {}, "call triangulate_region first"),
    ],
)
def test_out_of_order_calls_name_the_missing_tool(session, events, tool, arguments, missing):
    with pytest.raises(ToolCallError) as info:
        session.call_tool(tool, arguments)
    assert info.value.stage == tool
    assert missing in _failed_call(events)["error"]


@pytest.mark.parametrize("camera_id", ["cam_gt", "cam_99"])
@pytest.mark.parametrize("tool", ["sample_video", "inspect_camera", "get_supporting_frames"])
def test_non_visible_cameras_are_refused_without_echoing_the_id(session, events, tool, camera_id):
    arguments: dict[str, Any] = {"camera_id": camera_id}
    if tool == "get_supporting_frames":
        arguments["frame_indices"] = [0]
    with pytest.raises(ToolCallError) as info:
        session.call_tool(tool, arguments)
    assert info.value.stage == tool
    assert camera_id not in str(info.value)
    failed = _failed_call(events)
    assert failed["error"].startswith("GroundTruthAccessError")
    assert "use one of: cam_01, cam_02, cam_03" in failed["error"]
    assert events[-2][1]["args_summary"]["camera_id"] == NOT_VISIBLE
    assert camera_id not in json.dumps(events)
    assert not (session.run_dir / "frames" / camera_id).exists()


def test_session_takes_only_the_model_view(scenario, consistent, tmp_path):
    with pytest.raises(TypeError, match="ModelScenarioView"):
        ToolSession(scenario, consistent, lambda *_: None, run_dir=tmp_path / "run")


def test_new_observations_invalidate_fused_state(session):
    for camera_id in session.camera_ids:
        session.sample_video(camera_id)
        session.inspect_camera(camera_id)
    session.correlate_observations()
    session.triangulate_region()
    session.reason_hypothesis()

    session.sample_video("cam_02")
    assert "cam_02" not in session.batches
    assert session.evidence is session.bundle is session.raw_hypothesis is None
    with pytest.raises(ToolCallError, match="call correlate_observations first"):
        session.triangulate_region()

    session.correlate_observations()  # cam_01 and cam_03 cues only
    bundle = session.triangulate_region()
    assert {e.camera_id for e in bundle.evidence} == {"cam_01", "cam_03"}


def test_submit_gates_a_caller_supplied_hypothesis(session):
    for camera_id in session.camera_ids:
        session.sample_video(camera_id)
        session.inspect_camera(camera_id)
    session.correlate_observations()
    session.triangulate_region()
    claim = {
        "event_type": "vehicle_stop",
        "region": "nowhere_zone",
        "confidence": 0.9,
        "evidence_ids": ["obs_a_001", "obs_invented"],
        "reason": "caller-supplied claim",
        "alternatives": [],
        "limitations": [],
    }
    final = session.call_tool("submit_hypothesis", {"hypothesis": claim})
    assert final["region"] == "unknown"
    assert final["evidence_ids"] == ["obs_a_001"]
    assert final["confidence"] <= 0.6  # single-camera cap
    assert session.raw_hypothesis is None  # reason_hypothesis was never called

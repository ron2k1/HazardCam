"""P10: the run-scoped tool bindings (``tools/session.py``) and their JSON contract.

Media and fixture profiles come from ``conftest.py`` (TEST MEDIA, TEST FIXTURES).
"""

from __future__ import annotations

import copy
import json
import threading
from typing import Any

import pytest

from apps.api.schemas import GroundTruthAccessError, load_schema
from apps.api.schemas.contracts import def_validator
from apps.api.services.gt_guard import GtGuard
from tools.session import (
    NOT_VISIBLE,
    TOOL_NAMES,
    UNKNOWN_TOOL,
    ToolCallError,
    ToolSession,
    _Trace,
    args_def,
    rejection_error,
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


def _claim(**overrides: Any) -> dict[str, Any]:
    claim = {
        "event_type": "vehicle_stop",
        "region": "blind_zone_02",
        "confidence": 0.5,
        "evidence_ids": [],
        "reason": "caller-supplied claim",
        "alternatives": [],
        "limitations": [],
    }
    return {**claim, **overrides}


@pytest.mark.parametrize(
    ("name", "arguments", "stage", "message"),
    [
        ("sample_video", {}, "sample_video", "arguments: missing required argument(s): camera_id"),
        (
            "sample_video",
            {"camera_id": "cam_01", "fps": 2},
            "sample_video",
            "arguments: unexpected argument(s); allowed: camera_id",
        ),
        ("inspect_camera", {"camera_id": 1}, "inspect_camera", "camera_id: must be a string"),
        ("inspect_camera", None, "inspect_camera", "arguments: must be an object"),
        ("correlate_observations", {"all": True}, "correlate_observations", "takes no arguments"),
        (
            "get_supporting_frames",
            {"camera_id": "cam_01", "frame_indices": []},
            "get_supporting_frames",
            "frame_indices: must have at least 1 item",
        ),
        (
            "get_supporting_frames",
            {"camera_id": "cam_01", "frame_indices": [-1]},
            "get_supporting_frames",
            "frame_indices/0: must be >= 0",
        ),
        (
            "submit_hypothesis",
            {"hypothesis": _claim(region="")},
            "submit_hypothesis",
            "hypothesis/region: must be at least 1 character",
        ),
        ("teleport", {}, UNKNOWN_TOOL, "unknown tool; tools are: sample_video, inspect_camera"),
        # Malformed calls carrying the GT id: the error is built from the schema alone.
        ("inspect_camera", {"camera_id": ["cam_gt"]}, "inspect_camera", "must be a string"),
        ("inspect_camera", {"camera_id": {"id": "cam_gt"}}, "inspect_camera", "must be a string"),
        (
            "inspect_camera",
            {"camera_id": "cam_01", "cam_gt": 1},
            "inspect_camera",
            "unexpected argument(s); allowed: camera_id",
        ),
        ("cam_gt", {}, UNKNOWN_TOOL, "unknown tool"),
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
    assert failed["error"] == rejection_error(name, arguments)
    assert len(events) == 2  # nothing ran
    assert events[0][1]["args_summary"] == {"rejected": True}
    assert "cam_gt" not in str(info.value) and "cam_gt" not in json.dumps(events)


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


def test_a_refused_failure_message_still_closes_the_pair():
    """The API refuses a payload naming the GT camera; the pair must close regardless."""
    events: Events = []

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        if "cam_gt" in json.dumps(payload):
            raise GroundTruthAccessError(f"{event_type} payload references the GT camera")
        events.append((event_type, payload))

    def fail() -> None:
        raise ValueError("could not read cam_gt")

    with pytest.raises(ToolCallError) as info:
        _Trace(emit).call("inspect_camera", {}, fail, lambda _: {})
    assert _failed_call(events)["error"] == "ValueError: details withheld"
    assert str(info.value) == "ValueError: details withheld"
    assert info.value.__cause__ is None and info.value.__suppress_context__


def _run_all(session: ToolSession) -> None:
    for camera_id in session.camera_ids:
        session.sample_video(camera_id)
        session.inspect_camera(camera_id)
    session.correlate_observations()
    session.triangulate_region()
    session.reason_hypothesis()
    session.get_supporting_frames("cam_03", [2])
    session.submit_hypothesis()


STATE = (
    "manifests",
    "batches",
    "evidence",
    "clusters",
    "bundle",
    "raw_hypothesis",
    "hypothesis",
    "supporting_frames",
)


@pytest.mark.parametrize(
    ("tool", "arguments", "event"),
    [
        ("sample_video", {"camera_id": "cam_02"}, "camera.frames.sampled"),
        ("inspect_camera", {"camera_id": "cam_02"}, "camera.complete"),
        ("correlate_observations", {}, "evidence.linked"),
        ("triangulate_region", {}, "triangulation.updated"),
        ("reason_hypothesis", {}, "hypothesis.updated"),
        ("submit_hypothesis", {"hypothesis": _claim()}, "hypothesis.updated"),
    ],
)
def test_a_call_whose_events_fail_leaves_the_session_unchanged(
    scenario, consistent, media_root, tmp_path, tool, arguments, event
):
    refused: set[str] = set()

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        if event_type in refused:
            raise RuntimeError(f"{event_type} dropped")

    session = ToolSession(
        scenario.model_view(), consistent, emit, run_dir=tmp_path / "run", media_root=media_root
    )
    _run_all(session)
    before = {name: copy.deepcopy(getattr(session, name)) for name in STATE}
    refused.add(event)
    with pytest.raises(ToolCallError, match=f"{event} dropped"):
        session.call_tool(tool, arguments)
    assert {name: getattr(session, name) for name in STATE} == before


@pytest.mark.parametrize(
    ("tool", "arguments", "cleared"),
    [
        ("sample_video", {"camera_id": "cam_02"}, {"evidence", "clusters", "bundle"}),
        ("inspect_camera", {"camera_id": "cam_02"}, {"evidence", "clusters", "bundle"}),
        ("correlate_observations", {}, {"bundle"}),
        ("triangulate_region", {}, set()),
        ("reason_hypothesis", {}, set()),
    ],
)
def test_rerunning_a_tool_clears_everything_downstream(session, tool, arguments, cleared):
    _run_all(session)
    session.call_tool(tool, arguments)
    if tool == "sample_video":
        assert "cam_02" not in session.batches
    for name in cleared:
        assert getattr(session, name) is None, name
    assert session.hypothesis is None
    assert session.supporting_frames == {}
    if tool != "reason_hypothesis":
        assert session.raw_hypothesis is None


def test_calls_from_parallel_threads_never_interleave(session, events):
    threads = [
        threading.Thread(target=session.sample_video, args=(camera_id,))
        for camera_id in session.camera_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    pairs = [(t, p["call_id"]) for t, p in events if t in {"tool.started", "tool.completed"}]
    assert len(pairs) == 6
    for opened, closed in zip(pairs[::2], pairs[1::2], strict=True):
        assert opened[0] == "tool.started" and closed[0] == "tool.completed"
        assert opened[1] == closed[1]


def test_integral_float_frame_indices_are_accepted(session):
    session.sample_video("cam_03")
    result = session.call_tool(
        "get_supporting_frames", {"camera_id": "cam_03", "frame_indices": [1.0, 2]}
    )
    assert [f["index"] for f in result["frames"]] == [1, 2]

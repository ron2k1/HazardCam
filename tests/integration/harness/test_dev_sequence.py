"""P10: the NON-AGENT dev-sequence harness, end to end under the fixture profile.

Media and fixture profiles come from ``conftest.py`` (TEST MEDIA, TEST FIXTURES).
"""

from __future__ import annotations

import json

import pytest

from apps.api.schemas import (
    ALERT_EVENT_TYPES,
    EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    Hypothesis,
    validate_json,
)
from harness.dev_sequence import HARNESS_ID, SEQUENCE, run_dev_sequence_detailed
from tools.session import TOOL_NAMES, ToolCallError
from tools.submit import NOT_DIRECTLY_VISIBLE, submit_hypothesis

pytestmark = pytest.mark.media

GT_TOKENS = ("cam_gt", "hidden_ground_truth")
SAMPLED_FRAMES = 4  # conftest clips are 4 s, sampled at the fixture profile's 1 fps

# Which tool call each domain event must be emitted inside.
OWNER = {
    "camera.started": "sample_video",
    "camera.frames.sampled": "sample_video",
    "camera.observation": "inspect_camera",
    "camera.complete": "inspect_camera",
    "fusion.started": "correlate_observations",
    "evidence.linked": "correlate_observations",
    "triangulation.updated": "triangulate_region",
}


def _run(scenario, profile, media_root, run_dir, **kw):
    events: list[tuple[str, dict]] = []
    result = run_dev_sequence_detailed(
        scenario,
        profile,
        lambda t, p: events.append((t, json.loads(json.dumps(p)))),
        run_dir=run_dir,
        media_root=media_root,
        **kw,
    )
    return result, events


def test_full_sequence_covers_the_catalog_and_declares_no_agent(
    scenario, consistent, media_root, tmp_path
):
    result, events = _run(scenario, consistent, media_root, tmp_path / "run")
    types = [t for t, _ in events]
    # Terminal and alert events come from the run manager, not the harness.
    assert set(types) == set(EVENT_TYPES) - TERMINAL_EVENT_TYPES - ALERT_EVENT_TYPES
    assert types[:2] == ["run.started", "orchestrator.started"]
    assert events[0][1]["harness"] == HARNESS_ID == "dev-sequence"
    assert events[1][1] == {"harness": HARNESS_ID, "agent": False, "sequence": list(SEQUENCE)}
    assert [p["camera_id"] for t, p in events if t == "camera.started"] == [
        "cam_01",
        "cam_02",
        "cam_03",
    ]
    for t, p in events:
        if t == "camera.frames.sampled":
            assert [f["index"] for f in p["frames"]] == list(range(SAMPLED_FRAMES))
            assert all(isinstance(f["url"], str) for f in p["frames"])
    assert [p["final"] for t, p in events if t == "hypothesis.updated"] == [False, True]

    final = result.hypothesis
    assert (final.event_type, final.region, final.confidence) == (
        "vehicle_stop",
        "blind_zone_02",
        0.74,
    )
    assert result.bundle.status == "ok"
    assert set(result.supporting_frames) == {"cam_01", "cam_02", "cam_03"}
    assert [f.index for f in result.supporting_frames["cam_03"]] == [2, 3]


def test_tools_run_in_the_fixed_order(scenario, consistent, media_root, tmp_path):
    assert set(SEQUENCE) == set(TOOL_NAMES)
    _, events = _run(scenario, consistent, media_root, tmp_path / "run")
    tools = [p["tool"] for t, p in events if t == "tool.started"]
    assert tools == [
        *["sample_video", "inspect_camera"] * 3,
        "correlate_observations",
        "triangulate_region",
        "reason_hypothesis",
        *["get_supporting_frames"] * 3,
        "submit_hypothesis",
    ]


def test_every_domain_event_is_emitted_inside_its_tool_pair(
    scenario, consistent, media_root, tmp_path
):
    _, events = _run(scenario, consistent, media_root, tmp_path / "run")
    open_call = None
    started, completed = [], []
    for t, p in events:
        if t == "tool.started":
            assert open_call is None, "tool calls must not nest"
            open_call = p
            started.append(p["call_id"])
        elif t == "tool.completed":
            assert open_call and p["call_id"] == open_call["call_id"] and p["ok"]
            completed.append(p["call_id"])
            open_call = None
        elif t == "hypothesis.updated":
            want = "submit_hypothesis" if p["final"] else "reason_hypothesis"
            assert open_call and open_call["tool"] == want
        elif t in OWNER:
            assert open_call and open_call["tool"] == OWNER[t], t
    assert started == completed and len(set(started)) == len(started)


def test_final_hypothesis_is_the_submit_gate_output_and_artifacts_persist(
    scenario, consistent, media_root, tmp_path
):
    run_dir = tmp_path / "run"
    result, _ = _run(scenario, consistent, media_root, run_dir)
    assert result.hypothesis == submit_hypothesis(result.raw_hypothesis, result.bundle)
    assert NOT_DIRECTLY_VISIBLE in result.hypothesis.limitations

    saved = Hypothesis.model_validate_json((run_dir / "hypothesis.json").read_bytes())
    assert saved == result.hypothesis
    validate_json("evidence_bundle", json.loads((run_dir / "evidence_bundle.json").read_text()))
    telemetry = json.loads((run_dir / "telemetry.json").read_text())
    assert telemetry["profile"] == "fixture" and set(telemetry["tool_latency_ms"]) == set(SEQUENCE)
    frames = sorted(p.relative_to(run_dir).as_posix() for p in (run_dir / "frames").rglob("*.jpg"))
    assert frames == [
        f"frames/{c}/{i:04d}.jpg" for c in ("cam_01", "cam_02", "cam_03") for i in range(4)
    ]


def test_ground_truth_never_reaches_events_or_disk(scenario, consistent, media_root, tmp_path):
    run_dir = tmp_path / "run"
    _, events = _run(scenario, consistent, media_root, run_dir)
    text = json.dumps(events)
    on_disk = " ".join(p.as_posix() for p in run_dir.rglob("*"))
    on_disk += " ".join(p.read_text() for p in run_dir.glob("*.json"))
    for token in GT_TOKENS:
        assert token not in text and token not in on_disk


def test_no_observations_abstains_through_the_gate(scenario, make_profile, media_root, tmp_path):
    abstain = {"event_type": "unknown", "region": "unknown", "confidence": 0.1, "reason": "none"}
    profile = make_profile({}, abstain)
    result, events = _run(scenario, profile, media_root, tmp_path / "run")
    assert result.hypothesis.abstained and result.bundle.status == "insufficient"
    types = {t for t, _ in events}
    assert not types & {"camera.observation", "evidence.linked"}
    (tri,) = [p for t, p in events if t == "triangulation.updated"]
    assert tri["candidates"] == [] and tri["rays"] == []
    assert "get_supporting_frames" not in [p["tool"] for t, p in events if t == "tool.started"]


def test_failed_tool_closes_its_pair_and_names_the_stage(scenario, consistent, tmp_path):
    empty_media = tmp_path / "no_media"
    empty_media.mkdir()
    events: list[tuple[str, dict]] = []
    with pytest.raises(ToolCallError) as info:
        run_dev_sequence_detailed(
            scenario,
            consistent,
            lambda t, p: events.append((t, p)),
            run_dir=tmp_path / "run",
            media_root=empty_media,
        )
    assert info.value.stage == "sample_video"
    last_type, last = events[-1]
    assert last_type == "tool.completed"
    assert last["tool"] == "sample_video" and last["ok"] is False
    assert last["error"].startswith("FileNotFoundError")

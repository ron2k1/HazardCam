"""P03: the run event log: thread-safe seq ordering, terminal handling, persistence."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime

import pytest

from apps.api.schemas import (
    GroundTruthAccessError,
    Hypothesis,
    Observation,
    RunRecord,
    validate_json,
)
from apps.api.services.gt_guard import GtGuard
from apps.api.services.runs import RunHandle, short_error

HYPOTHESIS = Hypothesis(event_type="unknown", region="unknown", confidence=0.1, reason="none")


@pytest.fixture
def make_handle(tmp_path, scenario):
    def _make() -> RunHandle:
        now = datetime.now(UTC)
        record = RunRecord(
            run_id="run_test",
            scenario_id=scenario.id,
            profile="fixture",
            state="queued",
            created_at=now,
            updated_at=now,
        )
        return RunHandle(
            record, tmp_path, GtGuard.for_scenario(scenario), "cam_gt", asyncio.get_running_loop()
        )

    return _make


async def _drain(handle: RunHandle, after_seq: int = 0) -> list[dict]:
    return [json.loads(line) async for _, line in handle.stream(after_seq)]


async def test_concurrent_emitters_produce_contiguous_ordered_log(make_handle, tmp_path):
    handle = make_handle()
    handle.mark_running()
    barrier = threading.Barrier(4)

    def worker(cam: str) -> None:
        barrier.wait()
        for i in range(50):
            handle.emit("camera.observation", {"camera_id": cam, "i": i})

    stream = asyncio.create_task(_drain(handle))
    await asyncio.gather(*(asyncio.to_thread(worker, f"cam_{n:02d}") for n in range(4)))
    handle.finish_complete(HYPOTHESIS)
    envelopes = await asyncio.wait_for(stream, timeout=5)

    assert [e["seq"] for e in envelopes] == list(range(1, 202))
    assert envelopes[-1]["type"] == "run.complete"
    for cam in (f"cam_{n:02d}" for n in range(4)):  # per-thread order is preserved
        assert [
            e["payload"]["i"] for e in envelopes if e["payload"].get("camera_id") == cam
        ] == list(range(50))
    persisted = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert persisted == envelopes == handle.envelopes()
    for envelope in envelopes:
        validate_json("sse_envelope", envelope)
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["state"] == "complete" and record["last_seq"] == 201


async def test_terminal_state_flips_with_the_terminal_event(make_handle):
    handle = make_handle()
    handle.emit("run.started", {"scenario_id": "scenario_001"})
    handle.finish_failed("inspect_camera", "RuntimeError: boom")
    assert handle.record.state == "queued"  # nothing applied until the loop runs the append
    await asyncio.sleep(0)
    assert handle.finished and handle.record.state == "failed"
    assert handle.record.error == "RuntimeError: boom" and handle.record.last_seq == 2
    with pytest.raises(RuntimeError):
        handle.emit("camera.started", {"camera_id": "cam_01"})
    with pytest.raises(RuntimeError):
        handle.finish_complete(HYPOTHESIS)


async def test_emit_rejects_terminal_unknown_and_non_object_payloads(make_handle):
    handle = make_handle()
    for event_type in ("run.complete", "run.failed", "camera.exploded"):
        with pytest.raises(ValueError):
            handle.emit(event_type, {})
    with pytest.raises(TypeError):
        handle.emit("camera.started", ["not", "an", "object"])
    with pytest.raises(ValueError):
        handle.emit("camera.observation", {"confidence": float("nan")})
    await asyncio.sleep(0)
    assert handle.envelopes() == []


async def test_gt_reference_is_refused_before_a_seq_is_spent(make_handle):
    handle = make_handle()
    with pytest.raises(GroundTruthAccessError):
        handle.emit("camera.started", {"camera_id": "cam_gt"})
    handle.emit("camera.started", {"camera_id": "cam_01"})
    await asyncio.sleep(0)
    assert [e["seq"] for e in handle.envelopes()] == [1]


async def test_failure_text_is_redacted(make_handle):
    handle = make_handle()
    handle.finish_failed("cam_gt stage", "GroundTruthAccessError: camera 'cam_gt' is withheld")
    envelopes = await _drain(handle)
    assert "cam_gt" not in json.dumps(envelopes)


async def test_pydantic_payloads_are_serialised(make_handle):
    handle = make_handle()
    obs = Observation(
        id="o1", t_start=1.0, t_end=2.0, cue_type="c", description="d", confidence=0.5
    )
    handle.emit("camera.observation", {"camera_id": "cam_01", "observation": obs})
    handle.finish_complete(HYPOTHESIS)
    envelopes = await _drain(handle)
    assert envelopes[0]["payload"]["observation"]["id"] == "o1"
    assert envelopes[1]["payload"]["hypothesis"]["event_type"] == "unknown"


async def test_stream_past_the_end_of_a_finished_run_closes(make_handle):
    handle = make_handle()
    handle.emit("run.started", {})
    handle.finish_complete(HYPOTHESIS)
    await asyncio.sleep(0)
    assert await asyncio.wait_for(_drain(handle, after_seq=2), timeout=1) == []
    assert [e["seq"] for e in await _drain(handle, after_seq=1)] == [2]


async def test_tool_started_sets_stage(make_handle):
    handle = make_handle()
    assert handle.stage == "startup"
    handle.emit("tool.started", {"call_id": "c1", "tool": "correlate_observations"})
    assert handle.stage == "correlate_observations"


def test_short_error_is_one_bounded_line():
    message = short_error(ValueError("line one\nline two   " + "x" * 1000))
    assert message.startswith("ValueError: line one line two")
    assert "\n" not in message and len(message) <= 300
    assert short_error(KeyError()) == "KeyError"

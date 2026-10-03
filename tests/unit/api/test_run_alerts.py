"""Alert messages on the run event log: placement, executor limits, best effort, no leaks."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import pytest

from apps.api.schemas import Hypothesis, RunRecord, validate_json
from apps.api.services.alert_feed import AlertFeed
from apps.api.services.alert_messages import MessageContext
from apps.api.services.gt_guard import GtGuard
from apps.api.services.runs import RunHandle

FINAL = Hypothesis(
    event_type="vehicle_stop",
    region="blind_zone_02",
    confidence=0.74,
    evidence_ids=["cam_02.o1"],
    reason="cam_02.o1 at blind_zone_02",
)


def _observation(camera_id: str, n: int, cue: str) -> dict:
    return {
        "camera_id": camera_id,
        "observation": {
            "id": f"{camera_id}.o{n}",
            "t_start": 1.0,
            "t_end": 3.0,
            "cue_type": cue,
            "description": "Cars swerve around something",
            "confidence": 0.8,
        },
    }


@pytest.fixture
def make_handle(tmp_path, scenario):
    def _make(executor: object = None, *, alerts: bool = True) -> RunHandle:
        now = datetime.now(UTC)
        record = RunRecord(
            run_id="run_test",
            scenario_id=scenario.id,
            profile="fixture",
            state="queued",
            created_at=now,
            updated_at=now,
        )
        feed = AlertFeed.for_executor(MessageContext.from_scenario(scenario), executor)
        return RunHandle(
            record,
            tmp_path,
            GtGuard.for_scenario(scenario),
            "cam_gt",
            asyncio.get_running_loop(),
            alerts=feed if alerts else None,
        )

    return _make


async def _settle(handle: RunHandle) -> list[dict]:
    await asyncio.sleep(0)  # let call_soon_threadsafe appends land
    return handle.envelopes()


async def test_the_ping_follows_its_observation_and_the_final_message_closes(make_handle):
    handle = make_handle()
    handle.emit("run.started", {"scenario_id": "scenario_001"})
    handle.emit("camera.observation", _observation("cam_01", 1, "person_edge_transit"))
    handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
    handle.emit("camera.observation", _observation("cam_03", 1, "human_reaction"))
    handle.publish_final_alert(FINAL)
    handle.finish_complete(FINAL)
    envelopes = await _settle(handle)
    assert [e["type"] for e in envelopes] == [
        "run.started",
        "camera.observation",
        "camera.observation",
        "alert.message",  # ping right after the cam_02 traffic reaction
        "alert.delivery",
        "camera.observation",
        "alert.message",
        "alert.delivery",
        "run.complete",
    ]
    assert [e["seq"] for e in envelopes] == list(range(1, 10))
    ping, final = envelopes[3]["payload"]["message"], envelopes[6]["payload"]["message"]
    assert (ping["id"], ping["kind"], ping["evidence_ids"]) == ("msg_01", "ping", ["cam_02.o1"])
    assert (final["id"], final["kind"]) == ("msg_02", "alert")
    assert [envelopes[i]["payload"]["status"] for i in (4, 7)] == ["not_connected"] * 2
    assert [envelopes[i]["payload"]["message_id"] for i in (4, 7)] == ["msg_01", "msg_02"]
    for envelope in envelopes:
        validate_json("sse_envelope", envelope)


async def test_executors_cannot_forge_messages_or_report_on_unknown_ones(make_handle):
    agent = type("Agent", (), {"delivers_alerts": True})()
    handle = make_handle(agent)
    forged = {"message": {"id": "msg_01", "kind": "alert"}}
    with pytest.raises(ValueError, match="run manager"):
        handle.emit("alert.message", forged)
    stray = {"message_id": "msg_01", "channel": "telegram", "status": "sent", "detail": None}
    with pytest.raises(ValueError, match="unknown message"):
        handle.emit("alert.delivery", stray)
    with pytest.raises(ValueError):
        handle.emit("alert.delivery", {"message_id": "msg_01", "status": "delivered"})
    handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
    handle.emit("alert.delivery", stray)  # the capable agent reports on msg_01 itself
    types = [e["type"] for e in await _settle(handle)]
    assert types == ["camera.observation", "alert.message", "alert.delivery"]


async def test_a_composer_failure_never_breaks_a_tool_call(make_handle, monkeypatch, caplog):
    handle = make_handle()

    def boom(*_args, **_kwargs):
        raise RuntimeError("composer bug")

    monkeypatch.setattr("apps.api.services.alert_feed.compose_ping", boom)
    monkeypatch.setattr("apps.api.services.alert_feed.compose_final", boom)
    with caplog.at_level(logging.WARNING, logger="apps.api.services.runs"):
        handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
        handle.publish_final_alert(FINAL)
        handle.finish_complete(FINAL)
    types = [e["type"] for e in await _settle(handle)]
    assert types == ["camera.observation", "run.complete"]
    assert "alert message skipped (RuntimeError)" in caplog.text
    assert "composer bug" not in caplog.text  # details only at debug level


async def test_a_leaking_hypothesis_gets_no_message(make_handle):
    handle = make_handle()
    leaky = FINAL.model_copy(update={"reason": "the cam_gt view shows it"})
    handle.publish_final_alert(leaky)
    assert await _settle(handle) == []


async def test_a_message_naming_the_withheld_camera_is_skipped_not_redacted(
    make_handle, monkeypatch, caplog
):
    from apps.api.services import alert_feed

    real = alert_feed.compose_ping

    def leaky_ping(*args, **kwargs):
        message = real(*args, **kwargs)
        return message.model_copy(update={"headline": "Seen on cam_gt", "text": "cam_gt"})

    monkeypatch.setattr(alert_feed, "compose_ping", leaky_ping)
    handle = make_handle()
    with caplog.at_level(logging.WARNING, logger="apps.api.services.runs"):
        handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
        handle.publish_final_alert(FINAL)
        handle.finish_complete(FINAL)
    envelopes = await _settle(handle)
    types = [e["type"] for e in envelopes]
    # the ping is gone (no "[withheld]" copy, no delivery); the closing message still comes
    assert types == ["camera.observation", "alert.message", "alert.delivery", "run.complete"]
    assert "[withheld]" not in json.dumps(envelopes)
    assert "alert msg_01 skipped (withheld camera)" in caplog.text


async def test_runs_without_a_feed_behave_as_before(make_handle):
    handle = make_handle(alerts=False)
    handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
    handle.publish_final_alert(FINAL)
    handle.finish_complete(FINAL)
    types = [e["type"] for e in await _settle(handle)]
    assert types == ["camera.observation", "run.complete"]
    with pytest.raises(ValueError, match="unknown message"):
        make_handle(alerts=False).emit(
            "alert.delivery", {"message_id": "msg_01", "status": "sent", "detail": None}
        )


async def test_persisted_log_matches_and_carries_plain_text(make_handle, tmp_path):
    handle = make_handle()
    handle.emit("camera.observation", _observation("cam_02", 1, "traffic_reaction"))
    handle.publish_final_alert(FINAL)
    handle.finish_complete(FINAL)
    envelopes = await _settle(handle)
    persisted = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert persisted == envelopes
    texts = [e["payload"]["message"]["text"] for e in envelopes if e["type"] == "alert.message"]
    assert texts[1].splitlines()[:2] == [
        "CHECK SOON — Vehicle stopped: Intersection core",
        "What to do: Check that the stopped vehicle is not blocking the way.",
    ]
    for text in texts:
        assert "cam_" not in text and "blind_zone" not in text and "0." not in text

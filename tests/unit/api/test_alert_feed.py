"""The per-run alert feed: one ping, one closing message, delivery status per capability."""

from __future__ import annotations

import pytest

from apps.api.schemas import AlertDelivery, Hypothesis
from apps.api.services.alert_feed import NOT_CONNECTED_DETAIL, AlertFeed
from apps.api.services.alert_messages import MessageContext

FINAL = Hypothesis(
    event_type="vehicle_stop",
    region="blind_zone_02",
    confidence=0.74,
    evidence_ids=["cam_01.o1", "cam_02.o1"],
    reason="cam_01.o1 and cam_02.o1 cluster at blind_zone_02 (score 0.71).",
)
ABSTAIN = Hypothesis(event_type="unknown", region="unknown", confidence=0.2, reason="none")


def _obs(camera_id, n, cue, t0=1.0, t1=2.0, description="Something moves"):
    return {
        "camera_id": camera_id,
        "observation": {
            "id": f"{camera_id}.o{n}",
            "t_start": t0,
            "t_end": t1,
            "cue_type": cue,
            "description": description,
            "confidence": 0.8,
        },
    }


@pytest.fixture
def ctx(scenario) -> MessageContext:
    return MessageContext.from_scenario(scenario)


def test_one_ping_on_the_first_abnormal_observation(ctx):
    feed = AlertFeed(ctx)
    assert feed.observe("camera.observation", _obs("cam_01", 1, "person_edge_transit")) is None
    assert feed.observe("camera.observation", _obs("cam_01", 2, "vehicle_heading_change")) is None
    ping = feed.observe("camera.observation", _obs("cam_02", 1, "traffic_reaction"))
    assert ping is not None and (ping.id, ping.kind) == ("msg_01", "ping")
    assert ping.headline == "Heads-up from Camera 2: Vehicles braking or swerving"
    assert ping.evidence_ids == ["cam_02.o1"]
    assert feed.observe("camera.observation", _obs("cam_03", 1, "human_reaction")) is None
    assert feed.message_ids == ["msg_01"] and feed.knows("msg_01")


def test_hidden_or_malformed_observations_are_ignored(ctx):
    feed = AlertFeed(ctx)
    assert feed.observe("camera.observation", _obs("cam_gt", 1, "traffic_reaction")) is None
    assert feed.observe("camera.observation", {"camera_id": "cam_01"}) is None
    broken = _obs("cam_01", 1, "traffic_reaction")
    del broken["observation"]["t_start"]
    assert feed.observe("camera.observation", broken) is None
    assert feed.message_ids == []
    message = feed.final(FINAL)
    assert "cam_gt" not in message.camera_ids and message.id == "msg_01"


def test_final_message_uses_linked_evidence_and_candidates(ctx):
    feed = AlertFeed(ctx)
    feed.observe("camera.observation", _obs("cam_01", 1, "vehicle_slowing_or_stopping"))
    feed.observe("camera.observation", _obs("cam_02", 1, "traffic_reaction"))  # ping msg_01
    feed.observe("fusion.started", {})
    feed.observe(
        "evidence.linked",
        {
            "evidence": [
                {
                    "id": "cam_01.o1",
                    "camera_id": "cam_01",
                    "t_start": 4.0,
                    "t_end": 6.0,
                    "cue_type": "vehicle_slowing_or_stopping",
                    "description": "A car brakes hard at the crossing",
                    "confidence": 0.9,
                },
                {
                    "id": "cam_02.o1",
                    "camera_id": "cam_02",
                    "t_start": 5.0,
                    "t_end": 9.0,
                    "cue_type": "traffic_reaction",
                    "description": "Cars swerve around something at cam_02.o1 (bearing 185°)",
                    "confidence": 0.8,
                },
            ]
        },
    )
    feed.observe("triangulation.updated", {"candidates": [{"id": "blind_zone_02"}]})
    message = feed.final(FINAL)
    assert (message.id, message.kind, message.level) == ("msg_02", "alert", "warning")
    assert message.headline == "Vehicle stopped: Intersection core"
    assert message.line("where") == "Intersection core (near Camera 2)"
    # cam_02's description holds a bearing, so it is dropped whole and cam_01's is used
    assert message.line("what") == (
        "Camera 1: A car brakes hard at the crossing. "
        "Not seen directly; pieced together from the other cameras."
    )
    assert message.line("when") == "0:04–0:09 into the clip"
    assert (message.t_start, message.t_end) == (4.0, 9.0)
    assert feed.message_ids == ["msg_01", "msg_02"]
    assert feed.final(FINAL) is None  # once per run
    assert feed.observe("camera.observation", _obs("cam_03", 1, "human_reaction")) is None


def test_fusion_restart_drops_stale_evidence(ctx):
    feed = AlertFeed(ctx)
    stale = {
        "id": "cam_03.o9",
        "camera_id": "cam_03",
        "t_start": 0.0,
        "t_end": 1.0,
        "cue_type": "traffic_reaction",
        "description": "Old",
        "confidence": 0.9,
    }
    feed.observe("evidence.linked", {"evidence": [stale]})
    feed.observe("triangulation.updated", {"candidates": [{"id": "region_01", "center": [9, 9]}]})
    feed.observe("fusion.started", {})
    message = feed.final(FINAL.model_copy(update={"region": "region_01"}))
    assert message.camera_ids == []  # nothing linked after the restart
    assert message.line("where") == "Exact spot unclear"


def test_observations_stand_in_when_nothing_was_linked(ctx):
    feed = AlertFeed(ctx)
    feed.observe(
        "camera.observation",
        _obs("cam_03", 1, "vehicle_slowing_or_stopping", 2.0, 3.0, "A van stops"),
    )
    message = feed.final(FINAL.model_copy(update={"evidence_ids": ["cam_03.o1"]}))
    assert message.camera_ids == ["cam_03"]
    assert "Camera 3: A van stops." in message.line("what")


def test_calm_messages_are_not_delivered(ctx):
    feed = AlertFeed(ctx)
    message = feed.final(ABSTAIN)
    assert message.kind == "unconfirmed" and feed.delivery(message) is None
    feed = AlertFeed(ctx)
    clear = feed.final(ABSTAIN.model_copy(update={"event_type": "no_event", "confidence": 0.8}))
    assert clear.kind == "all_clear" and feed.delivery(clear) is None


def test_without_the_capability_delivery_is_not_connected(ctx):
    class Harness:  # no delivers_alerts attribute
        def deliver_alert(self, message):  # must not be called without the flag
            raise AssertionError("called")

    feed = AlertFeed.for_executor(ctx, Harness())
    ping = feed.observe("camera.observation", _obs("cam_02", 1, "traffic_reaction"))
    assert feed.delivery(ping) == {
        "message_id": "msg_01",
        "channel": "telegram",
        "status": "not_connected",
        "detail": NOT_CONNECTED_DETAIL,
    }
    truthy = type("Truthy", (), {"delivers_alerts": "yes"})()
    assert AlertFeed.for_executor(ctx, truthy).delivers_alerts is False  # only `True` counts


def test_a_capable_executor_without_a_hook_reports_delivery_itself(ctx):
    agent = type("Agent", (), {"delivers_alerts": True})()
    feed = AlertFeed.for_executor(ctx, agent)
    assert feed.delivery(feed.final(FINAL)) is None


@pytest.mark.parametrize(
    ("result", "status", "detail"),
    [
        ({"status": "sent"}, "sent", None),
        ({"status": "skipped", "detail": "Quiet hours."}, "skipped", "Quiet hours."),
        ({"status": "delivered"}, "failed", "The delivery hook returned no status."),
        (None, "failed", "The delivery hook returned no status."),
        (
            {"status": "failed", "detail": "401 from https://api.telegram.org/bot1/x"},
            "failed",
            "401 from <url>",
        ),
    ],
)
def test_the_delivery_hook_result_is_normalised(ctx, result, status, detail):
    sent = []

    class Agent:
        delivers_alerts = True

        def deliver_alert(self, message):
            sent.append(message)
            return result

    feed = AlertFeed.for_executor(ctx, Agent())
    message = feed.final(FINAL)
    delivery = feed.delivery(message)
    AlertDelivery.model_validate(delivery)
    assert (delivery["status"], delivery["detail"]) == (status, detail)
    assert sent == [message.model_dump(mode="json")]


def test_a_crashing_hook_is_a_redacted_failure(ctx):
    token = "123456789:" + "A" * 35

    class Agent:
        delivers_alerts = True

        def deliver_alert(self, message):
            raise ConnectionError(f"no route to https://api.telegram.org/bot{token}/sendMessage")

    feed = AlertFeed.for_executor(ctx, Agent())
    delivery = feed.delivery(feed.final(FINAL))
    assert delivery["status"] == "failed"
    assert delivery["detail"] == "no route to <url>"  # no exception class name
    assert token not in str(delivery)

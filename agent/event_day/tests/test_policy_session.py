"""D00: the bounded policy over a real ``ToolSession`` (fixture profile, test media).

A scripted caller stands in for the OpenClaw agent and follows the playbook order. D01
replaces it with the real agent through the tool registration.
"""

from __future__ import annotations

import json
import threading

import pytest

from agent.event_day.policy import (
    ALERT_NOT_DUE,
    ALERT_SENT,
    ALERT_SKIPPED,
    AgentPolicy,
    AlertRoute,
    Budget,
    run_brief,
)
from apps.api.schemas import UNKNOWN, Hypothesis
from apps.api.schemas.contracts import def_validator
from tools.session import ToolSession
from tools.submit import NOT_DIRECTLY_VISIBLE

from .conftest import CLAIM

pytestmark = pytest.mark.media

RUN_ID = "run_20261003T170000Z_abc123"
CHAT = "-1001234567890"
# Bot-token shaped, built at run time so no token-like literal sits in the repo.
TOKEN = ":".join(["123456789", "AAE" + "x7_" * 11])
GT_TOKENS = ("cam_gt", "hidden_ground_truth")


class Run:
    """One policy over one fixture session, recording every event and alert update."""

    def __init__(self, scenario, profile, media_root, run_dir, **policy_kw):
        self.events: list[tuple[str, dict]] = []
        self.alerts: list[dict] = []

        def emit(event_type: str, payload: dict) -> None:
            self.events.append((event_type, json.loads(json.dumps(payload))))

        view = scenario.model_view()
        self.session = ToolSession(view, profile, emit, run_dir=run_dir, media_root=media_root)
        policy_kw.setdefault("alert_listener", self.alerts.append)
        self.policy = AgentPolicy(self.session, emit=emit, **policy_kw)

    def call(self, name, arguments=None):
        return self.policy.call(name, arguments).to_json()

    def through_reasoning(self):
        for cam in self.session.camera_ids:
            assert self.call("sample_video", {"camera_id": cam})["ok"]
            assert self.call("inspect_camera", {"camera_id": cam})["ok"]
        assert self.call("correlate_observations", {})["ok"]
        bundle = self.call("triangulate_region", {})
        assert bundle["ok"]
        reasoned = self.call("reason_hypothesis", {})
        assert reasoned["ok"]
        return bundle["result"], reasoned["result"]

    def text(self) -> str:
        return json.dumps([self.events, self.policy.summary(), self.alerts])


@pytest.fixture
def run(scenario, make_profile, media_root, tmp_path):
    def make(hypothesis=CLAIM, **policy_kw) -> Run:
        policy_kw.setdefault("run_id", RUN_ID)
        policy_kw.setdefault("alert_route", AlertRoute(CHAT))
        return Run(scenario, make_profile(hypothesis), media_root, tmp_path / "run", **policy_kw)

    return make


def test_a_clean_run_submits_closes_and_hands_the_agent_one_alert(run):
    r = run()
    bundle, _ = r.through_reasoning()
    frames_by_camera = {e["camera_id"]: e["supporting_frames"] for e in bundle["evidence"]}
    for cam, frames in frames_by_camera.items():
        assert r.call("get_supporting_frames", {"camera_id": cam, "frame_indices": frames})["ok"]
    assert not r.policy.wait_closed(0)

    submitted = r.call("submit_hypothesis", {})
    assert submitted["ok"] and r.policy.wait_closed(0)
    def_validator("tool_call", "submit_hypothesis_result").validate(submitted["result"])
    final = Hypothesis.model_validate(submitted["result"])
    assert (final.event_type, final.region, final.confidence) == (
        "vehicle_stop",
        "blind_zone_02",
        0.74,
    )
    assert final.alternatives and NOT_DIRECTLY_VISIBLE in final.limitations
    assert r.policy.final_hypothesis == final == r.session.hypothesis

    alert = submitted["alert"]
    assert alert["send"] is True and alert["tool"] == "message"
    args = alert["arguments"]
    assert {k: args[k] for k in ("action", "channel", "target")} == {
        "action": "send",
        "channel": "telegram",
        "target": CHAT,
    }
    lines = args["message"].splitlines()
    assert lines[1:5] == [
        "event: vehicle_stop",
        "confidence: 0.74",
        "region: blind_zone_02 (coarse)",
        "cameras: cam_01 t=1.0-1.6s; cam_02 t=1.2-2.0s; cam_03 t=2.1-3.0s",
    ]
    assert f"run: {RUN_ID}" in lines
    assert not any(s in args["message"] for s in (".jpg", "frames/", "http", *GT_TOKENS))

    # The agent garbles the text: the grant carries the policy's own arguments.
    grant = r.policy.authorize_alert({"action": "send", "channel": "telegram", "message": "hi"})
    assert grant.allowed and grant.arguments == args
    again = r.policy.authorize_alert(args)
    assert not again.allowed and "already" in again.reason
    assert r.policy.record_alert(True)["status"] == ALERT_SENT
    assert [a["status"] for a in r.alerts] == ["due", "sending", "sending", "sent"]

    after = r.call("sample_video", {"camera_id": "cam_01"})
    assert after["refused"] and "run is closed" in after["error"]
    summary = r.policy.summary()
    assert summary["alert"]["grants"] == 1 and summary["alert"]["refused"] == 1
    assert CHAT not in json.dumps(summary)


def test_a_failed_telegram_send_is_skipped_and_changes_nothing(run):
    r = run()
    r.through_reasoning()
    final = r.call("submit_hypothesis", {})["result"]
    events_before = len(r.events)
    assert r.policy.authorize_alert({"action": "send", "channel": "telegram"}).allowed
    error = f"fetch https://api.telegram.org/bot{TOKEN}/sendMessage: ENOTFOUND bot{TOKEN}"
    state = r.policy.record_alert(False, error)
    assert state["status"] == ALERT_SKIPPED and state["reason"].startswith("delivery failed")
    assert "failed" not in state["status"]
    assert len(r.events) == events_before  # nothing more reaches the SSE stream
    assert r.session.hypothesis.model_dump(mode="json") == final
    assert TOKEN not in r.text() and "api.telegram.org" not in r.text()
    assert r.policy.record_alert(True)["status"] == ALERT_SKIPPED  # settled; not reopened


def test_an_alert_the_agent_never_sends_expires_as_skipped(run):
    r = run()
    r.through_reasoning()
    r.call("submit_hypothesis", {})
    assert r.policy.expire_alert()["status"] == ALERT_SKIPPED
    refused = r.policy.authorize_alert({"action": "send", "channel": "telegram"})
    assert not refused.allowed and "sends no alert" in refused.reason


def test_an_abstaining_run_sends_no_alert_and_keeps_the_claim_visible(run):
    r = run(CLAIM | {"confidence": 0.25})
    r.through_reasoning()
    submitted = r.call("submit_hypothesis", {})
    final = Hypothesis.model_validate(submitted["result"])
    assert final.abstained and final.region == UNKNOWN
    # The gate ranks alternatives by confidence: the demoted 0.25 claim follows its 0.39 rival.
    assert [a.event_type for a in final.alternatives] == ["vehicle_turnaround", "vehicle_stop"]
    assert any("abstention floor" in lim for lim in final.limitations)
    assert submitted["alert"]["send"] is False and "abstained" in submitted["alert"]["reason"]
    assert r.policy.alert_summary()["status"] == ALERT_NOT_DUE
    for params in ({"action": "send", "channel": "telegram"}, {"action": "delete"}):
        assert not r.policy.authorize_alert(params).allowed
    assert r.alerts[-1]["status"] == ALERT_NOT_DUE


def test_a_rival_the_reasoner_ranked_as_high_forces_an_abstention(run):
    r = run(CLAIM | {"alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.74}]})
    r.through_reasoning()
    submitted = r.call("submit_hypothesis", {})
    assert submitted["result"]["event_type"] == UNKNOWN
    assert submitted["alert"]["send"] is False


def test_no_event_is_not_alerted(run):
    r = run(CLAIM | {"event_type": "no_event", "alternatives": []})
    r.through_reasoning()
    submitted = r.call("submit_hypothesis", {})
    assert submitted["result"]["event_type"] == "no_event"
    assert "not an abnormal event type" in submitted["alert"]["reason"]


def test_without_a_route_the_alert_is_skipped_and_the_brief_says_so(run):
    r = run(alert_route=None)
    assert "alert: none for this run" in r.policy.brief()
    r.through_reasoning()
    submitted = r.call("submit_hypothesis", {})
    assert submitted["ok"] and submitted["alert"]["send"] is False
    assert r.policy.alert_summary()["status"] == ALERT_SKIPPED
    assert not r.policy.authorize_alert({"action": "send", "channel": "telegram"}).allowed


def test_alerts_are_send_only_and_only_after_the_submit(run):
    r = run()
    early = r.policy.authorize_alert({"action": "send", "channel": "telegram"})
    assert not early.allowed and "before submit_hypothesis" in early.reason
    r.through_reasoning()
    r.call("submit_hypothesis", {})
    for params in (
        {"action": "delete", "channel": "telegram"},
        {"action": "send", "channel": "slack"},
        "send",
    ):
        assert not r.policy.authorize_alert(params).allowed
    assert r.policy.alert_summary()["status"] == "due"


def test_the_withheld_camera_is_refused_and_never_echoed(run):
    r = run()
    for name in ("sample_video", "inspect_camera", "get_supporting_frames"):
        args = {"camera_id": "cam_gt"}
        if name == "get_supporting_frames":
            args["frame_indices"] = [0]
        out = r.call(name, args)
        assert out["refused"] and "cam_01, cam_02, cam_03" in out["error"]
    out = r.call("sample_video", {"camera_id": "hidden_ground_truth.mp4"})
    assert out["refused"]
    assert not any(token in r.text() for token in GT_TOKENS)
    assert {e["camera_id"] for e in r.policy.summary()["trace"]} == {"not_visible"}
    brief = r.policy.brief()
    assert f"run: {RUN_ID}" in brief and "Telegram alert armed" in brief
    assert not any(token in brief for token in GT_TOKENS)


def test_a_strengthened_or_replaced_claim_is_refused_and_a_weaker_one_goes_through(run):
    r = run()
    r.through_reasoning()
    stronger = r.call("submit_hypothesis", {"hypothesis": CLAIM | {"confidence": 0.95}})
    assert stronger["refused"] and "may not exceed" in stronger["error"]
    other = r.call("submit_hypothesis", {"hypothesis": CLAIM | {"event_type": "vehicle_turn"}})
    assert other["refused"] and "event_type must stay" in other["error"]
    weaker = r.call("submit_hypothesis", {"hypothesis": CLAIM | {"confidence": 0.5}})
    assert weaker["ok"] and weaker["result"]["confidence"] == 0.5
    assert weaker["alert"]["send"] is True


def test_caps_and_budget_bound_the_run(run):
    r = run(budget=Budget(spare_calls=0, max_consecutive_failures=99))
    for _ in range(2):
        assert r.call("sample_video", {"camera_id": "cam_01"})["ok"]
    capped = r.call("sample_video", {"camera_id": "cam_01"})
    assert capped["refused"] and "limit of 2" in capped["error"]
    while r.policy.summary()["calls"] <= r.policy.total_calls:
        r.call("correlate_observations", {})
    out = r.call("triangulate_region", {})
    assert out["refused"] and "out of budget" in out["error"]
    assert r.policy.summary()["stop_reason"]


def test_finalize_abstains_for_an_agent_that_never_submitted(run):
    r = run()
    r.through_reasoning()
    final = r.policy.finalize()
    assert final.abstained and r.policy.finalized_by_policy and r.policy.wait_closed(0)
    assert final.alternatives[0].event_type == "vehicle_stop"
    assert [p["final"] for t, p in r.events if t == "hypothesis.updated"][-1] is True
    assert r.policy.alert_summary()["status"] == ALERT_NOT_DUE
    assert r.policy.finalize() == final


def test_a_waiting_runner_wakes_on_the_submit_not_on_the_alert(run):
    r = run()
    r.through_reasoning()
    woke = threading.Event()
    waiter = threading.Thread(target=lambda: r.policy.wait_closed(5) and woke.set())
    waiter.start()
    r.call("submit_hypothesis", {})
    waiter.join(5)
    assert woke.is_set()
    assert r.policy.alert_summary()["status"] == "due"  # the send has not even started


def test_a_broken_alert_listener_never_breaks_the_run(run):
    def boom(_):
        raise RuntimeError("listener down")

    r = run(alert_listener=boom)
    r.through_reasoning()
    assert r.call("submit_hypothesis", {})["ok"]
    assert r.policy.authorize_alert({"action": "send", "channel": "telegram"}).allowed
    assert r.policy.record_alert(False, "timeout")["status"] == ALERT_SKIPPED


def test_run_brief_lists_only_visible_cameras(scenario):
    brief = run_brief(scenario.model_view(), run_id=RUN_ID)
    assert "cam_01" in brief and "cam_03" in brief
    assert not any(token in brief for token in GT_TOKENS)
    with pytest.raises(ValueError):
        AgentPolicy(None, run_id="bad id/../x")  # type: ignore[arg-type]  # checked first

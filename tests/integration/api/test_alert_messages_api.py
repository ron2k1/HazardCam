"""Alert messages through the API: placement in fixture runs, delivery capability, real data.

The example scenario's shared fixtures ping on ``obs_a_001`` (cam_01, ``traffic_reaction``)
and end in a confident ``traffic_obstruction_or_collision`` (region demoted to unknown).
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT, AlertDelivery, AlertMessage, SseEnvelope, validate_json
from apps.api.settings import Settings

GT_ID = "cam_gt"
CAMERA_TOOLS = {"sample_video", "inspect_camera"}
PLAIN_LEAKS = re.compile(
    r"cam_\w+|obs_\w+|blind_zone_\w+|region_\d+|\d\.\d|°|https?://|hidden_ground_truth"
    r"|(?i:\b(hypothes[ie]s|evidence|cues?|triangulat\w*|cluster\w*|score|abstain\w*)\b)"
)


def _envelopes(messages):
    return [m["data"] for m in messages]


def _assert_plain(message: dict) -> None:
    for text in [
        message["headline"],
        message["text"],
        *(line["value"] for line in message["lines"]),
    ]:
        assert PLAIN_LEAKS.search(text) is None, text


async def test_fixture_run_publishes_one_ping_and_a_closing_alert(start_run, read_events):
    run = await start_run()
    _, messages = await read_events(run["run_id"])
    envelopes = _envelopes(messages)
    types = [e["type"] for e in envelopes]
    assert types.count("alert.message") == 2 and types.count("alert.delivery") == 2

    # The ping sits right after its observation, inside the inspect_camera tool pair.
    first_obs = types.index("camera.observation")
    assert types[first_obs + 1 : first_obs + 3] == ["alert.message", "alert.delivery"]
    open_tool = None
    for envelope in envelopes[: first_obs + 3]:
        if envelope["type"] == "tool.started":
            open_tool = envelope["payload"]["tool"]
        elif envelope["type"] == "tool.completed":
            open_tool = None
    assert open_tool == "inspect_camera"
    ping = envelopes[first_obs + 1]["payload"]["message"]
    assert (ping["id"], ping["kind"], ping["level"]) == ("msg_01", "ping", "warning")
    assert ping["evidence_ids"] == [envelopes[first_obs]["payload"]["observation"]["id"]]
    assert ping["camera_ids"] == ["cam_01"]
    assert ping["headline"] == "Heads-up from Camera 1: Vehicles braking or swerving"

    # The closing message and its delivery come right before run.complete.
    assert types[-3:] == ["alert.message", "alert.delivery", "run.complete"]
    final = envelopes[-3]["payload"]["message"]
    # traffic_obstruction_or_collision is not in config/alerts.yaml: the label is the humanized
    # type and the level is the default, exactly as for a new factory event type.
    assert (final["id"], final["kind"], final["level"]) == ("msg_02", "alert", "warning")
    # submit_hypothesis demotes blind_zone_02 (not a fusion candidate) to "unknown".
    assert envelopes[-1]["payload"]["hypothesis"]["region"] == "unknown"
    assert final["headline"] == "Traffic obstruction or collision"
    lines = {line["key"]: line["value"] for line in final["lines"]}
    assert lines["where"] == "Exact spot unclear"
    assert lines["what"] == (
        "Camera 1: Several visible vehicles brake abruptly. "
        "Not seen directly; pieced together from the other cameras."
    )
    assert lines["when"] == "0:08–0:10 into the clip"
    assert lines["how_sure"] == "Likely (74%)"
    assert lines["seen_on"] == "Camera 1, Camera 2 and Camera 3"
    assert final["evidence_ids"] == envelopes[-1]["payload"]["hypothesis"]["evidence_ids"]
    assert final["created_at"].endswith("Z")

    deliveries = [e["payload"] for e in envelopes if e["type"] == "alert.delivery"]
    assert [(d["message_id"], d["status"]) for d in deliveries] == [
        ("msg_01", "not_connected"),
        ("msg_02", "not_connected"),
    ]
    for envelope in envelopes:
        validate_json("sse_envelope", envelope)
        SseEnvelope.model_validate(envelope)
    for message in (ping, final):
        AlertMessage.model_validate(message)
        _assert_plain(message)
        assert GT_ID not in json.dumps(message)


async def test_a_telegram_capable_executor_reports_sent(app, start_run, read_events):
    base = app.state.executor
    delivered: list[dict] = []

    class TelegramHarness:
        delivers_alerts = True

        def __call__(self, *args):
            return base(*args)

        def deliver_alert(self, message: dict) -> dict:
            delivered.append(message)
            return {"status": "sent", "detail": None}

    app.state.executor = TelegramHarness()
    run = await start_run()
    _, messages = await read_events(run["run_id"])
    deliveries = [e["payload"] for e in _envelopes(messages) if e["type"] == "alert.delivery"]
    assert [(d["message_id"], d["status"]) for d in deliveries] == [
        ("msg_01", "sent"),
        ("msg_02", "sent"),
    ]
    assert [m["kind"] for m in delivered] == ["ping", "alert"]
    for delivery in deliveries:
        AlertDelivery.model_validate(delivery)


async def test_an_abstaining_run_closes_calmly_without_delivery(app, start_run, read_events):
    def abstaining_executor(scenario, profile_name, emit, run_dir, pace_s):
        return {"event_type": "unknown", "region": "unknown", "confidence": 0.1, "reason": "x"}

    app.state.executor = abstaining_executor
    run = await start_run()
    _, messages = await read_events(run["run_id"])
    types = [e["type"] for e in _envelopes(messages)]
    assert types == ["alert.message", "run.complete"]
    message = messages[0]["data"]["payload"]["message"]
    assert (message["id"], message["kind"], message["level"]) == ("msg_01", "unconfirmed", "info")
    _assert_plain(message)


async def test_the_public_scenario_carries_display_names(client):
    body = (await client.get("/api/scenarios/scenario_001")).json()
    assert [c["display_name"] for c in body["cameras"]] == ["Camera 1", "Camera 2", "Camera 3"]
    assert body["start_wallclock"] is None
    assert GT_ID not in json.dumps(body)


EVAL_019 = REPO_ROOT / "data" / "prepared" / "eval_019"


@pytest.mark.media
@pytest.mark.skipif(
    not all((EVAL_019 / f"{cam}.mp4").is_file() for cam in ("cam_a", "cam_b", "cam_c"))
    or not (REPO_ROOT / "data" / "fixtures" / "eval_019" / "final_hypothesis.json").is_file(),
    reason="prepared MEVA eval_019 media or fixtures are not on this machine",
)
async def test_the_operators_leaky_run_reads_plainly(tmp_path):
    """The real eval_019 run that prompted this work, end to end in fixture mode."""
    settings = Settings(
        manifests_dir=REPO_ROOT / "data" / "manifests",
        prepared_dir=REPO_ROOT / "data" / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=REPO_ROOT,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        scenario = (await client.get("/api/scenarios/eval_019")).json()
        assert [c["display_name"] for c in scenario["cameras"]] == [
            "Camera A",
            "Camera B",
            "Camera C",
        ]
        assert scenario["start_wallclock"] == "2018-03-15T15:41:02"
        response = await client.post(
            "/api/runs", json={"scenario_id": "eval_019", "profile": "fixture", "pace_s": 0}
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        events = await asyncio.wait_for(client.get(f"/api/runs/{run_id}/events"), timeout=120)

    envelopes = [m["data"] for m in _parse(events.text)]
    assert envelopes[-1]["type"] == "run.complete", envelopes[-1]
    alerts = [e["payload"]["message"] for e in envelopes if e["type"] == "alert.message"]
    assert [m["kind"] for m in alerts] == ["ping", "alert"]
    ping, final = alerts
    assert ping["headline"] == "Heads-up from Camera B: Vehicle reversing or maneuvering"
    assert final["headline"] == "Vehicle turning around in the blind spot north-east of Camera C"
    lines = {line["key"]: line["value"] for line in final["lines"]}
    assert lines["where"] == "In the blind spot about 30 m north-east of Camera C"
    assert re.fullmatch(r"15:41:\d\d–15:41:\d\d on 15 Mar 2018", lines["when"])
    assert lines["how_sure"] == "Likely (77%)"
    assert lines["seen_on"] == "Camera A, Camera B and Camera C"
    for message in alerts:
        _assert_plain(message)
    # The technical view keeps the raw reasoning; only the messages are rewritten.
    assert envelopes[-1]["payload"]["hypothesis"]["reason"].startswith("Cues cam_b.o1")


def _parse(text: str) -> list[dict]:
    from .conftest import parse_sse

    return parse_sse(text)

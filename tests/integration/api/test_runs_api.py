"""P03: run lifecycle, SSE replay/resume/live streaming, failures, and the GT invariant."""

from __future__ import annotations

import asyncio
import json
import threading

from apps.api.schemas import (
    EVENT_TYPES,
    REPO_ROOT,
    GroundTruthAccessError,
    Hypothesis,
    SseEnvelope,
    validate_json,
)

# Ground-truth camera of contracts/examples/scenario_001.json.
GT_ID = "cam_gt"
GT_BASENAME = "hidden_ground_truth.mp4"
GT_FILE = "data/prepared/scenario_001/" + GT_BASENAME
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
FIXTURE_HYPOTHESIS = json.loads((FIXTURES_DIR / "final_hypothesis.json").read_text("utf-8"))
CAMERA_TOOLS = {"sample_video", "inspect_camera"}


async def _finished_run(start_run, read_events, **body):
    run = await start_run(**body)
    response, messages = await read_events(run["run_id"])
    assert response.status_code == 200
    return run, messages


async def test_post_run_returns_run_id(client, start_run, read_events):
    response = await client.post("/api/runs", json={"scenario_id": "scenario_001"})
    assert response.status_code == 202
    body = response.json()
    assert body["run_id"].startswith("run_")
    assert body["scenario_id"] == "scenario_001"
    assert body["profile"] == "fixture"
    assert body["state"] in {"queued", "running", "complete"}
    assert body["events_url"] == f"/api/runs/{body['run_id']}/events"
    assert response.headers["location"] == f"/api/runs/{body['run_id']}"
    validate_json("run", body)
    await read_events(body["run_id"])  # drain so the run finishes inside the test


async def test_fixture_run_streams_contiguous_catalog(client, start_run, read_events, settings):
    run, messages = await _finished_run(start_run, read_events)
    seqs = [m["data"]["seq"] for m in messages]
    assert seqs == list(range(1, len(messages) + 1))
    assert [m["id"] for m in messages] == [str(s) for s in seqs]
    assert all(m["event"] is None and m["fields"] == {"id", "data"} for m in messages)
    for m in messages:
        validate_json("sse_envelope", m["data"])
        envelope = SseEnvelope.model_validate(m["data"])
        assert envelope.run_id == run["run_id"]
        assert m["data"]["ts"].endswith("Z")

    types = [m["data"]["type"] for m in messages]
    assert types[0] == "run.started" and types[-1] == "run.complete"
    assert set(types) == set(EVENT_TYPES) - {"run.failed"}
    started = messages[0]["data"]["payload"]
    assert started["camera_ids"] == ["cam_01", "cam_02", "cam_03"]
    assert started["harness"] == "dev-sequence"

    complete = messages[-1]["data"]["payload"]
    finals = [m["data"]["payload"] for m in messages if m["data"]["type"] == "hypothesis.updated"]
    assert [f["final"] for f in finals] == [False, True]
    assert complete["hypothesis"] == finals[-1]["hypothesis"]
    assert isinstance(complete["duration_ms"], int)

    # The harness's frame URLs are the API's frame route: fetch one back.
    sampled = next(m for m in messages if m["data"]["type"] == "camera.frames.sampled")
    url = sampled["data"]["payload"]["frames"][0]["url"]
    frame = await client.get(url)
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"

    record = (await client.get(f"/api/runs/{run['run_id']}")).json()
    validate_json("run", record)
    assert record["state"] == "complete"
    assert record["last_seq"] == len(messages)
    assert record["finished_at"] is not None
    assert (
        Hypothesis.model_validate(record["hypothesis"]).event_type
        == complete["hypothesis"]["event_type"]
    )

    run_dir = settings.runs_dir / run["run_id"]
    persisted = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert persisted == [m["data"] for m in messages]
    assert json.loads((run_dir / "run.json").read_text())["state"] == "complete"


async def test_camera_events_sit_inside_camera_tool_pairs(start_run, read_events):
    _, messages = await _finished_run(start_run, read_events)
    open_tool = None
    for envelope in (m["data"] for m in messages):
        if envelope["type"] == "tool.started":
            open_tool = envelope["payload"]["tool"]
        elif envelope["type"] == "tool.completed":
            assert envelope["payload"]["tool"] == open_tool and envelope["payload"]["ok"]
            open_tool = None
        elif envelope["type"].startswith("camera."):
            assert open_tool in CAMERA_TOOLS, envelope["type"]


async def test_replay_after_finish_is_identical(start_run, read_events):
    run, first = await _finished_run(start_run, read_events)
    _, replay = await read_events(run["run_id"])
    assert [m["data"] for m in replay] == [m["data"] for m in first]


async def test_resume_with_after_seq_and_last_event_id(start_run, read_events):
    run, full = await _finished_run(start_run, read_events)
    n = len(full)
    run_id = run["run_id"]

    _, after = await read_events(run_id, params={"after_seq": 5})
    assert [m["data"]["seq"] for m in after] == list(range(6, n + 1))

    _, resumed = await read_events(run_id, headers={"Last-Event-ID": "7"})
    assert [m["data"]["seq"] for m in resumed] == list(range(8, n + 1))

    _, both = await read_events(run_id, params={"after_seq": 3}, headers={"Last-Event-ID": "9"})
    assert [m["data"]["seq"] for m in both] == list(range(10, n + 1))

    response, past_end = await read_events(run_id, params={"after_seq": n})
    assert response.status_code == 200 and past_end == []

    _, garbage_header = await read_events(run_id, headers={"Last-Event-ID": "not-a-seq"})
    assert len(garbage_header) == n


async def test_live_subscriber_gets_events_emitted_after_it_connects(
    app, client, start_run, read_events
):
    gate = threading.Event()

    def gated_executor(scenario, profile_name, emit, run_dir, pace_s):
        view = scenario.model_view()
        emit(
            "run.started",
            {
                "scenario_id": view.id,
                "profile": profile_name,
                "camera_ids": [c.id for c in view.cameras],
                "harness": "test",
            },
        )
        assert gate.wait(timeout=10), "test never released the gate"
        for cam in view.cameras:
            emit("camera.started", {"camera_id": cam.id})
        return Hypothesis.model_validate(FIXTURE_HYPOTHESIS)

    app.state.executor = gated_executor
    run = await start_run()
    stream = asyncio.create_task(read_events(run["run_id"]))
    await asyncio.sleep(0.2)
    assert (await client.get(f"/api/runs/{run['run_id']}")).json()["state"] == "running"
    assert not stream.done()
    gate.set()
    _, messages = await stream
    types = [m["data"]["type"] for m in messages]
    assert types == ["run.started", *["camera.started"] * 3, "run.complete"]
    assert [m["data"]["seq"] for m in messages] == [1, 2, 3, 4, 5]


async def test_keepalive_pings_while_idle(app, start_run, read_events):
    app.state.settings.sse_ping_s = 0.05
    gate = threading.Event()

    def slow_executor(scenario, profile_name, emit, run_dir, pace_s):
        gate.wait(timeout=10)
        return FIXTURE_HYPOTHESIS

    app.state.executor = slow_executor
    run = await start_run()
    stream = asyncio.create_task(read_events(run["run_id"]))
    await asyncio.sleep(0.3)
    gate.set()
    response, messages = await stream
    assert ": ping" in response.text
    assert [m["data"]["type"] for m in messages] == ["run.complete"]


async def test_failing_executor_emits_run_failed(app, client, start_run, read_events):
    def failing_executor(scenario, profile_name, emit, run_dir, pace_s):
        emit("tool.started", {"call_id": "c1", "tool": "inspect_camera", "args_summary": "x"})
        raise GroundTruthAccessError(f"camera {GT_ID!r} is the withheld ground-truth camera")

    app.state.executor = failing_executor
    run, messages = await _finished_run(start_run, read_events)
    last = messages[-1]["data"]
    assert last["type"] == "run.failed"
    assert last["payload"]["stage"] == "inspect_camera"
    assert last["payload"]["error"].startswith("GroundTruthAccessError: ")
    assert "Traceback" not in last["payload"]["error"]
    assert GT_ID not in json.dumps(last)

    record = (await client.get(f"/api/runs/{run['run_id']}")).json()
    assert record["state"] == "failed"
    assert record["hypothesis"] is None
    assert record["error"] == last["payload"]["error"]
    assert record["last_seq"] == last["seq"]


async def test_exception_stage_attribute_wins(app, start_run, read_events):
    class StageError(RuntimeError):
        stage = "reason_hypothesis"

    def executor(scenario, profile_name, emit, run_dir, pace_s):
        raise StageError("model endpoint timed out")

    app.state.executor = executor
    _, messages = await _finished_run(start_run, read_events)
    assert messages[-1]["data"]["payload"] == {
        "stage": "reason_hypothesis",
        "error": "StageError: model endpoint timed out",
    }


async def test_executor_cannot_publish_terminal_or_gt_events(app, start_run, read_events):
    attempts = {}

    def sneaky_executor(scenario, profile_name, emit, run_dir, pace_s):
        for name, args in {
            "terminal": ("run.complete", {}),
            "unknown": ("camera.exploded", {}),
            "gt_id": ("camera.started", {"camera_id": GT_ID}),
            "gt_path": ("camera.frames.sampled", {"camera_id": "cam_01", "src": GT_FILE}),
        }.items():
            try:
                emit(*args)
            except Exception as exc:  # noqa: BLE001 - recording which guard fired
                attempts[name] = type(exc).__name__
        emit("camera.started", {"camera_id": "cam_01"})
        return FIXTURE_HYPOTHESIS

    app.state.executor = sneaky_executor
    _, messages = await _finished_run(start_run, read_events)
    assert attempts == {
        "terminal": "ValueError",
        "unknown": "ValueError",
        "gt_id": "GroundTruthAccessError",
        "gt_path": "GroundTruthAccessError",
    }
    assert [m["data"]["type"] for m in messages] == ["camera.started", "run.complete"]
    assert [m["data"]["seq"] for m in messages] == [1, 2]


async def test_hypothesis_citing_gt_camera_fails_the_run(app, start_run, read_events):
    def executor(scenario, profile_name, emit, run_dir, pace_s):
        return FIXTURE_HYPOTHESIS | {"reason": f"seen directly on {GT_ID}"}

    app.state.executor = executor
    _, messages = await _finished_run(start_run, read_events)
    assert [m["data"]["type"] for m in messages] == ["run.failed"]
    assert GT_ID not in json.dumps(messages[-1]["data"])


async def test_ground_truth_absent_from_all_public_json(
    client, start_run, read_events, settings, scenario_doc
):
    scenario_doc["title"] = f"Intersection (judge camera {GT_ID} withheld)"
    scenario_doc["provenance"] = {
        "source": "TEST fixture",
        "license": "CC-BY-4.0",
        "note": f"{GT_ID} was recorded as {GT_FILE}",
        "original_files": {GT_ID: GT_BASENAME},
    }
    manifest = settings.manifests_dir / "scenario_001.json"
    manifest.write_text(json.dumps(scenario_doc), encoding="utf-8")

    listing = await client.get("/api/scenarios")
    detail = await client.get("/api/scenarios/scenario_001")
    created = await client.post("/api/runs", json={"scenario_id": "scenario_001"})
    run_id = created.json()["run_id"]
    events, _ = await read_events(run_id)
    record = await client.get(f"/api/runs/{run_id}")
    run_dir = settings.runs_dir / run_id
    bodies = {
        "list": listing.text,
        "detail": detail.text,
        "create": created.text,
        "sse": events.text,
        "record": record.text,
        "events.jsonl": (run_dir / "events.jsonl").read_text(),
        "run.json": (run_dir / "run.json").read_text(),
    }
    for name, text in bodies.items():
        for token in (GT_ID, GT_BASENAME, "hidden_ground_truth"):
            assert token not in text, f"{token!r} leaked in {name}"

    public = detail.json()
    assert public["has_ground_truth"] is True
    assert [c["id"] for c in public["cameras"]] == ["cam_01", "cam_02", "cam_03"]
    assert all("file" not in c for c in public["cameras"])
    assert public["provenance"]["source"] == "TEST fixture"
    assert "original_files" not in public["provenance"]
    assert "[withheld]" in public["title"]


async def test_request_validation(client):
    assert (await client.post("/api/runs", json={"scenario_id": "nope"})).status_code == 404
    bad_profile = {"scenario_id": "scenario_001", "profile": "../../etc/passwd"}
    assert (await client.post("/api/runs", json=bad_profile)).status_code == 422
    unknown_profile = {"scenario_id": "scenario_001", "profile": "no-such-profile"}
    assert (await client.post("/api/runs", json=unknown_profile)).status_code == 422
    too_slow = {"scenario_id": "scenario_001", "pace_s": 99}
    assert (await client.post("/api/runs", json=too_slow)).status_code == 422
    assert (await client.post("/api/runs", json={})).status_code == 422
    assert (await client.get("/api/runs/run_missing")).status_code == 404
    assert (await client.get("/api/runs/run_missing/events")).status_code == 404
    assert (await client.get("/api/scenarios/nope")).status_code == 404


async def test_explicit_profile_and_pace_are_recorded(start_run, read_events):
    run = await start_run(profile="fixture", pace_s=0.01)
    _, messages = await read_events(run["run_id"])
    assert run["profile"] == "fixture"
    assert messages[0]["data"]["payload"]["profile"] == "fixture"
    assert messages[-1]["data"]["type"] == "run.complete"

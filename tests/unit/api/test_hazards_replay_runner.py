"""Safety hazard API, second part: demo replay, the review runner seam, job lookups,
zones/pictures/signs and the clean evidence copies.

Reports under test are REAL runs, verbatim: the original run (contracts/examples/hazards/
source/) and an OpenClaw agent run on the GB10 (source/agent_run/). Video bytes are
placeholders; evidence pictures are synthetic JPEGs where pixels matter.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT
from apps.api.services import hazards as hz
from apps.api.services.hazards import HazardService
from apps.api.settings import Settings

EXAMPLES = REPO_ROOT / "contracts" / "examples" / "hazards"
SOURCE = EXAMPLES / "source"
AGENT_SOURCE = SOURCE / "agent_run"
SCHEMA = json.loads((REPO_ROOT / "contracts" / "hazard_view.schema.json").read_text("utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
WORDING = hz.load_wording()
ORIGINAL_RUN = "ed487eb3f1181f38"
AGENT_RUN = "ed02d540b08f6395"
AGENT_FILES = ("agent_trace.json", "agent_summary.json", "job_timeline.json")
SOURCE_BYTES = bytes(range(256)) * 16
EVIDENCE_MIN_CANVAS_W = 520  # hazards.scan pads narrow evidence pictures to this width


def validate(def_name: str, doc: Any) -> None:
    ref = {"$ref": f"{SCHEMA['$id']}#/$defs/{def_name}"}
    Draft202012Validator(ref, registry=REGISTRY).validate(doc)


def load(folder: Path, name: str) -> Any:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def write_clip(root: Path, clip_id: str, **extra: Any) -> None:
    doc = {"clip_id": clip_id, "title": f"Camera {clip_id}", "duration_s": 14.982, **extra}
    write_json(root / "clips" / clip_id / "clip.json", doc)
    (root / "clips" / clip_id / "source.mp4").write_bytes(SOURCE_BYTES)


def write_run(
    root: Path,
    clip_id: str,
    run_id: str,
    report: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    *,
    point: bool = True,
    extra_files: dict[str, Any] | None = None,
) -> Path:
    run_dir = root / "reports" / clip_id / run_id
    write_json(run_dir / "hazard_report.json", report)
    write_json(run_dir / "run_manifest.json", manifest or load(SOURCE, "run_manifest.json"))
    (run_dir / "processed.mp4").write_bytes(SOURCE_BYTES[:1024])
    for item in report.get("evidence", []):
        path = run_dir / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff\xe0" + item["evidence_id"].encode() + b"\xff\xd9")
    for name, doc in (extra_files or {}).items():
        write_json(run_dir / name, doc)
    if point:
        write_json(
            root / "reports" / clip_id / "latest_run.json",
            {"run_id": run_id, "status": report.get("status")},
        )
    return run_dir


def agent_report() -> dict[str, Any]:
    return load(AGENT_SOURCE, "hazard_report.json")


def write_agent_run(root: Path, clip_id: str = "hz_02", **kwargs: Any) -> Path:
    files = {name: load(AGENT_SOURCE, name) for name in AGENT_FILES}
    return write_run(
        root,
        clip_id,
        AGENT_RUN,
        agent_report(),
        load(AGENT_SOURCE, "run_manifest.json"),
        extra_files=files,
        **kwargs,
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """hz_00: the original run (not a GB10 run). hz_01: never reviewed. hz_02: the agent
    run, with its trace, summary and job timeline."""
    data = tmp_path / "hazards"
    write_clip(data, "hz_00")
    write_clip(data, "hz_01")
    write_clip(data, "hz_02")
    write_run(data, "hz_00", ORIGINAL_RUN, load(SOURCE, "hazard_report.json"))
    write_agent_run(data)
    write_json(data / "labels" / "hz_02.json", {"dataset_label": "0_safe_walkway_violation"})
    return data


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        manifests_dir=tmp_path / "manifests",
        prepared_dir=tmp_path / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=tmp_path,
    )


class VirtualTime:
    """``sleep`` and ``clock`` stand-ins: sleeping advances the clock, nothing waits."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.calls: list[float] = []
        self._lock = threading.Lock()

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.calls.append(seconds)
            self.now += seconds

    def clock(self) -> float:
        with self._lock:
            return self.now

    @property
    def total(self) -> float:
        return sum(self.calls)


def no_model(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("a replay must not run the pipeline or call a model")


def wait_finished(job: hz.HazardJob, timeout: float = 10.0) -> list[tuple[str, dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events, finished = job.events()
        if finished:
            return events
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


def make_app(settings: Settings, service: HazardService, **state: Any) -> Any:
    app = create_app(settings)
    app.state.hazards = service
    for key, value in state.items():
        setattr(app.state, key, value)
    return app


async def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def parse_sse(text: str) -> list[dict[str, Any]]:
    messages = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        data: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data.append(value)
            else:
                fields[key] = value
        if data:
            messages.append(
                {
                    "id": fields.get("id"),
                    "event": fields.get("event"),
                    "data": json.loads("\n".join(data)),
                }
            )
    return messages


async def read_events(client: httpx.AsyncClient, url: str, **kwargs: Any) -> list[dict[str, Any]]:
    response = await asyncio.wait_for(client.get(url, **kwargs), timeout=10)
    assert response.status_code == 200
    return parse_sse(response.text)


# --------------------------------------------------------------------------- demo replay


def test_demo_replay_paces_the_agent_run_between_25_and_40_s(root: Path) -> None:
    sleeps = VirtualTime()
    service = HazardService(
        root,
        profile="gb10",
        fixture=False,
        demo_replay=True,
        review_fn=no_model,
        sleep=sleeps.sleep,
        clock=sleeps.clock,
    )
    assert service.replays_by_default
    job = service.start_review("hz_02")
    assert job.mode == "replay" and job.runner == "openclaw-agent"
    events = wait_finished(job)
    # The replay waits for the recorded moments, scaled to a believable demo length.
    assert 10.0 - 1e-6 <= sleeps.total <= 14.0 + 1e-6  # config demo_replay.total_seconds 12
    expected = load(EXAMPLES, "job_events_agent.json")
    assert [e for e, _ in events] == [e["event"] for e in expected]
    for (event, data), want in zip(events[:-1], expected[:-1], strict=True):
        if event == "agent":
            assert data["text"] == want["data"]["text"] and data["kind"] == "say"
            validate("AgentEvent", data)
        else:
            assert data["step"] == want["data"]["step"]
            validate("ProgressEvent", data)
    done = events[-1][1]
    validate("DoneEvent", done)
    assert done == {
        "clip_id": "hz_02",
        "run_id": AGENT_RUN,
        "reviewed_at": "2026-10-03T18:55:08.841694+00:00",
        "runner": "openclaw-agent",
        "replay": True,
        "note": "Replay of the GB10 run from 2026-10-03 18:55 UTC",
    }


def test_each_clip_replays_its_own_run(root: Path) -> None:
    service = HazardService(root, profile="fixture", replay_pace_s=0.0, review_fn=no_model)
    original = wait_finished(service.start_review("hz_00"))[-1][1]
    agent = wait_finished(service.start_review("hz_02"))[-1][1]
    assert (original["run_id"], original["runner"]) == (ORIGINAL_RUN, "direct")
    assert original["note"] == "Replay of the stored run from 2026-10-03 16:55 UTC"
    assert (agent["run_id"], agent["runner"]) == (AGENT_RUN, "openclaw-agent")


async def test_replay_view_carries_the_replay_note(root: Path, settings: Settings) -> None:
    service = HazardService(root, profile="gb10", fixture=False, demo_replay=True)
    async with await client_for(make_app(settings, service)) as client:
        view = (await client.get("/api/hazards/clips/hz_02")).json()
    validate("HazardView", view)
    technical = view["technical"]
    assert technical["replay"] == {
        "note": "Replay of the GB10 run from 2026-10-03 18:55 UTC",
        "reviewed_at": "2026-10-03T18:55:08.841694+00:00",
        "run_id": AGENT_RUN,
    }
    assert technical["runner"] == "openclaw-agent"
    assert technical["agent"]["summary"] == load(AGENT_SOURCE, "agent_summary.json")
    assert technical["dataset_label"] == "0_safe_walkway_violation"
    assert view["worker"]["agent_summary"]["first_action"]
    live = HazardService(root, profile="gb10", fixture=False, demo_replay=False)
    assert live.view("hz_02")["technical"]["replay"] is None


async def test_mode_live_forces_a_real_run_during_demo_replay(
    root: Path, settings: Settings
) -> None:
    calls: list[str] = []

    def review_clip(video: Path, output_root: Path, *, source_name: str, progress: Any, **_: Any):
        calls.append(source_name)
        for step in range(1, 7):
            progress(step, 6, hz.SCRIPT_STEPS[step - 1])
        return write_run(root, source_name, "run_live", load(SOURCE, "hazard_report.json"))

    service = HazardService(
        root, profile="gb10", fixture=False, demo_replay=True, review_fn=review_clip
    )
    async with await client_for(make_app(settings, service)) as client:
        accepted = await client.post("/api/hazards/clips/hz_00/review", json={"mode": "live"})
        assert accepted.status_code == 202
        body = accepted.json()
        validate("ReviewAccepted", body)
        assert body["mode"] == "live" and body["runner"] == "direct"
        messages = await read_events(client, body["events_url"])
        assert messages[-1]["event"] == "done"
        assert messages[-1]["data"]["replay"] is False
        assert messages[-1]["data"]["run_id"] == "run_live"
        bad = await client.post("/api/hazards/clips/hz_00/review", json={"mode": "fast"})
        assert bad.status_code == 422
    assert calls == ["hz_00"]


def test_replay_without_a_stored_run_runs_live_outside_fixture(root: Path) -> None:
    calls: list[str] = []

    def review_clip(video: Path, output_root: Path, *, source_name: str, progress: Any, **_: Any):
        calls.append(source_name)
        progress(1, 6, hz.SCRIPT_STEPS[0])
        return write_run(root, source_name, "run_new", agent_report())

    service = HazardService(
        root, profile="gb10", fixture=False, demo_replay=True, review_fn=review_clip
    )
    job = service.start_review("hz_01")
    events = wait_finished(job)
    assert calls == ["hz_01"]
    assert job.mode == "live" and job.runner == "direct"
    assert events[-1][0] == "done" and events[-1][1]["replay"] is False


def test_demo_replay_env_and_fixture_default(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert hz.demo_replay_from_env({"HAZARDS_DEMO_REPLAY": "1"})
    assert hz.demo_replay_from_env({"HAZARDS_DEMO_REPLAY": " True "})
    assert not hz.demo_replay_from_env({"HAZARDS_DEMO_REPLAY": "0"})
    assert not hz.demo_replay_from_env({})
    monkeypatch.setenv("HAZARDS_DEMO_REPLAY", "yes")
    assert HazardService(root, profile="gb10", fixture=False).replays_by_default
    monkeypatch.delenv("HAZARDS_DEMO_REPLAY")
    assert not HazardService(root, profile="gb10", fixture=False).replays_by_default
    assert HazardService(root, profile="fixture").replays_by_default


def test_replay_schedule_clamps_and_keeps_order() -> None:
    pacing = {
        **WORDING["demo_replay"],
        "total_seconds": 0,
        "min_total_s": 25.0,
        "max_total_s": 40.0,
    }
    events = [hz.ReplayEvent(t, "progress", {"step": i + 1}) for i, t in enumerate([0, 1, 2])]
    short, end = hz.replay_schedule(events, 3.0, pacing)
    assert end == pytest.approx(25.0)  # a 3 s run is stretched to the 25 s minimum
    long, end = hz.replay_schedule(
        [hz.ReplayEvent(t, "progress", {}) for t in (0, 100, 400)], 400.0, pacing
    )
    assert end == pytest.approx(40.0)
    assert long[-1].t_s == pytest.approx(40.0 - pacing["tail_s"])
    crowded, _ = hz.replay_schedule(
        [hz.ReplayEvent(10.0, "progress", {}), hz.ReplayEvent(10.0, "agent", {})], 100.0, pacing
    )
    assert crowded[1].t_s - crowded[0].t_s == pytest.approx(pacing["min_line_s"])
    fixed, end = hz.replay_schedule(events, 3.0, pacing, pace_s=0.5)
    assert [e.t_s for e in fixed] == [0.0, 0.5, 1.0] and end == 1.5
    assert [e.data for e in short] == [e.data for e in events]


def test_recorded_events_without_a_timeline_use_timings_and_the_trace() -> None:
    manifest = load(AGENT_SOURCE, "run_manifest.json")
    trace = load(AGENT_SOURCE, "agent_trace.json")
    events, total = hz.recorded_events(steps=list(hz.SCRIPT_STEPS), manifest=manifest, trace=trace)
    progress = [e for e in events if e.event == "progress"]
    says = [e for e in events if e.event == "agent"]
    assert [e.data["step"] for e in progress] == [1, 2, 3, 4, 5, 6]
    assert [e.data["text"] for e in says] == [t["text"] for t in trace if t["kind"] == "say"]
    assert [e.t_s for e in events] == sorted(e.t_s for e in events)
    # The scan steps start when the agent's scan call started (its line minus the scan time).
    scan_line = next(t for t in trace if t.get("tool") == "hazard_scan_clip")
    scan_s = manifest["timings_s"]["scan"]
    assert progress[0].t_s == pytest.approx(scan_line["t_s"] - scan_s, abs=0.01)
    assert total >= events[-1].t_s
    timeline = load(AGENT_SOURCE, "job_timeline.json")
    recorded, recorded_total = hz.recorded_events(
        steps=list(hz.SCRIPT_STEPS), manifest=manifest, trace=trace, timeline=timeline
    )
    assert recorded_total == timeline["total_s"]
    assert [e.event for e in recorded] == [e["event"] for e in timeline["events"]]


# --------------------------------------------------------------------------- runner seam


class FakeAgentRunner:
    """Stands in for ``AgentHazardRunner``: narrates on step 0, reports the numbered steps,
    writes a finished run with an agent trace and summary, returns the run directory."""

    name = "openclaw-agent"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        video: Path,
        output_root: Path,
        *,
        source_name: str,
        refresh: bool,
        progress: Callable[[int, int, str], None],
    ) -> Path:
        self.calls.append(
            {
                "video": video,
                "output_root": output_root,
                "source_name": source_name,
                "refresh": refresh,
            }
        )
        progress(0, 6, "The safety agent picked up this clip and is planning its check")
        for step in range(1, 5):
            progress(step, 6, hz.SCRIPT_STEPS[step - 1])
        progress(0, 6, "The safety agent asked the local AI (Qwen at 127.0.0.1:8000) to check Z03")
        for step in (5, 6):
            progress(step, 6, hz.SCRIPT_STEPS[step - 1])
        trace = [
            {"t_s": 0.0, "kind": "say", "text": "The safety agent picked up this clip"},
            {"t_s": 1.0, "kind": "tool", "tool": "hazard_scan_clip", "text": "scan ok"},
        ]
        return write_run(
            self.root,
            source_name,
            "run_agent",
            agent_report(),
            load(AGENT_SOURCE, "run_manifest.json"),
            extra_files={
                "agent_trace.json": trace,
                "agent_summary.json": load(AGENT_SOURCE, "agent_summary.json"),
            },
        )


async def test_live_review_goes_through_the_runner_seam(root: Path, settings: Settings) -> None:
    runner = FakeAgentRunner(root)
    service = HazardService(root, profile="gb10", fixture=False, review_fn=no_model)
    app = make_app(
        settings,
        service,
        hazard_review_runner=runner,
        hazard_review_runner_name="openclaw-agent",
    )
    async with await client_for(app) as client:
        accepted = (await client.post("/api/hazards/clips/hz_01/review")).json()
        assert accepted["mode"] == "live" and accepted["runner"] == "openclaw-agent"
        messages = await read_events(client, accepted["events_url"])
        names = [m["event"] for m in messages]
        assert names == ["agent"] + ["progress"] * 4 + ["agent"] + ["progress"] * 2 + ["done"]
        says = [m["data"] for m in messages if m["event"] == "agent"]
        for data in says:
            validate("AgentEvent", data)
            assert data["kind"] == "say"
        # Narration reaches the stream in plain words: no zone ids, hosts or model names.
        assert says[1]["text"].startswith("The safety agent asked the local AI")
        assert "127.0.0.1" not in says[1]["text"] and "Z03" not in says[1]["text"]
        assert "Qwen" not in says[1]["text"]
        done = messages[-1]["data"]
        assert done["runner"] == "openclaw-agent" and done["replay"] is False
        assert done["run_id"] == "run_agent"

        # Neutral clip id as source_name: labels and file names never reach the agent.
        assert runner.calls == [
            {
                "video": (root / "clips" / "hz_01" / "source.mp4").resolve(),
                "output_root": root / "reports" / "hz_01",
                "source_name": "hz_01",
                "refresh": False,
            }
        ]
        run_dir = root / "reports" / "hz_01" / "run_agent"
        timeline = json.loads((run_dir / "job_timeline.json").read_text())
        assert timeline["runner"] == "openclaw-agent" and timeline["mode"] == "live"
        assert timeline["job_id"] == accepted["job_id"]
        assert [e["event"] for e in timeline["events"]] == names[:-1]
        assert timeline["total_s"] >= 0

        view = (await client.get("/api/hazards/clips/hz_01")).json()
        validate("HazardView", view)
        assert view["technical"]["runner"] == "openclaw-agent"
        assert view["technical"]["agent"]["agent_id"] == "urban-mirror"
        assert [t["kind"] for t in view["technical"]["agent"]["trace"]] == ["say", "tool"]
        assert view["worker"]["agent_summary"]["headline"]

        # A replay of that run follows its recorded timeline, narration included
        # (no pacing here: the pace is read when the replay job starts).
        service.replay_pace_s = 0.0
        replay = (
            await client.post("/api/hazards/clips/hz_01/review", json={"mode": "replay"})
        ).json()
        assert replay["mode"] == "replay" and replay["runner"] == "openclaw-agent"
    replayed = wait_finished(service.job(replay["job_id"]))
    assert [e for e, _ in replayed] == names
    assert replayed[-1][1]["replay"] is True
    assert len(runner.calls) == 1


async def test_direct_runner_is_used_without_an_agent(root: Path, settings: Settings) -> None:
    service = HazardService(root, profile="gb10", fixture=False)
    calls: list[str] = []

    def review_clip(video: Path, output_root: Path, *, source_name: str, progress: Any, **kw: Any):
        calls.append(kw["profile"])
        progress(1, 6, hz.SCRIPT_STEPS[0])
        return write_run(root, source_name, "run_direct", agent_report())

    service._review_fn = review_clip
    async with await client_for(make_app(settings, service)) as client:
        accepted = (await client.post("/api/hazards/clips/hz_01/review")).json()
        assert accepted["runner"] == "direct"
        messages = await read_events(client, accepted["events_url"])
    assert messages[-1]["data"]["runner"] == "direct"
    assert calls == ["gb10"]


# --------------------------------------------------------------------------- job lookups


async def test_latest_job_and_late_subscriber(root: Path, settings: Settings) -> None:
    service = HazardService(root, profile="fixture", replay_pace_s=0.0)
    async with await client_for(make_app(settings, service)) as client:
        assert (await client.get("/api/hazards/clips/hz_00/jobs/latest")).status_code == 404
        assert (await client.get("/api/hazards/clips/hz_99/jobs/latest")).status_code == 404
        accepted = (await client.post("/api/hazards/clips/hz_00/review")).json()
        wait_finished(service.job(accepted["job_id"]))
        latest = (await client.get("/api/hazards/clips/hz_00/jobs/latest")).json()
        validate("JobSummary", latest)
        assert latest["job_id"] == accepted["job_id"]
        assert latest["state"] == "done" and latest["mode"] == "replay"
        assert latest["events_url"] == accepted["events_url"]
        # A subscriber that arrives after the job finished still gets every event.
        late = await read_events(client, latest["events_url"])
        assert [m["id"] for m in late] == [str(i) for i in range(1, 8)]
        assert late[-1]["event"] == "done"


def test_finished_jobs_are_evicted_but_each_clips_latest_is_kept(root: Path) -> None:
    service = HazardService(root, profile="fixture", replay_pace_s=0.0, max_jobs=2)
    first = service.start_review("hz_02")
    wait_finished(first)
    for _ in range(3):
        wait_finished(service.start_review("hz_00"))
    assert service.latest_job("hz_02") is first
    assert service.job(first.job_id) is first
    assert len(service._jobs) <= 3


async def test_report_route_serves_the_current_report(root: Path, settings: Settings) -> None:
    service = HazardService(root, profile="fixture")
    async with await client_for(make_app(settings, service)) as client:
        report = await client.get("/api/hazards/clips/hz_02/report")
        assert report.status_code == 200
        assert report.json()["pipeline"]["run_id"] == AGENT_RUN
        assert (await client.get("/api/hazards/clips/hz_01/report")).status_code == 404
        assert (await client.get("/api/hazards/clips/hz_99/report")).status_code == 404


def test_report_drops_a_non_neutral_source_name(root: Path) -> None:
    report = agent_report()
    report["video"]["source_name"] = "0_tr7.mp4"
    write_run(root, "hz_01", "run_named", report)
    served = HazardService(root, profile="fixture").report("hz_01")
    assert served is not None and "0_tr7" not in json.dumps(served)


async def test_instructions_carry_standards_and_schema(root: Path, settings: Settings) -> None:
    service = HazardService(root, profile="fixture")
    async with await client_for(make_app(settings, service)) as client:
        body = (await client.get("/api/hazards/instructions")).json()
    validate("Instructions", body)
    assert "1910.176(a)" in body["standards"]
    assert set(body["standards"]["1910.176(a)"]) <= {"title", "summary", "url"}
    enum = body["schema"]["$defs"]["Finding"]["properties"]["standards"]["items"]["enum"]
    assert enum == list(body["standards"])


# --------------------------------------------------------------------------- current run


def _gb10(report: dict[str, Any], generated: str, status: str = "model_review_complete"):
    return dict(report, generated_at_utc=generated, status=status)


def test_current_run_prefers_the_latest_completed_gb10_run(root: Path) -> None:
    store = hz.HazardStore(root)
    reports = root / "reports" / "hz_00"
    # Only the imported original run (not GB10): latest_run.json decides.
    assert store.current_run_dir("hz_00") == (reports / ORIGINAL_RUN).resolve()
    base = agent_report()
    write_run(root, "hz_00", "gb10_direct", _gb10(base, "2026-10-03T19:00:00+00:00"), point=False)
    assert store.current_run_dir("hz_00") == (reports / "gb10_direct").resolve()
    # A newer failed run does not replace it.
    write_run(
        root,
        "hz_00",
        "gb10_failed",
        _gb10(base, "2026-10-03T19:30:00+00:00", "model_review_failed"),
        point=False,
    )
    assert store.current_run_dir("hz_00") == (reports / "gb10_direct").resolve()
    # An agent run finished up to 15 minutes before the newest run wins ...
    write_run(
        root,
        "hz_00",
        "gb10_agent",
        _gb10(base, "2026-10-03T18:50:00+00:00"),
        point=False,
        extra_files={"agent_trace.json": []},
    )
    assert store.runner_of(reports / "gb10_agent") == "openclaw-agent"
    assert store.current_run_dir("hz_00") == (reports / "gb10_agent").resolve()
    # ... an older one does not.
    write_json(
        reports / "gb10_agent" / "hazard_report.json", _gb10(base, "2026-10-03T18:40:00+00:00")
    )
    assert store.current_run_dir("hz_00") == (reports / "gb10_direct").resolve()
    # job_timeline.json names the runner of the last live job.
    write_json(reports / "gb10_agent" / "job_timeline.json", {"runner": "direct"})
    assert store.runner_of(reports / "gb10_agent") == "direct"
    assert store.runner_of(None) is None


# --------------------------------------------------------------------------- composer


@pytest.mark.parametrize(
    ("raw", "named"),
    [
        ("Zone Z02 and Z06", "Zone 2 and Zone 6"),
        ("(Z03, Z05)", "(Zone 3, Zone 5)"),
        ("the zone Z10 near zones Z01", "Zone 10 near Zone 1"),
        ("Center of the marked aisle, Z07", "Center of the marked aisle, Zone 7"),
        ("E024 is a picture, not a zone", "E024 is a picture, not a zone"),
    ],
)
def test_name_zones(raw: str, named: str) -> None:
    assert hz.name_zones(raw) == named


def test_worker_zones_pictures_and_signs_on_the_agent_run() -> None:
    clip = {"clip_id": "hz_02", "title": "Floor camera 02", "duration_s": 14.982}
    report = agent_report()
    view = hz.compose_view(clip=clip, report=report, status="reviewed", wording=WORDING)
    worker = view["worker"]
    zone_ids = sorted(z["zone_id"] for z in report["zones"])
    assert [z["name"] for z in worker["zones"]] == [f"Zone {int(z[1:])}" for z in zone_ids]
    width, height = report["video"]["analysis_width"], report["video"]["analysis_height"]
    for zone, raw in zip(worker["zones"], sorted(report["zones"], key=lambda z: z["zone_id"])):
        if raw.get("bbox_normalized"):
            assert zone["box"] == pytest.approx(raw["bbox_normalized"], abs=1e-4)
        else:
            x0, y0, x1, y1 = raw["bbox_analysis"]
            assert zone["box"] == pytest.approx(
                [x0 / width, y0 / height, x1 / width, y1 / height], abs=1e-4
            )
    flagged = {n for h in worker["hazards"] for n in h["zone_names"]}
    assert {z["name"] for z in worker["zones"] if z["has_hazard"]} == flagged
    for hazard in worker["hazards"]:
        assert hazard["pictures"], hazard["title"]
        assert all(
            p["clean_url"].startswith("/api/hazards/clips/hz_02/media/evidence_clean/")
            for p in hazard["pictures"]
        )
        assert hazard["sign"]["label"].isupper()
    assert {h["sign"]["label"] for h in worker["hazards"]} <= {
        s["label"] for s in WORDING["signs"].values()
    } | {WORDING["sign_fallback"]["label"]}


def test_blindspot_clips_use_their_own_headlines_and_signs() -> None:
    clip = {"clip_id": "bs_01", "title": "Aisle camera 1", "duration_s": 15.0, "kind": "blindspot"}
    report = agent_report()
    findings = [
        dict(report["findings"][0], standards=["1910.178(n)(4)"]),
        dict(report["findings"][1], standards=[]),
    ]
    view = hz.compose_view(
        clip=clip, report=dict(report, findings=findings), status="reviewed", wording=WORDING
    )
    validate("HazardView", view)
    assert view["clip"]["kind"] == "blindspot"
    assert view["worker"]["headline"] == "2 blind spots found"
    signs = sorted((h["sign"]["label"], h["sign"]["glyph"]) for h in view["worker"]["hazards"])
    assert signs == [("BLIND CORNER", "eye-off"), ("BLIND SPOT", "eye-off")]
    one = hz.compose_view(
        clip=clip, report=dict(report, findings=findings[:1]), status="reviewed", wording=WORDING
    )
    assert one["worker"]["headline"] == "1 blind spot found"
    none = hz.compose_view(
        clip=clip, report=dict(report, findings=[]), status="reviewed", wording=WORDING
    )
    assert none["worker"]["headline"] == "No blind spots seen in this clip"
    hazard_clip = dict(clip, kind="hazard")
    plain = hz.compose_view(
        clip=hazard_clip,
        report=dict(report, findings=findings[1:]),
        status="reviewed",
        wording=WORDING,
    )
    assert plain["worker"]["hazards"][0]["sign"] == WORDING["sign_fallback"]


def test_unknown_clip_kind_reads_as_hazard(root: Path) -> None:
    write_clip(root, "bs_01", kind="blindspot")
    write_clip(root, "hz_09", kind="bus")
    service = HazardService(root, profile="fixture")
    kinds = {c["clip_id"]: c["kind"] for c in service.list_clips()}
    assert (
        kinds["bs_01"] == "blindspot" and kinds["hz_09"] == "hazard" and kinds["hz_00"] == "hazard"
    )


# --------------------------------------------------------------------------- clean evidence


def _evidence_canvas(content_w: int, content_h: int) -> np.ndarray:
    canvas_w = max(content_w, EVIDENCE_MIN_CANVAS_W)
    image = np.full((hz.EVIDENCE_HEADER_PX + content_h, canvas_w, 3), 22, np.uint8)
    image[: hz.EVIDENCE_HEADER_PX] = 0  # label strip
    image[hz.EVIDENCE_HEADER_PX :, :content_w] = (40, 200, 120)  # picture
    return image


async def test_clean_evidence_drops_the_label_strip_and_padding(
    root: Path, settings: Settings
) -> None:
    report = load(SOURCE, "hazard_report.json")
    item = next(e for e in report["evidence"] if e["evidence_id"] == "E024")
    width = hz.clean_width(item, report["config"], EVIDENCE_MIN_CANVAS_W)
    assert width == 285  # a 285 px zone crop padded to the 520 px canvas
    raw = root / "reports" / "hz_00" / ORIGINAL_RUN / "evidence" / "E024.jpg"
    assert cv2.imwrite(str(raw), _evidence_canvas(width, 200))
    service = HazardService(root, profile="fixture")
    async with await client_for(make_app(settings, service)) as client:
        response = await client.get("/api/hazards/clips/hz_00/media/evidence_clean/E024.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        clean = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        assert clean.shape[:2] == (200, width)
        assert abs(int(clean[100, width // 2, 1]) - 200) < 12  # picture, not padding
        # A newer raw picture is cut again.
        assert cv2.imwrite(str(raw), _evidence_canvas(width, 120))
        future = time.time() + 5
        os.utime(raw, (future, future))
        again = await client.get("/api/hazards/clips/hz_00/media/evidence_clean/E024.jpg")
        img = cv2.imdecode(np.frombuffer(again.content, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[:2] == (120, width)
        for bad in ("E999", "E24", "../E024"):
            url = f"/api/hazards/clips/hz_00/media/evidence_clean/{bad}.jpg"
            assert (await client.get(url)).status_code == 404


def test_full_scene_pictures_keep_their_scaled_width() -> None:
    item = {"kind": "full scene", "bbox_source": [0, 0, 1920, 1080]}
    assert hz.clean_width(item, {"image_width": 1024, "crop_width": 768}, 1024) == 1024
    tile = {"kind": "scene tile", "bbox_source": [0, 0, 300, 200]}
    assert hz.clean_width(tile, {"crop_width": 768}, 520) == 300
    assert hz.clean_width({"kind": "zone crop"}, {}, 520) == 520


def test_concurrent_replays_of_different_clips_run_side_by_side(root: Path) -> None:
    gate = threading.Event()

    def slow_sleep(seconds: float) -> None:
        gate.wait(0.01)

    service = HazardService(
        root, profile="gb10", fixture=False, demo_replay=True, review_fn=no_model, sleep=slow_sleep
    )
    jobs = [service.start_review(c) for c in ("hz_00", "hz_02")]
    for job in jobs:
        assert wait_finished(job)[-1][0] == "done"


def test_agent_run_files_are_copied_verbatim(root: Path) -> None:
    run_dir = root / "reports" / "hz_02" / AGENT_RUN
    for name in AGENT_FILES:
        assert json.loads((run_dir / name).read_text()) == load(AGENT_SOURCE, name)
    shutil.rmtree(run_dir)
    assert hz.HazardStore(root).current_run_dir("hz_02") is None

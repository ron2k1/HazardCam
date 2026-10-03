"""Site runs (lead + six concurrent checkers): validation, tools, storage, endpoint, replay.

Hermetic: a fake hazard service stands in for the checkers and a fake lead calls the
three site tools the way the ``site-lead`` OpenClaw agent does.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import wall as wall_routes
from apps.api.services.site_runs import SiteRun, SiteService, validate_alerts

CAMS = [
    {"cam": 1, "clip_id": "hz_01", "kind": "hazard", "label": "FORKLIFT"},
    {"cam": 2, "clip_id": "hz_02", "kind": "hazard", "label": "PPE"},
    {"cam": 3, "clip_id": "hz_03", "kind": "hazard", "label": "SPILL"},
    {"cam": 4, "clip_id": "bs_01", "kind": "blindspot", "label": "BLIND SPOT"},
    {"cam": 5, "clip_id": "bs_02", "kind": "blindspot", "label": "BLIND SPOT"},
    {"cam": 6, "clip_id": "bs_03", "kind": "blindspot", "label": "BLIND SPOT"},
]
REPORTS = {
    "hz_01": [
        {
            "finding_id": "H01",
            "severity": "high",
            "title": "Forklift near walkers",
            "zone_ids": ["Z3"],
        }
    ],
    "hz_02": [{"finding_id": "H01", "severity": "low", "title": "No vest", "zone_ids": ["Z1"]}],
    "bs_01": [
        {"finding_id": "H02", "severity": "medium", "title": "Blind corner", "zone_ids": ["Z2"]}
    ],
}


class FakeJob:
    def __init__(self, job_id: str, clip_id: str, delay: float, store: FakeStore) -> None:
        self.job_id, self.clip_id = job_id, clip_id
        self.state = "running"
        self.started = time.monotonic()

        def finish() -> None:
            time.sleep(delay)
            self.state = "done"

        threading.Thread(target=finish, daemon=True).start()

    @property
    def finished(self) -> bool:
        return self.state != "running"


class FakeStore:
    def current_run_dir(self, clip_id: str) -> Path:
        return Path("/nonexistent") / clip_id

    def report(self, run_dir: Path) -> dict[str, Any]:
        return {"status": "model_review_complete", "findings": REPORTS.get(run_dir.name, [])}

    def agent_summary(self, run_dir: Path) -> dict[str, Any]:
        found = REPORTS.get(run_dir.name, [])
        return {
            "headline": f"{run_dir.name} checked",
            "priority": found[0]["severity"] if found else "none",
            "confirmed_finding_ids": [f["finding_id"] for f in found],
        }


class FakeHazards:
    replays_by_default = False

    def __init__(self, delay: float = 0.3) -> None:
        self.store = FakeStore()
        self.delay = delay
        self.jobs: dict[str, FakeJob] = {}
        self.calls: list[tuple[str, str]] = []
        self._n = 0

    def start_review(self, clip_id: str, *, mode: str | None = None, runner=None, runner_name=None):
        self._n += 1
        job = FakeJob(f"job{self._n}", clip_id, self.delay, self.store)
        self.jobs[job.job_id] = job
        self.calls.append((clip_id, str(mode)))
        return job

    def job(self, job_id: str):
        return self.jobs.get(job_id)


def good_lead(run: SiteRun, sites: SiteService) -> None:
    sites.start_checks(run)
    while not sites.check_status(run, wait_s=0.5)["result"]["all_finished"]:
        pass
    bad = sites.submit_alerts(
        run, [{"cam": 9, "severity": "high", "finding_ids": ["F1"], "line": "x CAM 9"}]
    )
    assert not bad["ok"]
    ok = sites.submit_alerts(
        run,
        [
            {
                "cam": 1,
                "severity": "high",
                "finding_ids": ["H01"],
                "line": "CAM 1: forklift near walkers in Zone 3",
            },
            {
                "cam": 4,
                "severity": "medium",
                "finding_ids": ["H02"],
                "line": "CAM 4: blind corner in Zone 2",
            },
        ],
    )
    assert ok["ok"], ok


def make_service(tmp_path: Path, lead=good_lead, delay: float = 0.3) -> SiteService:
    return SiteService(
        FakeHazards(delay),
        lambda: list(CAMS),
        tmp_path / "site_runs",
        lead_runner=lead,
        replay_seconds=1.0,
        poll_s=0.05,
    )


def wait_done(run: SiteRun, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while run.state == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert run.state == "done"


# -- validation -------------------------------------------------------------------


def done_checkers() -> dict[int, dict[str, Any]]:
    return {
        1: {"state": "done", "findings": [{"id": "F1", "severity": "high", "zone_ids": ["Z3"]}]},
        2: {"state": "done", "findings": [{"id": "F1", "severity": "low", "zone_ids": ["Z1"]}]},
        3: {"state": "failed", "findings": []},
    }


@pytest.mark.parametrize(
    ("alerts", "why"),
    [
        (
            [{"cam": 7, "severity": "high", "finding_ids": ["F1"], "line": "CAM 7 fire"}],
            "not on the wall",
        ),
        (
            [{"cam": 1, "severity": "high", "finding_ids": ["F9"], "line": "CAM 1 fire"}],
            "no finding F9",
        ),
        (
            [{"cam": 1, "severity": "medium", "finding_ids": ["F1"], "line": "CAM 1 fork"}],
            "not 'medium'",
        ),
        (
            [{"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 1 in Zone 5"}],
            "Zone 5",
        ),
        (
            [{"cam": 3, "severity": "high", "finding_ids": ["F1"], "line": "CAM 3 x"}],
            "no finished report",
        ),
        (
            [{"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 2 forklift"}],
            "another camera",
        ),
        (
            [
                {"cam": 2, "severity": "low", "finding_ids": ["F1"], "line": "CAM 2 vest"},
                {"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 1 fork"},
            ],
            "highest severity first",
        ),
        (
            [
                {"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 1 fork"},
                {"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 1 fork"},
            ],
            "twice",
        ),
    ],
)
def test_invented_alerts_are_refused(alerts, why):
    problem = validate_alerts(alerts, done_checkers())
    assert problem is not None and why in problem


def test_grounded_alerts_and_no_alerts_pass():
    ok = [
        {"cam": 1, "severity": "high", "finding_ids": ["F1"], "line": "CAM 1: forklift in Zone 3"}
    ]
    assert validate_alerts(ok, done_checkers()) is None
    assert validate_alerts([], done_checkers()) is None


# -- live run through the tools ---------------------------------------------------


def test_live_run_starts_six_checkers_concurrently_and_stores_the_alerts(tmp_path):
    sites = make_service(tmp_path, delay=0.5)
    t0 = time.monotonic()
    run = sites.start("live")
    wait_done(run)
    wall_s = time.monotonic() - t0
    snap = run.snapshot()
    assert [c["state"] for c in snap["checkers"]] == ["done"] * 6
    assert len({c["job_id"] for c in snap["checkers"]}) == 6
    starts = [c["started_s"] for c in snap["checkers"]]
    assert max(starts) - min(starts) < 0.4  # all six started together
    assert wall_s < 6 * 0.5  # concurrent, not one after another
    assert snap["alerts_source"] == "lead"
    assert [a["cam"] for a in snap["alerts"]] == [1, 4]
    assert all(a["job_id"] for a in snap["alerts"])
    out = tmp_path / "site_runs" / run.site_run_id
    for name in ("site_run.json", "lead_trace.json", "alerts.json"):
        assert (out / name).is_file()
    stored = sites.stored(run.site_run_id)
    assert stored is not None and stored["state"] == "done" and stored["lead_trace"]
    assert any("refused" in r["text"] for r in stored["lead_trace"])


def test_a_failed_lead_still_finishes_with_the_checkers_own_findings(tmp_path):
    def broken(run, sites):
        raise RuntimeError("lead crashed")

    sites = make_service(tmp_path, lead=broken)
    run = sites.start("live")
    wait_done(run)
    snap = run.snapshot()
    assert snap["alerts_source"] == "checkers"
    assert {a["cam"] for a in snap["alerts"]} == {1, 2, 4}
    assert snap["alerts"][0]["severity"] == "high"


def test_replay_compresses_the_latest_live_run_with_fresh_replay_jobs(tmp_path):
    sites = make_service(tmp_path, delay=0.2)
    live = sites.start("live")
    wait_done(live)
    hz: FakeHazards = sites.hazards
    hz.calls.clear()
    replay = sites.start("replay")
    wait_done(replay)
    assert replay.mode == "replay"
    assert sorted(c for c, _ in hz.calls) == sorted(c["clip_id"] for c in CAMS)
    assert all(mode == "replay" for _, mode in hz.calls)
    live_jobs = {c["job_id"] for c in live.snapshot()["checkers"]}
    alerts = replay.snapshot()["alerts"]
    assert [a["cam"] for a in alerts] == [1, 4]
    assert not live_jobs & {a["job_id"] for a in alerts}


def test_replay_without_a_stored_run_is_a_lookup_error(tmp_path):
    with pytest.raises(LookupError):
        make_service(tmp_path).start("replay")


# -- endpoint ---------------------------------------------------------------------


def api(tmp_path: Path, lead=good_lead) -> TestClient:
    app = FastAPI()
    app.include_router(wall_routes.router)
    app.state.site_runs = make_service(tmp_path, lead=lead)
    return TestClient(app)


def test_post_run_then_poll_the_snapshot(tmp_path):
    client = api(tmp_path)
    r = client.post("/api/wall/run", json={"mode": "live"})
    assert r.status_code == 202
    body = r.json()
    assert body["mode"] == "live" and len(body["cams"]) == 6
    deadline = time.monotonic() + 10
    snap: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snap = client.get(f"/api/wall/runs/{body['site_run_id']}").json()
        if snap["state"] == "done":
            break
        time.sleep(0.1)
    assert snap["state"] == "done" and [a["cam"] for a in snap["alerts"]] == [1, 4]
    assert client.get("/api/wall/runs/nope").status_code == 404


def test_post_run_without_a_lead_is_503_and_replay_without_a_run_is_404(tmp_path):
    client = api(tmp_path, lead=None)
    assert client.post("/api/wall/run", json={"mode": "live"}).status_code == 503
    assert client.post("/api/wall/run", json={"mode": "replay"}).status_code == 404

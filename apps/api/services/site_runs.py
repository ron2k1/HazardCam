"""Site runs on the camera wall: one lead agent, six concurrent camera checkers (event day).

A site run is what ``POST /api/wall/run`` starts. The lead (OpenClaw agent ``site-lead``,
``agent/event_day/site_lead.py``) drives it through three tools that land here:

* ``start_checks``: starts the six wall cameras' checks at once through the normal hazard
  review seam (``HazardService.start_review``), so each checker is the existing
  urban-mirror OpenClaw turn with its own job id, SSE stream and process page;
* ``check_status``: per-camera state, and for each finished checker its validated
  ``agent_summary`` plus its finding list (id, title, severity, zones);
* ``submit_alerts``: the lead's notification list, validated against the checkers'
  stored reports. Invented cameras, finding ids, zones or severities are refused.

Everything is stored under ``data/hazards/site_runs/<id>/``: ``site_run.json`` (checkers,
job ids, real timings, events), ``lead_trace.json`` and ``alerts.json``. In demo replay mode
``POST`` replays the latest completed site run, compressed to the hazard replay length,
with fresh per-camera replay jobs so every tile and process link still works.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}
TERMINAL = ("done", "failed")
LINE_MAX = 120
STATUS_WAIT_S = 15.0
_ZONE = re.compile(r"\bzone\s*([0-9]+)", re.IGNORECASE)
_DIGITS = re.compile(r"([0-9]+)")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sev(value: Any) -> str:
    return value if value in SEVERITY_RANK else "medium"


def _zone_numbers(zone_ids: Any) -> set[str]:
    out: set[str] = set()
    for z in zone_ids or []:
        m = _DIGITS.search(str(z))
        if m:
            out.add(str(int(m.group(1))))
    return out


def checker_findings(clip_id: str, run_dir: Path | None, report: Mapping[str, Any] | None):
    """The finding list a checker's agent saw (same ids as ``hazard_review_clip``)."""
    try:
        from agent.event_day.hazard_tools import review_summary

        rows = review_summary(clip_id, run_dir, report)["findings"]
    except Exception:  # noqa: BLE001 - the agent package is optional for the plain API
        rows = [
            {
                "id": str(f.get("finding_id") or f"F{i}"),
                "severity": _sev(f.get("severity")),
                "title": str(f.get("title", "")),
                "zone_ids": list(f.get("zone_ids") or []),
            }
            for i, f in enumerate((report or {}).get("findings") or [], 1)
        ]
    return [
        {
            "id": r["id"],
            "title": r.get("title", ""),
            "severity": _sev(r.get("severity")),
            "zone_ids": list(r.get("zone_ids") or []),
        }
        for r in rows
    ]


def validate_alerts(alerts: Any, checkers: Mapping[int, Mapping[str, Any]]) -> str | None:
    """Why ``alerts`` is refused, or ``None``. Every alert must name a finished camera,
    cite finding ids from that camera's report, carry that finding set's top severity
    and mention only zones those findings cover."""
    if not isinstance(alerts, list):
        return "alerts must be a list"
    if len(alerts) > len(checkers):
        return "more alerts than cameras"
    seen: set[int] = set()
    prev_rank = 99
    for n, alert in enumerate(alerts, 1):
        if not isinstance(alert, dict):
            return f"alert {n} must be an object"
        cam = alert.get("cam")
        if not isinstance(cam, int) or cam not in checkers:
            return f"alert {n}: camera {cam!r} is not on the wall"
        if cam in seen:
            return f"alert {n}: camera {cam} is listed twice"
        seen.add(cam)
        checker = checkers[cam]
        if checker.get("state") != "done":
            return f"alert {n}: CAM {cam} has no finished report"
        findings = {f["id"]: f for f in checker.get("findings") or []}
        ids = alert.get("finding_ids")
        if not isinstance(ids, list) or not ids:
            return f"alert {n}: cite at least one finding id from CAM {cam}'s report"
        unknown = [i for i in ids if i not in findings]
        if unknown:
            return f"alert {n}: CAM {cam}'s report has no finding {', '.join(map(str, unknown))}"
        top = max((findings[i]["severity"] for i in ids), key=lambda s: SEVERITY_RANK[s])
        severity = alert.get("severity")
        if severity != top:
            return f"alert {n}: CAM {cam}'s cited findings are {top}, not {severity!r}"
        rank = SEVERITY_RANK[top]
        if rank > prev_rank:
            return f"alert {n}: list alerts highest severity first"
        prev_rank = rank
        line = alert.get("line")
        if not isinstance(line, str) or not 3 <= len(line.strip()) <= LINE_MAX:
            return f"alert {n}: line must be 3-{LINE_MAX} characters"
        zones = set().union(*(_zone_numbers(findings[i]["zone_ids"]) for i in ids))
        for z in _ZONE.findall(line):
            if str(int(z)) not in zones:
                return f"alert {n}: Zone {z} is not in the cited findings"
        cams = {int(c) for c in re.findall(r"\bcam\s*([0-9]+)", line, re.IGNORECASE)}
        if cams - {cam}:
            return f"alert {n}: the line names another camera"
    return None


class SiteRun:
    """One lead plus six checkers. Thread-safe; events are replayable for SSE."""

    def __init__(self, site_run_id: str, cams: list[dict[str, Any]], mode: str) -> None:
        self.site_run_id = site_run_id
        self.mode = mode
        self.created_at = _now()
        self._t0 = time.monotonic()
        self._cond = threading.Condition()
        self._events: list[tuple[str, dict[str, Any]]] = []
        self.state = "running"
        self.checkers: dict[int, dict[str, Any]] = {
            int(c["cam"]): {
                "cam": int(c["cam"]),
                "clip_id": c["clip_id"],
                "kind": c.get("kind", "hazard"),
                "label": c.get("label", ""),
                "state": "queued",
                "job_id": None,
                "started_s": None,
                "ended_s": None,
                "started_at": None,
                "ended_at": None,
                "summary": None,
                "findings": [],
            }
            for c in cams
        }
        self.lead_trace: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] | None = None
        self.alerts_source: str | None = None
        self.lead_turn: dict[str, Any] | None = None
        self.checks_started = False
        self.ended_s: float | None = None

    # -- events -----------------------------------------------------------------------
    def t(self) -> float:
        return round(time.monotonic() - self._t0, 2)

    def emit(self, event: str, data: dict[str, Any]) -> None:
        with self._cond:
            self._events.append((event, {**data, "t_s": data.get("t_s", self.t())}))
            self._cond.notify_all()

    def say(self, text: str, kind: str = "say") -> None:
        row = {"t_s": self.t(), "kind": kind, "text": text}
        with self._cond:
            self.lead_trace.append(row)
        self.emit("lead", row)

    def events(self, start: int = 0) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
        with self._cond:
            return list(self._events[start:]), self.state in TERMINAL

    def wait_change(self, seen: int, timeout: float) -> None:
        with self._cond:
            self._cond.wait_for(lambda: len(self._events) > seen, timeout=timeout)

    async def stream(self, start: int = 0) -> AsyncIterator[tuple[int, str, dict[str, Any]]]:
        seq = start
        while True:
            batch, finished = self.events(seq)
            for event, data in batch:
                seq += 1
                yield seq, event, data
            if finished and not batch:
                return
            await asyncio.sleep(0.25)

    # -- checkers ---------------------------------------------------------------------
    def set_checker(self, cam: int, **fields: Any) -> None:
        with self._cond:
            self.checkers[cam].update(fields)
            row = dict(self.checkers[cam])
        self.emit(
            "checker",
            {
                k: row[k]
                for k in ("cam", "clip_id", "kind", "state", "job_id", "started_s", "ended_s")
            }
            | {"priority": (row.get("summary") or {}).get("priority")},
        )

    def all_finished(self) -> bool:
        with self._cond:
            return all(c["state"] in TERMINAL for c in self.checkers.values())

    def finish(self, state: str) -> None:
        with self._cond:
            if self.state in TERMINAL:
                return
            self.ended_s = self.t()
        self.emit(
            state,
            {"alerts": self.alerts or [], "alerts_source": self.alerts_source, "t_s": self.ended_s},
        )
        with self._cond:
            self.state = state
            self._cond.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._cond:
            return {
                "site_run_id": self.site_run_id,
                "mode": self.mode,
                "state": self.state,
                "created_at": self.created_at,
                "elapsed_s": self.ended_s if self.ended_s is not None else self.t(),
                "checkers": [
                    dict(c) for c in sorted(self.checkers.values(), key=lambda c: c["cam"])
                ],
                "lead_trace": list(self.lead_trace),
                "lead_turn": self.lead_turn,
                "alerts": self.alerts,
                "alerts_source": self.alerts_source,
                "events_url": f"/api/wall/runs/{self.site_run_id}/events",
            }


LeadRunner = Callable[["SiteRun", "SiteService"], None]


class SiteService:
    """Starts, tracks, stores and replays site runs."""

    def __init__(
        self,
        hazards: Any,
        tiles: Callable[[], list[dict[str, Any]]],
        root: Path,
        *,
        lead_runner: LeadRunner | None = None,
        checker_runner: Any = None,
        checker_runner_name: str | None = None,
        replay_seconds: float = 12.0,
        poll_s: float = 0.5,
    ) -> None:
        self.hazards = hazards
        self.tiles = tiles
        self.root = Path(root)
        self.lead_runner = lead_runner
        self.checker_runner = checker_runner
        self.checker_runner_name = checker_runner_name
        self.replay_seconds = replay_seconds
        self.poll_s = poll_s
        self._runs: dict[str, SiteRun] = {}
        self._lock = threading.Lock()

    def run(self, site_run_id: str) -> SiteRun | None:
        with self._lock:
            return self._runs.get(site_run_id)

    def _cams(self) -> list[dict[str, Any]]:
        return [
            {
                "cam": t["cam"],
                "clip_id": t["clip_id"],
                "kind": t.get("kind"),
                "label": t.get("label"),
            }
            for t in self.tiles()
        ]

    # -- start ------------------------------------------------------------------------
    def start(self, mode: str) -> SiteRun:
        if mode == "replay":
            stored = self.latest_completed()
            if stored is None:
                raise LookupError("no completed site run to replay")
            run = SiteRun(f"site-{uuid.uuid4().hex[:10]}", stored["cams"], "replay")
            target: Callable[[], None] = lambda: self._replay(run, stored)
        else:
            if self.lead_runner is None:
                raise RuntimeError("no lead agent on this API")
            run = SiteRun(
                f"site-{datetime.now(UTC).strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}",
                self._cams(),
                "live",
            )
            target = lambda: self._live(run)
        with self._lock:
            self._runs[run.site_run_id] = run
        threading.Thread(target=target, name=f"site:{run.site_run_id}", daemon=True).start()
        return run

    def _live(self, run: SiteRun) -> None:
        run.say("Lead agent is starting six camera checkers", "plan")
        try:
            assert self.lead_runner is not None
            self.lead_runner(run, self)
        except Exception as exc:  # the lead failed; the checkers' reports still stand
            logger.warning("site lead failed", exc_info=True)
            run.say(f"lead turn failed: {type(exc).__name__}", "tool")
        if not run.checks_started:
            self.start_checks(run)
        while not run.all_finished():
            time.sleep(self.poll_s)
        if run.alerts is None:
            run.alerts = self.fallback_alerts(run)
            run.alerts_source = "checkers"
            run.say("Lead agent did not submit alerts; showing the checkers' own findings", "tool")
        run.finish("done")
        self.save(run)

    # -- tools ------------------------------------------------------------------------
    def start_checks(self, run: SiteRun) -> dict[str, Any]:
        if run.checks_started:
            return {"ok": True, "result": {"started": False, "note": "checks already running"}}
        run.checks_started = True
        for cam, checker in sorted(run.checkers.items()):
            self._start_checker(run, cam, checker["clip_id"], mode="live")
        return {
            "ok": True,
            "result": {
                "started": True,
                "cameras": [{"cam": c, "kind": k["kind"]} for c, k in sorted(run.checkers.items())],
                "next": "call mirror__site_check_status until every camera is done or failed",
            },
        }

    def _start_checker(self, run: SiteRun, cam: int, clip_id: str, *, mode: str) -> str | None:
        try:
            job = self.hazards.start_review(
                clip_id,
                mode=mode,
                runner=self.checker_runner if mode == "live" else None,
                runner_name=self.checker_runner_name if mode == "live" else None,
            )
        except Exception as exc:  # noqa: BLE001 - JobConflict (job_id) or a failed start
            job_id = getattr(exc, "job_id", None)
            job = self.hazards.job(job_id) if job_id else None
            if job is None:
                run.set_checker(cam, state="failed", ended_s=run.t(), ended_at=_now())
                return None
        run.set_checker(
            cam, state="running", job_id=job.job_id, started_s=run.t(), started_at=_now()
        )
        threading.Thread(
            target=self._watch, args=(run, cam, job), name=f"checker:{cam}", daemon=True
        ).start()
        return str(job.job_id)

    def _watch(self, run: SiteRun, cam: int, job: Any) -> None:
        while not job.finished:
            time.sleep(self.poll_s)
        clip_id = run.checkers[cam]["clip_id"]
        store = self.hazards.store
        run_dir = store.current_run_dir(clip_id)
        report = store.report(run_dir) if run_dir else None
        summary = store.agent_summary(run_dir) if run_dir else None
        findings = checker_findings(clip_id, run_dir, report) if report else []
        state = "done" if job.state == "done" else "failed"
        run.set_checker(
            cam, state=state, ended_s=run.t(), ended_at=_now(), summary=summary, findings=findings
        )

    def check_status(self, run: SiteRun, wait_s: float = STATUS_WAIT_S) -> dict[str, Any]:
        seen = len(run.events()[0])
        if not run.all_finished():
            run.wait_change(seen, wait_s)
        with run._cond:
            cams = [dict(c) for c in sorted(run.checkers.values(), key=lambda c: c["cam"])]
        rows = []
        for c in cams:
            row: dict[str, Any] = {"cam": c["cam"], "watch": c["kind"], "state": c["state"]}
            if c["state"] == "done":
                s = c.get("summary") or {}
                row["summary"] = {
                    k: s.get(k) for k in ("headline", "priority", "confirmed_finding_ids")
                }
                row["findings"] = c["findings"]
            rows.append(row)
        done = all(r["state"] in TERMINAL for r in rows)
        return {
            "ok": True,
            "result": {
                "all_finished": done,
                "cameras": rows,
                "next": "call mirror__site_submit_alerts"
                if done
                else "call mirror__site_check_status again",
            },
        }

    def submit_alerts(self, run: SiteRun, alerts: Any) -> dict[str, Any]:
        if run.alerts is not None:
            return {
                "ok": False,
                "error": "alerts already submitted; reply with the FINAL line",
                "refused": True,
            }
        if not run.all_finished():
            return {
                "ok": False,
                "error": "some checkers are still running; poll status first",
                "refused": False,
            }
        with run._cond:
            checkers = {k: dict(v) for k, v in run.checkers.items()}
        problem = validate_alerts(alerts, checkers)
        if problem:
            run.say(f"alerts refused: {problem}", "tool")
            return {
                "ok": False,
                "error": f"alerts not accepted: {problem}. Fix and resubmit.",
                "refused": False,
            }
        clean = [
            {
                "cam": a["cam"],
                "clip_id": checkers[a["cam"]]["clip_id"],
                "kind": checkers[a["cam"]]["kind"],
                "job_id": checkers[a["cam"]]["job_id"],
                "severity": a["severity"],
                "finding_ids": list(a["finding_ids"]),
                "line": a["line"].strip(),
            }
            for a in alerts
        ]
        run.alerts = clean
        run.alerts_source = "lead"
        run.say(f"Lead agent sent {len(clean)} alert(s)", "alerts")
        run.emit("alerts", {"alerts": clean, "alerts_source": "lead"})
        return {"ok": True, "result": {"accepted": len(clean), "next": "reply with the FINAL line"}}

    @staticmethod
    def fallback_alerts(run: SiteRun) -> list[dict[str, Any]]:
        out = []
        for c in run.checkers.values():
            s = c.get("summary") or {}
            if c["state"] != "done" or s.get("priority") in (None, "none"):
                continue
            out.append(
                {
                    "cam": c["cam"],
                    "clip_id": c["clip_id"],
                    "kind": c["kind"],
                    "job_id": c["job_id"],
                    "severity": s["priority"],
                    "finding_ids": list(s.get("confirmed_finding_ids") or []),
                    "line": str(s.get("headline", ""))[:LINE_MAX],
                }
            )
        out.sort(key=lambda a: -SEVERITY_RANK.get(a["severity"], 0))
        return out

    # -- storage ----------------------------------------------------------------------
    def save(self, run: SiteRun) -> Path:
        out = self.root / run.site_run_id
        out.mkdir(parents=True, exist_ok=True)
        snap = run.snapshot()
        events, _ = run.events()
        site = {
            **{k: v for k, v in snap.items() if k != "lead_trace"},
            "cams": [
                {k: c[k] for k in ("cam", "clip_id", "kind", "label")} for c in snap["checkers"]
            ],
            "events": [{"event": e, "data": d} for e, d in events],
        }
        (out / "site_run.json").write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
        (out / "lead_trace.json").write_text(
            json.dumps({"lead_trace": snap["lead_trace"], "lead_turn": snap["lead_turn"]}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (out / "alerts.json").write_text(
            json.dumps({"alerts": snap["alerts"], "source": snap["alerts_source"]}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return out

    def latest_completed(self) -> dict[str, Any] | None:
        best: tuple[str, dict[str, Any]] | None = None
        for path in self.root.glob("*/site_run.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("state") != "done" or data.get("mode") != "live":
                continue
            key = str(data.get("created_at", ""))
            if best is None or key > best[0]:
                best = (key, data)
        return best[1] if best else None

    def stored(self, site_run_id: str) -> dict[str, Any] | None:
        path = self.root / site_run_id / "site_run.json"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", site_run_id) or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        trace = self.root / site_run_id / "lead_trace.json"
        if trace.is_file():
            data["lead_trace"] = json.loads(trace.read_text(encoding="utf-8")).get("lead_trace", [])
        data.pop("events", None)
        return data

    # -- replay -----------------------------------------------------------------------
    def _replay(self, run: SiteRun, stored: Mapping[str, Any]) -> None:
        events = list(stored.get("events") or [])
        span = max((float(e["data"].get("t_s") or 0) for e in events), default=0.0) or 1.0
        scale = min(1.0, self.replay_seconds / span)
        jobs: dict[int, str] = {}
        t0 = time.monotonic()
        for e in events:
            event, data = e["event"], dict(e["data"])
            at = float(data.get("t_s") or 0) * scale
            delay = at - (time.monotonic() - t0)
            if delay > 0:
                time.sleep(delay)
            if event == "lead":
                run.say(data.get("text", ""), data.get("kind", "say"))
            elif event == "checker":
                cam = int(data["cam"])
                if data["state"] == "running" and cam not in jobs:
                    jobs[cam] = self._start_checker(run, cam, data["clip_id"], mode="replay") or ""
                # terminal checker state arrives through the replay job's watcher
            elif event == "alerts":
                run.alerts = [
                    {**a, "job_id": jobs.get(int(a["cam"]), a.get("job_id"))}
                    for a in data["alerts"]
                ]
                run.alerts_source = data.get("alerts_source", "lead")
                run.emit("alerts", {"alerts": run.alerts, "alerts_source": run.alerts_source})
        if run.alerts is None:
            stored_alerts = stored.get("alerts") or []
            run.alerts = [
                {**a, "job_id": jobs.get(int(a["cam"]), a.get("job_id"))} for a in stored_alerts
            ]
            run.alerts_source = stored.get("alerts_source")
        deadline = time.monotonic() + max(60.0, self.replay_seconds * 4)
        while not run.all_finished() and time.monotonic() < deadline:
            time.sleep(self.poll_s)
        run.finish("done")


__all__ = ["SiteRun", "SiteService", "checker_findings", "validate_alerts"]

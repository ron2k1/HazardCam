"""One real judged run through the running API, with per-stage latency and GT-exclusion proof (D03).

    .venv/bin/python scripts/runtime/judged_run.py [--scenario scenario_001] [--profile gb10]
        [--api http://127.0.0.1:8088] [--sandbox ambient-mirror] [--out artifacts/event_day/d03]

Uses the API that is already running (``scripts/runtime/start_api.sh``, agent executor); it
never starts or restarts one. Writes ``sse_<run_id>.txt`` (the raw stream) and
``judged_run_<run_id>.json`` (latency + proof) under ``--out`` and prints a summary.

Latency comes from the run's own envelope timestamps: agent start-up (``run.started`` to the
first ``tool.started``), each tool's ``latency_ms``, the agent's model time between tool calls,
and the close (last tool to ``run.complete``).

Ground-truth exclusion is checked on every surface the model or agent can see. The tokens
are ``apps.api.services.gt_guard.ground_truth_tokens`` plus the camera label, its MEVA id and
the judge route. Each scan also counts a positive control (visible camera ids), so a scan that
read nothing cannot pass:

1. the public scenario view, the one the run is built from;
2. the media route refuses the withheld camera;
3. the SSE stream;
4. the run directory (events, run record, agent turn, agent policy);
5. the agent's own OpenClaw session transcript in the sandbox (system prompt, brief, every tool
   call and result Qwen saw);
6. the sandbox filesystem holds no copy of the withheld video.

Nothing here reads or prints the tool server's token.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from apps.api.schemas import Scenario
from apps.api.services.gt_guard import GtGuard, ground_truth_tokens

STAGES = {
    "sample_video": "perception",
    "inspect_camera": "perception",
    "correlate_observations": "fusion",
    "triangulate_region": "fusion",
    "reason_hypothesis": "reasoning",
    "get_supporting_frames": "evidence",
    "submit_hypothesis": "submit",
}
TERMINAL = {"run.complete", "run.failed"}
SESSIONS = "/sandbox/.openclaw/agents/{agent}/sessions/sessions.json"


def openshell() -> str:
    found = shutil.which("openshell") or str(Path.home() / ".local" / "bin" / "openshell")
    if not Path(found).exists():
        raise SystemExit("openshell not found (add ~/.local/bin to PATH)")
    return found


def sandbox_sh(sandbox: str, script: str) -> str:
    proc = subprocess.run(
        [openshell(), "sandbox", "exec", "-n", sandbox, "--", "sh", "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sandbox exec failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
    return proc.stdout


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


class Scanner:
    """The app's GT guard tokens plus label, MEVA id and judge route; controls are visible ids."""

    def __init__(self, scenario: Scenario) -> None:
        gt = scenario.ground_truth_camera
        extra = [gt.label, "/api/judge"]
        extra += re.findall(r"\bMEVA (G\d+)\b", gt.label or "")
        self.tokens = tuple(sorted({*ground_truth_tokens(scenario), *filter(None, extra)}, key=len))
        self.guard = GtGuard(tuple(sorted(self.tokens, key=len, reverse=True)))
        self.controls = tuple(c.id for c in scenario.visible_cameras)

    def scan(self, name: str, text: str) -> dict[str, Any]:
        hits = sorted(set(self.guard._pattern.findall(text))) if self.guard._pattern else []
        control = {
            c: len(re.findall(rf"(?<![A-Za-z0-9_\-]){re.escape(c)}(?![A-Za-z0-9_\-])", text))
            for c in self.controls
        }
        ok = not hits and any(control.values())
        return {
            "check": name,
            "ok": ok,
            "bytes": len(text),
            "gt_hits": hits,
            "control_hits": control,
        }


def stream_run(api: str, run_id: str, raw_path: Path, timeout_s: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with (
        raw_path.open("w", encoding="utf-8") as raw,
        httpx.stream(
            "GET", f"{api}/api/runs/{run_id}/events", timeout=httpx.Timeout(timeout_s, connect=10)
        ) as resp,
    ):
        resp.raise_for_status()
        for line in resp.iter_lines():
            raw.write(line + "\n")
            if line.startswith("data:"):
                envelope = json.loads(line[5:].strip())
                envelope["_recv"] = time.time()
                events.append(envelope)
                if envelope["type"] in TERMINAL:
                    break
    return events


def latency(events: list[dict[str, Any]]) -> dict[str, Any]:
    events = sorted(events, key=lambda e: e["seq"])
    t0 = ts(events[0]["ts"])
    rel = lambda e: round(ts(e["ts"]) - t0, 3)
    starts = {e["payload"]["call_id"]: e for e in events if e["type"] == "tool.started"}
    calls, think, prev_end = [], 0.0, None
    for done in (e for e in events if e["type"] == "tool.completed"):
        p = done["payload"]
        start = starts.get(p["call_id"])
        if start and prev_end is not None:
            think += ts(start["ts"]) - prev_end
        prev_end = ts(done["ts"])
        calls.append(
            {
                "call_id": p["call_id"],
                "tool": p["tool"],
                "stage": STAGES.get(p["tool"], "other"),
                "ok": p.get("ok"),
                "started_s": rel(start) if start else None,
                "latency_s": round((p.get("latency_ms") or 0) / 1000, 3),
                "args": (start or {}).get("payload", {}).get("args_summary"),
            }
        )
    stages: dict[str, dict[str, float]] = {}
    for c in calls:
        s = stages.setdefault(c["stage"], {"calls": 0, "tool_s": 0.0, "max_s": 0.0})
        s["calls"] += 1
        s["tool_s"] = round(s["tool_s"] + c["latency_s"], 3)
        s["max_s"] = max(s["max_s"], c["latency_s"])
    first = lambda kind: next((rel(e) for e in events if e["type"] == kind), None)
    end = events[-1]
    tool_s = round(sum(c["latency_s"] for c in calls), 3)
    first_tool = first("tool.started")
    return {
        "terminal": end["type"],
        "total_s": rel(end),
        "agent_startup_s": first_tool,
        "agent_think_between_tools_s": round(think, 3),
        "agent_close_s": round(ts(end["ts"]) - prev_end, 3) if prev_end else None,
        "tool_time_s": tool_s,
        "first_observation_s": first("camera.observation"),
        "first_hypothesis_s": first("hypothesis.updated"),
        "triangulation_s": first("triangulation.updated"),
        "stages": stages,
        "calls": calls,
        "event_count": len(events),
    }


def transcript(sandbox: str, agent: str, run_id: str) -> tuple[dict[str, Any], str]:
    sessions = json.loads(sandbox_sh(sandbox, f"cat {SESSIONS.format(agent=agent)}"))
    key = next((k for k in sessions if k.endswith(":" + run_id.lower())), None)
    if key is None:
        raise RuntimeError(f"no OpenClaw session for {run_id}")
    entry = sessions[key]
    session_file = entry["sessionFile"]
    trajectory = session_file.removesuffix(".jsonl") + ".trajectory.jsonl"
    text = sandbox_sh(sandbox, f"cat '{session_file}'; cat '{trajectory}' 2>/dev/null || true")
    meta = {
        k: entry.get(k)
        for k in (
            "sessionId",
            "status",
            "model",
            "modelProvider",
            "contextTokens",
            "inputTokens",
            "outputTokens",
            "runtimeMs",
            "abortedLastRun",
        )
    }
    return {
        "session_key": key,
        "session_file": session_file,
        "trajectory": trajectory,
        **meta,
    }, text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="judged_run.py")
    parser.add_argument("--api", default=os.environ.get("AUM_API", "http://127.0.0.1:8088"))
    parser.add_argument("--scenario", default="scenario_001")
    parser.add_argument("--profile", default="gb10")
    parser.add_argument("--sandbox", default=os.environ.get("AUM_SANDBOX", "ambient-mirror"))
    parser.add_argument("--agent", default="urban-mirror")
    parser.add_argument("--out", type=Path, default=REPO / "artifacts" / "event_day" / "d03")
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--turn-wait", type=float, default=180.0, help="s to wait for the turn")
    parser.add_argument("--run-id", help="re-verify a finished run instead of starting one")
    args = parser.parse_args(argv)
    args.out = args.out.resolve()  # the report paths are written relative to REPO
    args.out.mkdir(parents=True, exist_ok=True)

    scenario = Scenario.model_validate_json(
        (REPO / "data" / "manifests" / f"{args.scenario}.json").read_text(encoding="utf-8")
    )
    gt_id = scenario.ground_truth_camera.id
    scanner = Scanner(scenario)
    proof: list[dict[str, Any]] = []

    with httpx.Client(base_url=args.api, timeout=30) as api:
        health = api.get("/healthz").json()
        models = api.get("/api/models/health").json()
        public = api.get(f"/api/scenarios/{args.scenario}")
        proof.append(scanner.scan("public_scenario_view", public.text))
        gt_media = api.get(f"/media/scenarios/{args.scenario}/cameras/{gt_id}")
        proof.append(
            {
                "check": "media_route_refuses_gt",
                "ok": gt_media.status_code == 403,
                "status": gt_media.status_code,
                "detail": gt_media.text[:120],
            }
        )

        posted_at = time.time()
        if args.run_id:
            run_id = args.run_id
            print(f"re-verifying {run_id} (no new run)", flush=True)
        else:
            created = api.post(
                "/api/runs", json={"scenario_id": args.scenario, "profile": args.profile}
            )
            created.raise_for_status()
            run_id = created.json()["run_id"]
            print(f"run {run_id} started ({args.scenario}, {args.profile})", flush=True)

    raw_path = args.out / f"sse_{run_id}.txt"
    events = stream_run(args.api, run_id, raw_path, args.timeout)
    wall_s = round(events[-1]["_recv"] - posted_at, 3) if events and not args.run_id else None
    record = httpx.get(f"{args.api}/api/runs/{run_id}", timeout=30).json()
    proof.append(scanner.scan("sse_stream", raw_path.read_text(encoding="utf-8")))

    # The policy closes the run at submit; the OpenClaw turn (its FINAL reply) ends after that.
    # Scan only once the turn has ended, so the transcript and run files are complete.
    runs_dir = Path(health["dependencies"]["runs_dir"]["path"]) / run_id
    deadline = time.time() + args.turn_wait
    while not (runs_dir / "agent_turn.json").exists() and time.time() < deadline:
        time.sleep(2)
    run_files = {p.name: p.read_text(encoding="utf-8") for p in sorted(runs_dir.glob("*.json*"))}
    proof.append(
        {**scanner.scan("run_dir_files", "\n".join(run_files.values())), "files": sorted(run_files)}
    )

    session: dict[str, Any] = {}
    try:
        session, text = transcript(args.sandbox, args.agent, run_id)
        scan = scanner.scan("agent_session_transcript", text)
        scan["run_id_present"] = run_id in text or run_id.lower() in text
        scan["session_status"] = session.get("status")
        scan["ok"] = scan["ok"] and scan["run_id_present"] and session.get("status") == "done"
        proof.append(scan)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        proof.append({"check": "agent_session_transcript", "ok": False, "error": str(exc)[:300]})

    try:
        name = Path(scenario.ground_truth_camera.file).name
        found = sandbox_sh(
            args.sandbox,
            f"find / \\( -path /proc -o -path /sys -o -path /dev \\) -prune -o -name '{name}' -print"
            f" 2>/dev/null; find / \\( -path /proc -o -path /sys \\) -prune -o -type d -name '{args.scenario}'"
            " -print 2>/dev/null; true",
        ).split()
        proof.append(
            {
                "check": "sandbox_filesystem",
                "ok": not found,
                "searched_for": [name, args.scenario],
                "found": found,
            }
        )
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        proof.append({"check": "sandbox_filesystem", "ok": False, "error": str(exc)[:300]})

    def read(name: str) -> Any:
        try:
            return json.loads(run_files[name])
        except (KeyError, ValueError):
            return None

    policy = read("agent_policy.json") or {}
    report = {
        "run_id": run_id,
        "scenario_id": args.scenario,
        "profile": args.profile,
        "api": args.api,
        "status": record.get("state"),
        "error": record.get("error"),
        "harness": next(
            (e["payload"].get("harness") for e in events if e["type"] == "run.started"), None
        ),
        "models": {
            slot: {k: models.get(slot, {}).get(k) for k in ("base_url", "model", "status")}
            for slot in ("perception", "reasoning")
        },
        "final": record.get("hypothesis"),
        "client_wall_s": wall_s,
        "latency": latency(events) if events else None,
        "agent_turn": read("agent_turn.json"),
        "agent_policy": {
            k: policy.get(k)
            for k in (
                "calls",
                "refusals",
                "failures",
                "per_tool",
                "elapsed_s",
                "closed",
                "finalized_by_policy",
                "stop_reason",
            )
        },
        "agent_session": session,
        "gt_exclusion": {
            "withheld_camera": gt_id,
            "tokens": list(scanner.tokens),
            "controls": list(scanner.controls),
            "ok": all(p["ok"] for p in proof),
            "checks": proof,
        },
        "sse_file": str(raw_path.relative_to(REPO)),
    }
    out = args.out / f"judged_run_{run_id}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lat = report["latency"] or {}
    print(
        f"status={report['status']} harness={report['harness']} total={lat.get('total_s')}s "
        f"wall={wall_s}s startup={lat.get('agent_startup_s')}s think={lat.get('agent_think_between_tools_s')}s "
        f"tools={lat.get('tool_time_s')}s close={lat.get('agent_close_s')}s"
    )
    for stage, s in (lat.get("stages") or {}).items():
        print(f"  {stage:<10} calls={s['calls']:<2} tool_s={s['tool_s']:<7} max_s={s['max_s']}")
    for p in proof:
        print(
            f"  GT {p['check']:<26} {'OK' if p['ok'] else 'FAIL'} hits={p.get('gt_hits', '-')}"
            f" control={p.get('control_hits', p.get('status', p.get('found', '-')))}"
        )
    print(f"wrote {out.relative_to(REPO)}")
    turn_ok = bool((report["agent_turn"] or {}).get("ok"))
    return 0 if report["status"] == "complete" and turn_ok and report["gt_exclusion"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

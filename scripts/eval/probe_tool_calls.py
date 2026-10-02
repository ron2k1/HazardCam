#!/usr/bin/env python3
"""Run the single-turn tool-call probe (``eval/tool_probe.py``) against local reasoning models.

  python scripts/eval/probe_tool_calls.py                       # lite-local and full-local
  python scripts/eval/probe_tool_calls.py --profile full-local --scenario eval_007

The transcript is a fixture-mode ToolSession run of one prepared scenario (its own
recording). Each case is one ``/chat/completions`` request with ``tools``; no reply is
executed or answered. Writes ``<out>/<profile>.json`` per profile and rebuilds
``<out>/PROBE.md`` from every profile probed so far. Exit status 1 if any request failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from apps.api.services.scenarios import LoadedScenario, ScenarioStore
from eval.tool_probe import (
    REQUEST_FAILED,
    SYSTEM_PROMPT,
    Case,
    Step,
    build_cases,
    score_reply,
    summarize_probe,
    tool_definitions,
)
from harness.dev_sequence import cited_frames
from inference.client import CONNECT_TIMEOUT_S, ChatClient
from inference.profiles import EndpointConfig, load_profile
from tools.session import ToolSession

OUT = REPO / "artifacts" / "eval" / "tool_probe"
RUNS_DIR = REPO / "data" / "runs" / "tool_probe"
DEFAULT_PROFILES = ("lite-local", "full-local")
DEFAULT_SCENARIO = "eval_001"


def record_steps(loaded: LoadedScenario, run_dir: Path) -> tuple[list[str], list[Step]]:
    """Drive a fixture ToolSession in the harness order through ``call_tool``."""
    completed: list[dict[str, Any]] = []

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "tool.completed":
            completed.append(payload)

    session = ToolSession(
        loaded.scenario.model_view(),
        load_profile("fixture"),
        emit,
        run_dir=run_dir,
        media_root=REPO,
    )
    steps: list[Step] = []

    def call(name: str, arguments: dict[str, Any]) -> None:
        session.call_tool(name, arguments)
        steps.append(Step(name, arguments, {"ok": True, **completed[-1]["result_summary"]}))

    for camera_id in session.camera_ids:
        call("sample_video", {"camera_id": camera_id})
        call("inspect_camera", {"camera_id": camera_id})
    call("correlate_observations", {})
    call("triangulate_region", {})
    call("reason_hypothesis", {})
    assert session.bundle is not None and session.raw_hypothesis is not None
    for camera_id, indices in cited_frames(
        session.bundle, session.raw_hypothesis, session.manifests
    ).items():
        call("get_supporting_frames", {"camera_id": camera_id, "frame_indices": indices})
    call("submit_hypothesis", {})
    return session.camera_ids, steps


def ask(endpoint: EndpointConfig, case: Case, tools: list[dict[str, Any]]) -> dict[str, Any]:
    client = ChatClient(endpoint)
    body = client.build_payload(case.messages, temperature=0.0)
    body.pop("response_format", None)  # a JSON-mode constraint would fight the tool call
    body["tools"] = tools
    key = endpoint.api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    timeout = httpx.Timeout(endpoint.timeout_seconds, connect=CONNECT_TIMEOUT_S)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as http:
            resp = http.post(client.url, json=body, headers=headers)
        latency = round(time.perf_counter() - started, 2)
        if resp.status_code >= 400:
            return _failed(case, f"HTTP {resp.status_code}", latency)
        message = resp.json()["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError("message is not an object")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        return _failed(case, type(exc).__name__, round(time.perf_counter() - started, 2))
    row = score_reply(case, message)
    row["latency_s"] = latency
    return row


def _failed(case: Case, error: str, latency: float) -> dict[str, Any]:
    return {
        "case": case.name,
        "tool_calls": 0,
        "content_chars": 0,
        "tool": None,
        "outcome": REQUEST_FAILED,
        "error": error,
        "invisible_camera": False,
        "latency_s": latency,
    }


def _rate(p: dict[str, Any]) -> str:
    if not p["n"]:
        return "n/a"
    lo, hi = p["wilson95"]
    return f"{p['k']}/{p['n']} = {p['rate']:.2f} [{lo:.2f}, {hi:.2f}]"


def render(summaries: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Tool-call capability probe",
        "",
        "Single-turn: one request per case, the reply is scored and never executed. Method,",
        "cases and scoring in `eval/tool_probe.py`. Not an agent loop and not the event-day",
        "playbook. Rates are k/n = rate [Wilson 95%].",
        "",
        (
            "| profile | model | pass | schema-valid call | outcomes | parallel"
            " | invisible camera | recovered | median s |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for profile, s in summaries.items():
        outcomes = ", ".join(f"{k} {v}" for k, v in s["outcomes"].items())
        lines.append(
            f"| {profile} | `{s['meta']['model']}` | {_rate(s['pass'])} | "
            f"{_rate(s['schema_valid'])} | {outcomes} | {s['parallel_calls']} | "
            f"{s['invisible_camera_calls']} | {s['recovered']} | {s['median_latency_s']} |"
        )
    cases = [r["case"] for r in next(iter(summaries.values()))["rows"]] if summaries else []
    lines += ["", "## Per case", "", "| case | " + " | ".join(summaries) + " |"]
    lines.append("|---|" + "---|" * len(summaries))
    for case in cases:
        cells = []
        for s in summaries.values():
            row = next((r for r in s["rows"] if r["case"] == case), None)
            cells.append(f"{row['outcome']} ({row['tool']})" if row else "")
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    first = next(iter(summaries.values()), None)
    if first:
        lines += [
            "",
            (
                f"Transcript: fixture run of `{first['meta']['scenario']}`. "
                f'System message: "{first["meta"]["system_prompt"]}"'
            ),
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--profile", nargs="+", default=list(DEFAULT_PROFILES))
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    store = ScenarioStore(REPO / "data" / "manifests", REPO, REPO / "data" / "prepared")
    loaded = store.get(args.scenario)
    if loaded is None:
        raise SystemExit(f"unknown scenario {args.scenario!r}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cameras, steps = record_steps(loaded, RUNS_DIR / f"{args.scenario}_{stamp}")
    cases = build_cases(args.scenario, cameras, steps)
    tools = tool_definitions()

    failed = 0
    for name in args.profile:
        endpoint = load_profile(name).reasoning
        rows = []
        for case in cases:
            row = ask(endpoint, case, tools)
            rows.append(row)
            print(json.dumps({"profile": name, **row}), flush=True)
        failed += sum(r["outcome"] == "request_failed" for r in rows)
        meta = {
            "profile": name,
            "model": endpoint.model,
            "scenario": args.scenario,
            "cases": len(cases),
            "system_prompt": SYSTEM_PROMPT,
            "tools_contract": "contracts/tools.schema.json",
            "probed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        doc = summarize_probe(rows, meta=meta)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{name}.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    summaries = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.out.glob("*.json"))
    }
    (args.out / "PROBE.md").write_text(render(summaries), encoding="utf-8", newline="\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

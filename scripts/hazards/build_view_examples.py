"""Rebuild the /hazards contract examples from the real original run.

Input: ``contracts/examples/hazards/source/`` holds verbatim copies of the original
``hazard_report.json`` and ``run_manifest.json`` (Ollama qwen3.6:35b-a3b on macOS,
FastSAM-s, astra-1.1; imported as clip ``hz_00`` "Press line camera"). The prompts come
from the byte-identical script copy under ``third_party/astra_safety_hazard/``.

``source/agent_run/`` holds a real GB10 run that the OpenClaw agent ``urban-mirror`` made
through the review runner seam (clip ``hz_02``, 2026-10-03): its ``hazard_report.json``,
``run_manifest.json``, ``agent_trace.json``, ``agent_summary.json`` and
``job_timeline.json``, copied verbatim from ``data/hazards/reports/hz_02/<run_id>/``.

Output (``contracts/examples/hazards/``): ``hazard_view.json`` (reviewed),
``hazard_view_not_reviewed.json``, ``hazard_view_agent.json`` (agent run, demo replay on),
``clips.json``, ``instructions.json``, ``review_accepted.json``, ``job_latest.json``,
``job_events.json`` (demo replay of the original run), ``job_events_agent.json`` (demo
replay of the agent run, narration included), ``job_events_failed.json`` and ``wall.json``.
``runtime_status.json`` is a captured ``GET /api/runtime/status`` from the GB10 and is not
rebuilt here. Wording comes from ``config/hazards.yaml``, the wall from ``config/wall.yaml``.

Run after the composer or the wording changes::

    .venv/bin/python scripts/hazards/build_view_examples.py

``tests/unit/contracts/test_hazard_view_contract.py`` fails when the examples drift.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.services.hazards import (
    AGENT_RUNNER,
    DIRECT_RUNNER,
    SCRIPT_STEPS,
    compose_view,
    derive_status,
    instruction_extras,
    load_wording,
    plain_narration,
    prompts_from_script,
    recorded_events,
    replay_note,
    replay_schedule,
    summarize_clip,
)
from apps.api.services.wall import compose_wall, load_wall_config

EXAMPLES = REPO_ROOT / "contracts" / "examples" / "hazards"
SOURCE = EXAMPLES / "source"
AGENT_SOURCE = SOURCE / "agent_run"
# Not rebuilt: a captured GET /api/runtime/status (validated against the schema only).
STATIC_EXAMPLES = ("runtime_status.json",)
EXAMPLE_JOB_ID = "hzjob_0123456789ab"
# Judge-only label of the original clip (4_tr1.mp4 from the train split).
EXAMPLE_LABEL = {"dataset_label": "4_safe_walkway"}
# A not-yet-reviewed clip as scripts/hazards/prepare_clips.py describes it (neutral id and
# title; duration of the first test-split clip, 372 frames at 24.83 fps).
NOT_REVIEWED_CLIP = {"clip_id": "hz_01", "title": "Floor camera 01", "duration_s": 14.982}
# The agent run's clip as prepare_clips.py staged it, and its judge-only label.
AGENT_CLIP = {"clip_id": "hz_02", "title": "Floor camera 02", "duration_s": 14.982}
AGENT_LABEL = {"dataset_label": "0_safe_walkway_violation"}
# Blind-spot clips as the warehouse builder stages them (for the wall example).
BLINDSPOT_CLIPS = [
    {"clip_id": f"bs_0{i}", "title": f"Aisle camera {i}", "duration_s": 15.0, "kind": "blindspot"}
    for i in (1, 2, 3)
]


def _load(name: str, folder: Path = SOURCE) -> Any:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def replay_events(
    report: dict[str, Any],
    manifest: dict[str, Any],
    wording: dict[str, Any],
    *,
    clip_id: str,
    run_id: str,
    runner: str,
    trace: Any = None,
    timeline: Any = None,
) -> list[dict[str, Any]]:
    """The SSE events a demo replay of a stored run sends (replay times as t_s)."""
    events, total = recorded_events(
        steps=list(SCRIPT_STEPS), manifest=manifest, trace=trace, timeline=timeline
    )
    schedule, _end = replay_schedule(events, total, wording["demo_replay"])
    steps = wording["steps"]
    out: list[dict[str, Any]] = []
    for item in schedule:
        if item.event == "progress":
            step = int(item.data["step"])
            data = {
                "step": step,
                "total": len(SCRIPT_STEPS),
                "message": item.data["message"],
                "plain_message": steps[step - 1],
                "t_s": item.t_s,
            }
        else:
            text = plain_narration(item.data.get("text"))
            if not text:
                continue
            data = {"text": text, "kind": "say", "t_s": item.t_s}
        out.append({"event": item.event, "data": data})
    done = {
        "clip_id": clip_id,
        "run_id": run_id,
        "reviewed_at": report.get("generated_at_utc"),
        "runner": runner,
        "replay": True,
        "note": replay_note(report, wording),
    }
    return [*out, {"event": "done", "data": done}]


def original_run_id(report: dict[str, Any]) -> str:
    """The script's RUN_ID: sha256 of {source, config, weights}, first 16 hex."""
    key = {
        "source": report["video"]["source_sha256"],
        "config": report["config"],
        "weights": report.get("segmentation_weights_sha256"),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def example_clip(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "clip_id": "hz_00",
        "title": "Press line camera",
        "duration_s": round(float(report["video"]["duration_s"]), 3),
    }


def build() -> dict[str, Any]:
    """Every example document, keyed by file name."""
    wording = load_wording()
    prompts = prompts_from_script()
    report, manifest = _load("hazard_report.json"), _load("run_manifest.json")
    clip = example_clip(report)
    status = derive_status(report)
    view = compose_view(
        clip=clip,
        report=report,
        status=status,
        wording=wording,
        manifest=manifest,
        label=EXAMPLE_LABEL,
        prompts=prompts,
        run_id=original_run_id(report),
    )
    agent_report = _load("hazard_report.json", AGENT_SOURCE)
    agent_manifest = _load("run_manifest.json", AGENT_SOURCE)
    agent_trace = _load("agent_trace.json", AGENT_SOURCE)
    agent_summary = _load("agent_summary.json", AGENT_SOURCE)
    agent_timeline = _load("job_timeline.json", AGENT_SOURCE)
    agent_run_id = agent_report["pipeline"]["run_id"]
    agent_view = compose_view(
        clip=AGENT_CLIP,
        report=agent_report,
        status=derive_status(agent_report),
        wording=wording,
        manifest=agent_manifest,
        label=AGENT_LABEL,
        prompts=prompts,
        run_id=agent_run_id,
        runner=AGENT_RUNNER,
        agent_trace=agent_trace,
        agent_summary=agent_summary,
        replay=True,
    )
    not_reviewed = compose_view(
        clip=NOT_REVIEWED_CLIP,
        report=None,
        status="not_reviewed",
        wording=wording,
        prompts=prompts,
        has_processed=False,
    )
    events = replay_events(
        report,
        manifest,
        wording,
        clip_id=clip["clip_id"],
        run_id=original_run_id(report),
        runner=DIRECT_RUNNER,
    )
    agent_events = replay_events(
        agent_report,
        agent_manifest,
        wording,
        clip_id=AGENT_CLIP["clip_id"],
        run_id=agent_run_id,
        runner=AGENT_RUNNER,
        trace=agent_trace,
        timeline=agent_timeline,
    )
    progress = [e for e in events if e["event"] == "progress"]
    events_url = f"/api/hazards/jobs/{EXAMPLE_JOB_ID}/events"
    hazard_clips = [
        dict(clip, kind="hazard"),
        dict(NOT_REVIEWED_CLIP, kind="hazard"),
        dict(AGENT_CLIP, kind="hazard"),
    ]
    return {
        "hazard_view.json": view,
        "hazard_view_not_reviewed.json": not_reviewed,
        "hazard_view_agent.json": agent_view,
        "clips.json": {
            "clips": [
                summarize_clip(clip, report, status),
                summarize_clip(NOT_REVIEWED_CLIP, None, "not_reviewed"),
                summarize_clip(AGENT_CLIP, agent_report, derive_status(agent_report)),
            ]
        },
        "instructions.json": {
            "checks": list(wording["checks"]),
            "rules": list(wording["rules"]),
            **prompts,
            **instruction_extras(),
        },
        "review_accepted.json": {
            "job_id": EXAMPLE_JOB_ID,
            "events_url": events_url,
            "mode": "replay",
            "runner": AGENT_RUNNER,
        },
        "job_latest.json": {
            "job_id": EXAMPLE_JOB_ID,
            "clip_id": AGENT_CLIP["clip_id"],
            "state": "done",
            "mode": "replay",
            "runner": AGENT_RUNNER,
            "started_at": agent_timeline["started_at_utc"],
            "events_url": events_url,
        },
        "job_events.json": events,
        "job_events_agent.json": agent_events,
        "job_events_failed.json": [
            *progress[:4],
            {"event": "failed", "data": {"plain_message": wording["messages"]["model_failed"]}},
        ],
        "wall.json": compose_wall([*hazard_clips, *BLINDSPOT_CLIPS], load_wall_config()),
    }


def dump(doc: Any) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for name, doc in build().items():
        assert name not in STATIC_EXAMPLES
        (EXAMPLES / name).write_text(dump(doc), encoding="utf-8")
        print(f"wrote {(EXAMPLES / name).relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

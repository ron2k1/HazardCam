#!/usr/bin/env python3
"""Record real model outputs as per-scenario fixtures for fixture mode.

Runs the NON-AGENT dev harness with a live profile (default ``lite-local``) on prepared
scenarios and writes, per scenario, under ``data/fixtures/<scenario_id>/``:

  qwen_observations.json  camera_id -> ObservationBatch, the perception model's output
  final_hypothesis.json   the reasoning model's raw hypothesis, before the submit gate
  provenance.json         profile, models, commit, time, adapter calls and outcome

Fixture mode replays these through the same deterministic fusion and submit gate, so a
fixture run shows what the real models produced on that scenario. Nothing here is
hand-written. A scenario with a failed adapter call is reported and not written unless
``--allow-degraded``.

  python scripts/record_fixtures.py --scenario scenario_001
  python scripts/record_fixtures.py --all --profile lite-local
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from apps.api.schemas import Scenario
from apps.api.services.gt_guard import GtGuard
from apps.api.services.scenarios import ScenarioStore
from harness.dev_sequence import DevSequenceResult, run_dev_sequence_detailed
from inference.profiles import ModelProfile, load_profile
from tools.session import ToolCallError

FIXTURES_DIR = REPO / "data" / "fixtures"
RUNS_DIR = REPO / "data" / "runs" / "record"
PROVENANCE_FILE = "provenance.json"
SOURCE_NOTE = "Real model outputs on real MEVA KF1 video (CC BY 4.0). Not hand-written."


def _fixture_names() -> tuple[str, str]:
    """The file names fixture mode looks up, taken from the fixture profile itself."""
    fixture = load_profile("fixture")
    paths = (fixture.perception.fixture, fixture.reasoning.fixture)
    if not all(paths):
        raise SystemExit("the fixture profile names no fixture files")
    return Path(paths[0]).name, Path(paths[1]).name


def _git_commit() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    done = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or None


def _summary(h: Any) -> dict[str, Any]:
    return {"event_type": h.event_type, "region": h.region, "confidence": h.confidence}


def _documents(result: DevSequenceResult, profile: ModelProfile) -> dict[str, Any]:
    observations_name, hypothesis_name = _fixture_names()
    return {
        observations_name: {b.camera_id: b.model_dump(mode="json") for b in result.batches},
        hypothesis_name: result.raw_hypothesis.model_dump(mode="json"),
        PROVENANCE_FILE: {
            "source": SOURCE_NOTE,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "profile": profile.profile,
            "perception_model": profile.perception.model,
            "reasoning_model": profile.reasoning.model,
            "media": profile.media.model_dump(mode="json"),
            "duration_ms": result.duration_ms,
            "bundle_status": result.bundle.status,
            "raw_hypothesis": _summary(result.raw_hypothesis),
            "submitted_hypothesis": _summary(result.hypothesis),
            "adapter_calls": result.adapter_calls,
        },
    }


def record(
    scenario: Scenario, profile: ModelProfile, out_dir: Path, *, allow_degraded: bool
) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    guard = GtGuard.for_scenario(scenario)
    scenario_id = scenario.id
    try:
        result = run_dev_sequence_detailed(
            scenario,
            profile,
            lambda _type, _payload: None,
            run_dir=RUNS_DIR / f"{scenario_id}_{stamp}",
            media_root=REPO,
        )
    except ToolCallError as exc:
        return {
            "scenario_id": scenario_id,
            "status": "failed",
            "stage": exc.stage,
            "error": str(exc),
        }

    failed = [c for c in result.adapter_calls if not c["ok"]]
    outcome = {
        "scenario_id": scenario_id,
        "status": "degraded" if failed else "recorded",
        "observations": sum(len(b.observations) for b in result.batches),
        "raw": _summary(result.raw_hypothesis),
        "submitted": _summary(result.hypothesis),
        "seconds": round(result.duration_ms / 1000, 1),
        "failed_calls": [f"{c['role']}:{c.get('camera_id') or '-'}: {c['error']}" for c in failed],
    }
    if failed and not allow_degraded:
        outcome["written"] = False
        return outcome

    texts = {
        name: json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        for name, doc in _documents(result, profile).items()
    }
    leaked = sorted(name for name, text in texts.items() if guard.leaks(text))
    if leaked:
        raise SystemExit(f"{scenario_id}: refusing to write; ground truth referenced in {leaked}")
    target = out_dir / scenario_id
    target.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    outcome["written"] = True
    return outcome


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--scenario", nargs="+", metavar="ID", help="scenario ids to record")
    which.add_argument("--all", action="store_true", help="every scenario in data/manifests")
    ap.add_argument(
        "--profile", default="lite-local", help="live model profile (default lite-local)"
    )
    ap.add_argument("--out", type=Path, default=FIXTURES_DIR, help="fixtures root")
    ap.add_argument("--allow-degraded", action="store_true", help="write despite failed calls")
    args = ap.parse_args()

    profile = load_profile(args.profile)
    if profile.perception.backend == "fixture" or profile.reasoning.backend == "fixture":
        raise SystemExit(f"profile {args.profile!r} replays fixtures; record from a live profile")
    store = ScenarioStore(REPO / "data" / "manifests", REPO, REPO / "data" / "prepared")
    loaded = {s.scenario.id: s.scenario for s in store.list()}
    ids = sorted(loaded) if args.all else args.scenario
    unknown = [i for i in ids if i not in loaded]
    if unknown:
        raise SystemExit(f"unknown scenario ids: {unknown}")

    outcomes = []
    for scenario_id in ids:
        outcome = record(loaded[scenario_id], profile, args.out, allow_degraded=args.allow_degraded)
        outcomes.append(outcome)
        print(json.dumps(outcome, ensure_ascii=False), flush=True)
    return 0 if all(o["status"] == "recorded" for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())

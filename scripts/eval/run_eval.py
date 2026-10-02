#!/usr/bin/env python3
"""Run the NON-AGENT dev harness over an eval manifest and score it (``eval/SCORING.md``).

  python scripts/eval/run_eval.py --profile fixture
  MODEL_PROFILE=lite-local python scripts/eval/run_eval.py --manifest data/eval/manifest.json
  python scripts/eval/run_eval.py --profile full-local --scenario scenario_001 eval_007

Writes ``<out>/<profile>/scenarios.json``, ``summary.json`` and ``SUMMARY.md``, then
rebuilds ``<out>/summary.json`` and ``<out>/COMPARISON.md`` from every profile scored so
far. Headline verdicts are defined over the whole manifest, so a ``--scenario`` subset
goes to ``<out>/subsets/<profile>/`` with no baseline verdict and never enters the index.
A scenario's judge-only ``expected.json`` is read only after its run has returned.
In fixture mode each scenario must have its own recording (``scripts/record_fixtures.py``);
the shared example fixtures are never replayed onto a real scenario.

Exit status is 0 when the pipeline held (every run completed, schema-valid, no GT leak)
and, in fixture mode, every replay reproduced its recording, whatever the accuracy.
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from apps.api.services.scenarios import LoadedScenario, ScenarioStore
from eval.scoring import ScenarioScore, score_run
from eval.summary import (
    comparison,
    constant_baselines,
    render_comparison,
    render_markdown,
    scores_json,
    summarize,
)
from harness.dev_sequence import DevSequenceResult, run_dev_sequence_detailed
from inference.profiles import ModelProfile, load_profile
from tools.session import ToolCallError

MANIFEST = REPO / "data" / "eval" / "manifest.json"
OUT = REPO / "artifacts" / "eval"
RUNS_DIR = REPO / "data" / "runs" / "eval"
SUBSETS_DIR = "subsets"
PROVENANCE_FILE = "provenance.json"
SUMMARY_KEYS = ("event_type", "region", "confidence")


def _git_commit() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    done = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or None


def _is_fixture(profile: ModelProfile) -> bool:
    return profile.perception.backend == "fixture" or profile.reasoning.backend == "fixture"


def _recording_dir(profile: ModelProfile, scenario_id: str) -> Path | None:
    fixture_dir = profile.reasoning.fixture_dir or profile.perception.fixture_dir
    return REPO / fixture_dir / scenario_id if fixture_dir else None


def _missing_recordings(profile: ModelProfile, scenario_id: str) -> list[str]:
    """Fixture files that would fall back to the shared example instead of this scenario."""
    missing = []
    for endpoint in (profile.perception, profile.reasoning):
        if endpoint.backend != "fixture":
            continue
        path = endpoint.fixture_path(scenario_id)
        if path is None or path.parent.name != scenario_id:
            missing.append(Path(endpoint.fixture or "?").name)
    return missing


def _provenance(profile: ModelProfile, scenario_id: str) -> dict[str, Any] | None:
    folder = _recording_dir(profile, scenario_id)
    path = folder / PROVENANCE_FILE if folder else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None


def _replay_match(
    profile: ModelProfile, scenario_id: str, result: DevSequenceResult | None
) -> bool | None:
    """In fixture mode: does replay reproduce the submitted hypothesis that was recorded?"""
    provenance = _provenance(profile, scenario_id) if _is_fixture(profile) else None
    if provenance is None or result is None:
        return None
    replayed = {k: getattr(result.hypothesis, k) for k in SUMMARY_KEYS}
    return replayed == {k: provenance["submitted_hypothesis"][k] for k in SUMMARY_KEYS}


def run_one(
    loaded: LoadedScenario, profile: ModelProfile, store: ScenarioStore, stamp: str
) -> ScenarioScore:
    scenario, guard = loaded.scenario, loaded.guard
    leaks = 0

    def emit(_event_type: str, payload: dict[str, Any]) -> None:
        nonlocal leaks
        if guard.leaks(json.dumps(payload, ensure_ascii=False, default=str)):
            leaks += 1

    result: DevSequenceResult | None = None
    error: str | None = None
    missing = _missing_recordings(profile, scenario.id) if _is_fixture(profile) else []
    if missing:
        error = f"no recording for this scenario ({', '.join(missing)}); run record_fixtures.py"
    else:
        try:
            result = run_dev_sequence_detailed(
                scenario,
                profile,
                emit,
                run_dir=RUNS_DIR / profile.profile / f"{scenario.id}_{stamp}",
                media_root=REPO,
            )
        except ToolCallError as exc:
            error = f"{exc.stage}: {exc}"
    # Judge-only labels, read after the run has returned.
    expected = json.loads(store.expected_path(scenario.id).read_text(encoding="utf-8"))
    return score_run(
        expected,
        result,
        error=error,
        gt_leaks=leaks,
        replay_match=_replay_match(profile, scenario.id, result),
    )


def _models(profile: ModelProfile, ids: list[str]) -> dict[str, Any]:
    if not _is_fixture(profile):
        return {
            "perception_model": profile.perception.model,
            "reasoning_model": profile.reasoning.model,
        }
    recordings = [p for p in (_provenance(profile, i) for i in ids) if p]
    replayed = sorted(
        {(p["profile"], p["perception_model"], p["reasoning_model"]) for p in recordings}
    )
    return {
        "perception_model": "replay: " + ", ".join(m[1] for m in replayed),
        "reasoning_model": "replay: " + ", ".join(m[2] for m in replayed),
        "replays_profiles": [m[0] for m in replayed],
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _dump(doc: Any) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=True) + "\n"


def rebuild_index(out: Path, manifest_ids: list[str], store: ScenarioStore) -> None:
    summaries = {
        p.parent.name: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(out.glob("*/summary.json"))
    }
    expected = [
        json.loads(store.expected_path(i).read_text(encoding="utf-8")) for i in manifest_ids
    ]
    baselines = constant_baselines(expected)
    table = comparison(summaries)
    index = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scoring_rules": "eval/SCORING.md",
        "manifest_scenarios": len(manifest_ids),
        "best_constant_baselines": baselines["best"],
        "profiles": table,
    }
    _write(out / "summary.json", _dump(index))
    _write(out / "COMPARISON.md", render_comparison(table, baselines))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--profile", help="model profile (default: $MODEL_PROFILE, else fixture)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST, help="eval manifest")
    ap.add_argument("--scenario", nargs="+", metavar="ID", help="score only these scenarios")
    ap.add_argument("--out", type=Path, default=OUT, help="artifacts root")
    args = ap.parse_args()

    profile = load_profile(args.profile)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_ids: list[str] = manifest["scenarios"]
    ids = args.scenario or manifest_ids
    subset = sorted(ids) != sorted(manifest_ids)
    store = ScenarioStore(REPO / "data" / "manifests", REPO, REPO / "data" / "prepared")
    loaded = {s.scenario.id: s for s in store.list()}
    unknown = [i for i in ids if i not in loaded or i not in manifest_ids]
    if unknown:
        raise SystemExit(f"not in the manifest or not prepared: {unknown}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    scores = []
    for scenario_id in ids:
        score = run_one(loaded[scenario_id], profile, store, stamp)
        scores.append(score)
        line = {
            "scenario_id": scenario_id,
            "outcome": score.outcome,
            "class_ok": score.class_ok,
            "event_type": score.event_type,
            "region_ok": score.region_ok,
            "seconds": round((score.duration_ms or 0) / 1000, 1),
            "error": score.error,
        }
        print(json.dumps(line), flush=True)

    expected_by_id = {
        i: json.loads(store.expected_path(i).read_text(encoding="utf-8")) for i in ids
    }
    meta = {
        "profile": profile.profile,
        "mode": profile.mode,
        **_models(profile, ids),
        "media": profile.media.model_dump(mode="json"),
        "git_commit": _git_commit(),
        "scored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "manifest": manifest.get("name"),
        "scenarios": ids,
        "subset_of_manifest": subset,
        "scoring_rules": "eval/SCORING.md",
    }
    summary = summarize(scores, expected_by_id, meta=meta, full_manifest=not subset)
    folder = args.out / SUBSETS_DIR / profile.profile if subset else args.out / profile.profile
    _write(folder / "scenarios.json", _dump(scores_json(scores)))
    _write(folder / "summary.json", _dump(summary))
    _write(folder / "SUMMARY.md", render_markdown(summary))
    if not subset:
        rebuild_index(args.out, manifest_ids, store)
    print(json.dumps({"summary": str(folder / "summary.json"), "verdict": summary["verdict"]}))
    # SCORING.md: a fixture replay mismatch is a bug. It fails the run, not a verdict flag.
    mismatches = summary["system"]["replay_mismatches"] or 0
    return 0 if summary["verdict"]["pipeline_ok"] and not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())

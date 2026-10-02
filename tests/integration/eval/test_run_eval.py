"""P12: ``scripts/eval/run_eval.py`` end to end in fixture mode on real prepared scenarios.

Subset runs stay out of the headline artifacts, and a fixture replay mismatch fails the run.
Everything is written under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from apps.api.schemas import REPO_ROOT

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(
        not (REPO_ROOT / "data" / "prepared" / "eval_005" / "cam_a.mp4").is_file(),
        reason="prepared MEVA media is not on this machine",
    ),
]

_SPEC = importlib.util.spec_from_file_location(
    "run_eval", REPO_ROOT / "scripts" / "eval" / "run_eval.py"
)
assert _SPEC is not None and _SPEC.loader is not None
run_eval = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_eval)


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "eval"


def _main(monkeypatch, out, *scenarios: str) -> int:
    argv = ["run_eval.py", "--profile", "fixture", "--out", str(out), "--scenario", *scenarios]
    monkeypatch.setattr(sys, "argv", argv)
    return run_eval.main()


def test_a_subset_run_is_kept_apart_and_has_no_baseline_verdict(monkeypatch, out):
    assert _main(monkeypatch, out, "eval_001", "eval_005") == 0
    summary = json.loads((out / "subsets" / "fixture" / "summary.json").read_text("utf-8"))
    assert summary["n"] == 2 and summary["meta"]["subset_of_manifest"] is True
    # Headline verdicts are defined over the whole manifest only (SCORING.md).
    assert summary["verdict"] == {"pipeline_ok": True, "beats_constant_baselines": None}
    assert not (out / "fixture").exists()  # the full-manifest artifacts are untouched
    assert not (out / "summary.json").exists() and not (out / "COMPARISON.md").exists()
    assert "Subset run" in (out / "subsets" / "fixture" / "SUMMARY.md").read_text("utf-8")


def test_a_fixture_replay_mismatch_fails_the_run(monkeypatch, out):
    monkeypatch.setattr(run_eval, "_replay_match", lambda *_: False)
    assert _main(monkeypatch, out, "eval_005") == 1
    summary = json.loads((out / "subsets" / "fixture" / "summary.json").read_text("utf-8"))
    assert summary["system"]["replay_mismatches"] == 1
    assert summary["verdict"]["pipeline_ok"] is True  # a bug, not a verdict flag

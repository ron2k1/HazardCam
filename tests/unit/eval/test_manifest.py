"""P12: the eval manifest names every prepared scenario, and each has judge-only labels."""

from __future__ import annotations

import json

from apps.api.schemas import REPO_ROOT

MANIFEST = json.loads((REPO_ROOT / "data" / "eval" / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_lists_every_prepared_scenario_once():
    ids = MANIFEST["scenarios"]
    prepared = sorted(p.stem for p in (REPO_ROOT / "data" / "manifests").glob("*.json"))
    assert ids == sorted(set(ids)) == prepared


def test_every_manifest_scenario_has_labels_and_a_recording():
    for scenario_id in MANIFEST["scenarios"]:
        assert (REPO_ROOT / "data" / "prepared" / scenario_id / "expected.json").is_file()
        recording = REPO_ROOT / "data" / "fixtures" / scenario_id
        for name in ("qwen_observations.json", "final_hypothesis.json", "provenance.json"):
            assert (recording / name).is_file(), (scenario_id, name)


def test_manifest_points_at_the_preregistered_rules():
    assert (REPO_ROOT / MANIFEST["scoring"]).is_file()

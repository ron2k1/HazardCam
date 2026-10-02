"""P03: env-driven settings and the ground-truth token guard."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from apps.api.schemas import REPO_ROOT
from apps.api.services.gt_guard import REDACTED, GtGuard, ground_truth_tokens
from apps.api.settings import DEFAULT_CORS_ORIGINS, Settings

ENV_VARS = (
    "AUM_MANIFESTS_DIR",
    "AUM_PREPARED_DIR",
    "AUM_RUNS_DIR",
    "AUM_MEDIA_ROOT",
    "AUM_MODELS_DIR",
    "MODEL_PROFILE",
    "AUM_CORS_ORIGINS",
    "AUM_DEFAULT_PACE_S",
    "AUM_SSE_PING_S",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_defaults_anchor_to_repo_root(clean_env):
    s = Settings.from_env()
    assert s.manifests_dir == (REPO_ROOT / "data" / "manifests").resolve()
    assert s.prepared_dir == (REPO_ROOT / "data" / "prepared").resolve()
    assert s.runs_dir == (REPO_ROOT / "data" / "runs").resolve()
    assert s.models_dir == (REPO_ROOT / "config" / "models").resolve()
    assert s.media_root == REPO_ROOT.resolve()
    assert s.model_profile == "fixture"
    assert s.cors_origins == list(DEFAULT_CORS_ORIGINS)
    assert s.default_pace_s == 0.0


def test_env_overrides(clean_env, tmp_path):
    clean_env.setenv("AUM_RUNS_DIR", str(tmp_path / "runs"))
    clean_env.setenv("AUM_MANIFESTS_DIR", "some/relative")
    clean_env.setenv("MODEL_PROFILE", "lite-local")
    clean_env.setenv("AUM_CORS_ORIGINS", "http://a:1, http://b:2 ,")
    clean_env.setenv("AUM_DEFAULT_PACE_S", "0.4")
    s = Settings.from_env()
    assert s.runs_dir == tmp_path / "runs"
    assert s.manifests_dir == (REPO_ROOT / "some" / "relative").resolve()
    assert s.model_profile == "lite-local"
    assert s.cors_origins == ["http://a:1", "http://b:2"]
    assert s.default_pace_s == 0.4


@pytest.mark.parametrize("name", ["../x", "a/b", ".hidden", "", "a\\b"])
def test_unsafe_profile_names_rejected(clean_env, name):
    with pytest.raises(ValidationError):
        Settings(model_profile=name)
    assert Settings().profile_config(name) is None


def test_profile_config_resolves_existing_yaml_only(clean_env):
    s = Settings()
    assert s.profile_config("fixture") == s.models_dir / "fixture.yaml"
    assert s.profile_config("does-not-exist") is None


def test_tokens_cover_id_path_and_basename(scenario):
    assert set(ground_truth_tokens(scenario)) == {
        "cam_gt",
        "data/prepared/scenario_001/hidden_ground_truth.mp4",
        "hidden_ground_truth.mp4",
    }


@pytest.mark.parametrize(
    "text",
    [
        '{"camera_id": "cam_gt"}',
        "camera 'cam_gt' is withheld",
        "see data/prepared/scenario_001/hidden_ground_truth.mp4",
        r"C:\repo\data\prepared\scenario_001\hidden_ground_truth.mp4",
        json.dumps({"p": r"C:\repo\hidden_ground_truth.mp4"}),
        "cam_gt.",
    ],
)
def test_guard_detects_leaks(scenario, text):
    guard = GtGuard.for_scenario(scenario)
    assert guard.leaks(text)
    assert not any(t in guard.redact(text) for t in ("cam_gt", "hidden_ground_truth.mp4"))


@pytest.mark.parametrize("text", ["cam_01", "cam_gt2", "my_cam_gt", "cam-gt", "scam_gtx", ""])
def test_guard_matches_whole_identifiers_only(scenario, text):
    assert not GtGuard.for_scenario(scenario).leaks(text)


def test_short_gt_id_does_not_match_longer_visible_ids():
    guard = GtGuard(("cam_0",))
    assert not guard.leaks('{"camera_ids": ["cam_01", "cam_02"]}')
    assert guard.leaks('{"camera_id": "cam_0"}')


def test_redact_obj_walks_nested_structures(scenario):
    guard = GtGuard.for_scenario(scenario)
    out = guard.redact_obj({"a": ["x cam_gt y", {"b": "hidden_ground_truth.mp4"}], "n": 3})
    assert out == {"a": [f"x {REDACTED} y", {"b": REDACTED}], "n": 3}


def test_empty_guard_is_inert():
    guard = GtGuard(())
    assert not guard.leaks("anything") and guard.redact("anything") == "anything"

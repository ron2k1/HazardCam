"""P06: profiles load and validate, env overrides, placeholder gating, no secrets."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from inference.profiles import (
    PROFILES_DIR,
    EndpointConfig,
    ModelProfile,
    ProfileError,
    list_profiles,
    load_profile,
)

EXPECTED = {"fixture", "lite-local", "full-local", "remote16gb", "gb10"}


def test_all_expected_profiles_exist():
    assert EXPECTED <= set(list_profiles())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_profile_parses_with_both_roles(name):
    profile = load_profile(name, env={}, require_resolved=False)
    assert profile.profile == name
    for ep in (profile.perception, profile.reasoning):
        assert ep.backend in ("fixture", "openai_compatible")
    assert profile.media.max_frames_per_camera >= 1


def test_default_is_fixture_then_model_profile_env():
    assert load_profile(env={}).profile == "fixture"
    assert load_profile(env={"MODEL_PROFILE": "lite-local"}).profile == "lite-local"
    assert load_profile("fixture", env={"MODEL_PROFILE": "lite-local"}).profile == "fixture"


def test_lite_local_targets_ollama_with_explicit_thinking_off():
    p = load_profile("lite-local", env={})
    assert p.perception.base_url == p.reasoning.base_url == "http://127.0.0.1:11434/v1"
    assert (p.perception.model, p.reasoning.model) == ("qwen3-vl:4b-instruct", "ministral-3:3b")
    assert p.perception.think is False and p.reasoning.think is False
    assert p.perception.context_tokens == 4096 and p.perception.max_image_width == 512


def test_full_local_is_closest_practical_pair():
    p = load_profile("full-local", env={})
    assert (p.perception.model, p.reasoning.model) == ("qwen3.5:9b", "ministral-3:8b")
    assert p.perception.think is False  # hybrid-thinking model: must be explicit
    assert "35B" in (p.notes or "") or "35b" in (p.notes or "")


def test_env_overrides_apply_to_openai_endpoints():
    env = {
        "QWEN_BASE_URL": "http://10.0.0.5:9000/v1",
        "QWEN_MODEL": "qwen-x",
        "MISTRAL_BASE_URL": "http://10.0.0.6:9001/v1",
        "MISTRAL_MODEL": "mistral-y",
    }
    p = load_profile("lite-local", env=env)
    assert (p.perception.base_url, p.perception.model) == ("http://10.0.0.5:9000/v1", "qwen-x")
    assert (p.reasoning.base_url, p.reasoning.model) == ("http://10.0.0.6:9001/v1", "mistral-y")


def test_env_overrides_ignore_fixture_backend_and_blank_values():
    p = load_profile("fixture", env={"QWEN_BASE_URL": "http://x/v1", "QWEN_MODEL": "q"})
    assert p.perception.base_url is None and p.perception.model is None
    p = load_profile("lite-local", env={"QWEN_MODEL": "   "})
    assert p.perception.model == "qwen3-vl:4b-instruct"


def test_unknown_profile_is_a_clear_error():
    with pytest.raises(ProfileError, match="unknown model profile 'nope'.*available"):
        load_profile("nope", env={})


@pytest.mark.parametrize("bad", ["../secrets", "a/b", "UPPER", "..\\x"])
def test_profile_names_cannot_escape_the_config_dir(bad):
    with pytest.raises(ProfileError, match="invalid profile name"):
        load_profile(bad, env={})


def test_gb10_is_filled_on_event_day():
    # Filled from the live GB10 on 2026-10-03 (D02): selecting it needs no overrides.
    p = load_profile("gb10", env={})
    assert p.placeholders() == []
    assert p.perception.base_url == p.reasoning.base_url == "http://127.0.0.1:8000/v1"


def test_gb10_resolves_once_models_are_overridden():
    p = load_profile("gb10", env={"QWEN_MODEL": "Qwen/Qwen3-VL-30B", "MISTRAL_MODEL": "mistral-s"})
    assert p.perception.think_param == "chat_template_kwargs"
    assert p.placeholders() == []


def test_remote16gb_needs_base_urls_from_env():
    with pytest.raises(ProfileError, match="base_url"):
        load_profile("remote16gb", env={})
    env = {"QWEN_BASE_URL": "http://pc:11434/v1", "MISTRAL_BASE_URL": "http://pc:11434/v1"}
    assert load_profile("remote16gb", env=env).perception.base_url == "http://pc:11434/v1"


def test_unselected_profiles_may_keep_placeholders():
    assert load_profile("remote16gb", env={}, require_resolved=False).placeholders()


# --- secrets ----------------------------------------------------------------------------

_KEYLIKE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|nvapi-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}"
    r"|Bearer\s+\S+|AKIA[0-9A-Z]{12,})"
)


@pytest.mark.parametrize("path", sorted(PROFILES_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_no_profile_contains_key_like_values(path):
    text = path.read_text(encoding="utf-8")
    assert not _KEYLIKE.search(text)
    assert not re.search(
        r"^\s*(api_key|token|password|secret)\s*:", text, re.MULTILINE | re.IGNORECASE
    )


def test_profiles_reject_inline_keys():
    base = {"profile": "x", "mode": "local", "reasoning": {"backend": "fixture", "fixture": "f"}}
    with pytest.raises(ValidationError):
        ModelProfile.model_validate(
            {**base, "perception": {"backend": "openai_compatible", "api_key": "sk-abc"}}
        )
    with pytest.raises(ValidationError, match="NAME"):
        EndpointConfig(backend="openai_compatible", api_key_env="sk-abcdef123456")


def test_api_key_is_read_from_named_env_at_call_time():
    ep = EndpointConfig(backend="openai_compatible", api_key_env="NIM_API_KEY")
    assert ep.api_key({}) is None
    assert ep.api_key({"NIM_API_KEY": "k123"}) == "k123"
    assert "k123" not in ep.model_dump_json()


def test_extra_body_cannot_override_core_fields():
    with pytest.raises(ValidationError, match="extra_body"):
        EndpointConfig(backend="openai_compatible", extra_body={"model": "other"})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        EndpointConfig(backend="openai_compatible", base_ulr="typo")


# --- fixture paths ----------------------------------------------------------------------


def test_per_scenario_fixture_wins_when_present(tmp_path):
    (tmp_path / "scenario_009").mkdir()
    shared = tmp_path / "qwen_observations.json"
    shared.write_text("{}", encoding="utf-8")
    per = tmp_path / "scenario_009" / "qwen_observations.json"
    per.write_text("{}", encoding="utf-8")
    ep = EndpointConfig(backend="fixture", fixture=str(shared), fixture_dir=str(tmp_path))
    assert ep.fixture_path("scenario_009") == per
    assert ep.fixture_path("scenario_other") == shared
    assert ep.fixture_path(None) == shared

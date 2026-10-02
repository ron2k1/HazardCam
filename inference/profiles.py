"""Model profiles: which backend, endpoint, checkpoint and sampling each mode uses.

A profile is ``config/models/<name>.yaml``. The app never branches on hardware; it loads
a profile and hands it to the adapter factories in :mod:`inference.base`.

Secrets never live in a profile. An endpoint that needs a key names the environment
variable that holds it (``api_key_env``); the value is read only at request time.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apps.api.schemas import REPO_ROOT

PROFILES_DIR = REPO_ROOT / "config" / "models"
DEFAULT_PROFILE = "fixture"
PLACEHOLDER_MARK = "REPLACE"

# env var -> (endpoint section, field). Applied to openai_compatible endpoints only.
ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "QWEN_BASE_URL": ("perception", "base_url"),
    "QWEN_MODEL": ("perception", "model"),
    "MISTRAL_BASE_URL": ("reasoning", "base_url"),
    "MISTRAL_MODEL": ("reasoning", "model"),
}

_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

Backend = Literal["fixture", "openai_compatible"]
# How the explicit thinking toggle is spelled on the wire:
#   reasoning_effort      Ollama /v1 ("none" disables; verified on Ollama 0.22.1)
#   chat_template_kwargs  vLLM / SGLang Qwen templates ({"enable_thinking": bool})
#   none                  never send a thinking field
ThinkParam = Literal["reasoning_effort", "chat_template_kwargs", "none"]
StructuredOutput = Literal["json_schema", "json_object", "none"]


class ProfileError(ValueError):
    """A profile is unknown, malformed, or selected while still holding placeholders."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EndpointConfig(_Strict):
    backend: Backend
    # fixture backend
    fixture: str | None = None
    fixture_dir: str | None = None
    # openai_compatible backend
    base_url: str | None = None
    model: str | None = None
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_tokens: int = Field(default=1024, ge=16)
    temperature: float = Field(default=0.0, ge=0, le=2)
    retries: int = Field(default=2, ge=0, le=10)
    think: bool | None = None
    think_param: ThinkParam = "reasoning_effort"
    structured_output: StructuredOutput = "json_schema"
    api_key_env: str | None = None
    quantization: str | None = None
    context_tokens: int | None = Field(default=None, ge=256)
    max_image_width: int | None = Field(default=None, ge=64)
    image_token_px: int = Field(default=32, ge=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key_env")
    @classmethod
    def _env_name_only(cls, v: str | None) -> str | None:
        if v is not None and not _ENV_NAME.match(v):
            raise ValueError("api_key_env must be an environment variable NAME, not a value")
        return v

    @field_validator("extra_body")
    @classmethod
    def _no_core_overrides(cls, v: dict[str, Any]) -> dict[str, Any]:
        clash = {"model", "messages", "stream"} & set(v)
        if clash:
            raise ValueError(f"extra_body may not override {sorted(clash)}")
        return v

    def api_key(self, env: Mapping[str, str] | None = None) -> str | None:
        """The key from the named env var at call time; never stored on the profile."""
        if not self.api_key_env:
            return None
        return (env if env is not None else os.environ).get(self.api_key_env) or None

    def fixture_path(self, scenario_id: str | None) -> Path | None:
        """Per-scenario fixture when present, else the profile-wide fixture file."""
        default = _repo_path(self.fixture) if self.fixture else None
        if scenario_id and self.fixture_dir and default is not None:
            per_scenario = _repo_path(self.fixture_dir) / scenario_id / default.name
            if per_scenario.is_file():
                return per_scenario
        return default


class MediaConfig(_Strict):
    sample_fps: float = Field(default=1.0, gt=0)
    max_frames_per_camera: int = Field(default=8, ge=1)
    max_width: int = Field(default=768, ge=64)
    concurrency: int = Field(default=1, ge=1)


class ModelProfile(_Strict):
    profile: str
    mode: str
    notes: str | None = None
    perception: EndpointConfig
    reasoning: EndpointConfig
    media: MediaConfig = Field(default_factory=MediaConfig)

    def placeholders(self) -> list[str]:
        """Dotted paths of every still-unfilled ``REPLACE*`` value."""
        found: list[str] = []
        for section in ("perception", "reasoning"):
            dumped = getattr(self, section).model_dump()
            for key, value in dumped.items():
                if isinstance(value, str) and PLACEHOLDER_MARK in value:
                    found.append(f"{section}.{key}")
        return found


def _repo_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def load_profile(
    name: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    require_resolved: bool = True,
) -> ModelProfile:
    """Load ``config/models/<name>.yaml`` and apply env overrides.

    ``name`` defaults to ``$MODEL_PROFILE``, else ``fixture``. With ``require_resolved``
    (the default, i.e. this profile is being *selected*), any remaining ``REPLACE*``
    placeholder or a missing endpoint URL/model raises :class:`ProfileError`.
    """
    env = os.environ if env is None else env
    name = name or env.get("MODEL_PROFILE") or DEFAULT_PROFILE
    if not _PROFILE_NAME.match(name):
        raise ProfileError(f"invalid profile name {name!r}")
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file():
        raise ProfileError(f"unknown model profile {name!r}; available: {list_profiles()}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"profile {name!r} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {name!r} must be a mapping")
    if raw.get("profile", name) != name:
        raise ProfileError(f"profile file {path.name} declares profile {raw.get('profile')!r}")

    for var, (section, field) in ENV_OVERRIDES.items():
        value = (env.get(var) or "").strip()
        block = raw.get(section)
        if value and isinstance(block, dict) and block.get("backend") == "openai_compatible":
            block[field] = value

    try:
        profile = ModelProfile.model_validate(raw)
    except ValidationError as exc:
        raise ProfileError(f"profile {name!r} is invalid: {exc}") from exc

    if require_resolved:
        _require_resolved(profile)
    return profile


def _require_resolved(profile: ModelProfile) -> None:
    problems = [f"{p} is a placeholder" for p in profile.placeholders()]
    for section in ("perception", "reasoning"):
        ep: EndpointConfig = getattr(profile, section)
        if ep.backend == "openai_compatible":
            if not ep.base_url or not ep.base_url.startswith(("http://", "https://")):
                problems.append(f"{section}.base_url must be an http(s) URL")
            if not ep.model:
                problems.append(f"{section}.model is required")
        elif ep.fixture_path(None) is None:
            problems.append(f"{section}.fixture is required for the fixture backend")
    if problems:
        hint = "fill the profile or set QWEN_/MISTRAL_ BASE_URL/MODEL env overrides"
        raise ProfileError(f"profile {profile.profile!r} cannot be selected: {problems} ({hint})")

"""Environment-driven API settings. Relative paths resolve against the repo root."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.schemas import REPO_ROOT

DEFAULT_CORS_ORIGINS = ("http://127.0.0.1:3000", "http://localhost:3000")

# Profile names become file names under config/models, so keep them to one safe segment.
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_PATH_ENV = {
    "manifests_dir": "AUM_MANIFESTS_DIR",
    "prepared_dir": "AUM_PREPARED_DIR",
    "runs_dir": "AUM_RUNS_DIR",
    "media_root": "AUM_MEDIA_ROOT",
    "models_dir": "AUM_MODELS_DIR",
    "alerts_config": "AUM_ALERTS_CONFIG",
}


class Settings(BaseModel):
    # Validate defaults too, so the relative defaults below are anchored to REPO_ROOT
    # instead of the process working directory.
    model_config = ConfigDict(validate_default=True)

    manifests_dir: Path = Path("data/manifests")
    prepared_dir: Path = Path("data/prepared")
    runs_dir: Path = Path("data/runs")
    # Scenario camera ``file`` values are resolved against this directory.
    media_root: Path = Path(".")
    models_dir: Path = Path("config/models")
    # Plain-language alert wording (labels, levels, actions, which cues ping).
    alerts_config: Path = Path("config/alerts.yaml")
    model_profile: str = "fixture"
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    default_pace_s: float = Field(default=0.0, ge=0, le=5)
    sse_ping_s: float = Field(default=15.0, gt=0)
    model_probe_timeout_s: float = Field(default=2.0, gt=0)

    @field_validator(
        "manifests_dir", "prepared_dir", "runs_dir", "media_root", "models_dir", "alerts_config"
    )
    @classmethod
    def _anchor_to_repo(cls, value: Path) -> Path:
        value = Path(value).expanduser()
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @field_validator("model_profile")
    @classmethod
    def _profile_name(cls, value: str) -> str:
        if not PROFILE_NAME_RE.match(value):
            raise ValueError(f"invalid profile name {value!r}")
        return value

    @classmethod
    def from_env(cls) -> Settings:
        values: dict[str, object] = {
            field: os.environ[env] for field, env in _PATH_ENV.items() if os.environ.get(env)
        }
        if os.environ.get("MODEL_PROFILE"):
            values["model_profile"] = os.environ["MODEL_PROFILE"]
        if os.environ.get("AUM_CORS_ORIGINS"):
            values["cors_origins"] = [
                o.strip() for o in os.environ["AUM_CORS_ORIGINS"].split(",") if o.strip()
            ]
        if os.environ.get("AUM_DEFAULT_PACE_S"):
            values["default_pace_s"] = float(os.environ["AUM_DEFAULT_PACE_S"])
        if os.environ.get("AUM_SSE_PING_S"):
            values["sse_ping_s"] = float(os.environ["AUM_SSE_PING_S"])
        return cls(**values)

    def profile_config(self, name: str) -> Path | None:
        """Path to ``config/models/<name>.yaml`` if ``name`` is safe and the file exists."""
        if not PROFILE_NAME_RE.match(name):
            return None
        path = self.models_dir / f"{name}.yaml"
        return path if path.is_file() else None

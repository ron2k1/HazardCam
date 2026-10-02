"""Run executor that binds the API to the NON-AGENT dev-sequence harness.

The API calls an executor positionally with a profile *name*; the harness wants a
loaded ``ModelProfile``, the media root and a frame URL builder. On event day the
OpenClaw agent gets its own executor; this one stays as the dev/fallback path.
"""

from __future__ import annotations

from pathlib import Path

from apps.api.schemas import REPO_ROOT, Hypothesis, Scenario
from apps.api.services.media import frame_url
from apps.api.services.runs import Emit
from harness.dev_sequence import run_dev_sequence
from inference.profiles import load_profile


class DevSequenceExecutor:
    def __init__(self, media_root: Path = REPO_ROOT) -> None:
        self.media_root = media_root

    def __call__(
        self, scenario: Scenario, profile_name: str, emit: Emit, run_dir: Path, pace_s: float
    ) -> Hypothesis:
        run_id = run_dir.name
        return run_dev_sequence(
            scenario,
            load_profile(profile_name),
            emit,
            run_dir=run_dir,
            pace_s=pace_s,
            frame_url=lambda camera_id, index: frame_url(run_id, camera_id, index),
            media_root=self.media_root,
        )

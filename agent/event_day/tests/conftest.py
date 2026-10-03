"""Shared setup for the event-day agent policy tests (D00).

Camera media is TEST MEDIA (ffmpeg lavfi ``testsrc2``) written at the contract example
scenario's visible camera paths; the withheld clip is never generated. The fixture
profile reads TEST FIXTURES written per test: the same three cues the harness tests use,
whose bearings cross in ``blind_zone_02``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from apps.api.schemas import REPO_ROOT, Scenario
from inference.profiles import ModelProfile, load_profile

FFMPEG = shutil.which("ffmpeg")
EXAMPLE = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"
CLIP_SECONDS = 4

MakeProfile = Callable[[dict], ModelProfile]


@pytest.fixture(scope="session")
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not on PATH")
    root = tmp_path_factory.mktemp("agent_media")
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for cam in doc["visible_cameras"]:
        out = root / cam["file"]
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=160x90:rate=10:duration={CLIP_SECONDS}",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ],
            check=True,
            timeout=60,
        )
    return root


@pytest.fixture
def scenario() -> Scenario:
    return Scenario.model_validate_json(EXAMPLE.read_bytes())


def _obs(cam: str, oid: str, t0: float, t1: float, direction: str, conf: float, frames):
    return {
        "camera_id": cam,
        "observations": [
            {
                "id": oid,
                "t_start": t0,
                "t_end": t1,
                "cue_type": "vehicle_slowing_or_stopping",
                "description": "test cue",
                "direction": direction,
                "confidence": conf,
                "supporting_frames": frames,
            }
        ],
    }


OBSERVATIONS = {
    "cam_01": _obs("cam_01", "obs_a_001", 1.0, 1.6, "right", 0.84, [1]),
    "cam_02": _obs("cam_02", "obs_b_001", 1.2, 2.0, "west", 0.76, [1, 2]),
    "cam_03": _obs("cam_03", "obs_c_001", 2.1, 3.0, "center_left", 0.79, [2, 3]),
}

CLAIM = {
    "event_type": "vehicle_stop",
    "region": "blind_zone_02",
    "confidence": 0.74,
    "evidence_ids": ["obs_a_001", "obs_b_001", "obs_c_001"],
    "reason": "Three cameras show traffic slowing toward the same core.",
    "alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.39}],
    "limitations": [],
}


@pytest.fixture
def make_profile(tmp_path: Path) -> MakeProfile:
    """The fixture profile with the test cues and ``hypothesis`` as the reasoner's output."""

    def make(hypothesis: dict) -> ModelProfile:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        paths = {
            "perception": fixtures / "qwen_observations.json",
            "reasoning": fixtures / "final_hypothesis.json",
        }
        paths["perception"].write_text(json.dumps(OBSERVATIONS), encoding="utf-8")
        paths["reasoning"].write_text(json.dumps(hypothesis), encoding="utf-8")
        base = load_profile("fixture", env={})
        return base.model_copy(
            update={
                role: getattr(base, role).model_copy(
                    update={"fixture": str(path), "fixture_dir": str(fixtures)}
                )
                for role, path in paths.items()
            }
        )

    return make

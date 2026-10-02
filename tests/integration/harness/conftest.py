"""Shared setup for the harness and tool-session tests.

Camera media is TEST MEDIA (ffmpeg lavfi ``testsrc2``), generated once per session at the
contract example scenario's camera paths. The fixture files written by ``consistent`` are
TEST FIXTURES for plumbing: the same three cues as ``data/fixtures``, with frame indices
inside a 4-frame manifest and the bearings P08 verified to cross in ``blind_zone_02``.
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
CLIP_SECONDS = 4  # 1 fps sampling -> frames at t = 0, 1, 2, 3

MakeProfile = Callable[[dict, dict], ModelProfile]


@pytest.fixture(scope="session")
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not on PATH")
    root = tmp_path_factory.mktemp("harness_media")
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for cam in doc["visible_cameras"]:  # the GT clip is never needed by the harness
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


@pytest.fixture
def make_profile(tmp_path: Path) -> MakeProfile:
    """The fixture profile, pointed at freshly written perception/reasoning fixtures."""

    def make(observations: dict, hypothesis: dict) -> ModelProfile:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        paths = {
            "perception": fixtures / "qwen_observations.json",
            "reasoning": fixtures / "final_hypothesis.json",
        }
        paths["perception"].write_text(json.dumps(observations), encoding="utf-8")
        paths["reasoning"].write_text(json.dumps(hypothesis), encoding="utf-8")
        base = load_profile("fixture")
        return base.model_copy(
            update={
                role: getattr(base, role).model_copy(
                    update={"fixture": str(path), "fixture_dir": str(fixtures)}
                )
                for role, path in paths.items()
            }
        )

    return make


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


@pytest.fixture
def consistent(make_profile: MakeProfile) -> ModelProfile:
    observations = {
        "cam_01": _obs("cam_01", "obs_a_001", 1.0, 1.6, "right", 0.84, [1]),
        "cam_02": _obs("cam_02", "obs_b_001", 1.2, 2.0, "west", 0.76, [1, 2]),
        "cam_03": _obs("cam_03", "obs_c_001", 2.1, 3.0, "center_left", 0.79, [2, 3]),
    }
    hypothesis = {
        "event_type": "vehicle_stop",
        "region": "blind_zone_02",
        "confidence": 0.74,
        "evidence_ids": ["obs_a_001", "obs_b_001", "obs_c_001"],
        "reason": "Three cameras show traffic slowing toward the same core.",
        "alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.39}],
        "limitations": [],
    }
    return make_profile(observations, hypothesis)

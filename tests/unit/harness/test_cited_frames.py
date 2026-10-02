"""P10: ``cited_frames`` resolves a hypothesis's cited evidence into frame indices per camera."""

from __future__ import annotations

from apps.api.schemas import EvidenceBundle, Hypothesis, MediaManifest
from harness.dev_sequence import cited_frames

FRAMES = 8


def _manifest(camera_id: str) -> MediaManifest:
    return MediaManifest.model_validate(
        {
            "camera_id": camera_id,
            "source": f"data/prepared/eval_001/{camera_id}.mp4",
            "duration_s": 8.0,
            "src_fps": 30.0,
            "width": 768,
            "height": 432,
            "sample_fps": 1.0,
            "frames": [{"index": i, "frame_id": i * 30, "t": float(i)} for i in range(FRAMES)],
        }
    )


def _item(evidence_id: str, camera_id: str, frames: list[int]) -> dict:
    return {
        "id": evidence_id,
        "camera_id": camera_id,
        "t_start": 0.0,
        "t_end": 4.0,
        "cue_type": "vehicle_slowing_or_stopping",
        "description": "a van slows",
        "confidence": 0.7,
        "supporting_frames": frames,
    }


def test_each_camera_lists_every_cited_frame_once_in_order():
    bundle = EvidenceBundle.model_validate(
        {
            "scenario_id": "eval_001",
            "status": "ok",
            "cameras": [{"id": "cam_a"}, {"id": "cam_b"}],
            "evidence": [
                _item("cam_b.o1", "cam_b", [2, 1, 0]),
                _item("cam_b.o2", "cam_b", [2, 3, FRAMES + 1]),
                _item("cam_a.o1", "cam_a", [4]),
            ],
            "clusters": [],
            "region_candidates": [],
        }
    )
    hypothesis = Hypothesis.model_validate(
        {
            "event_type": "vehicle_stop",
            "region": "unknown",
            "confidence": 0.5,
            "evidence_ids": ["cam_b.o1", "cam_b.o2"],
            "reason": "built for a unit test",
            "alternatives": [],
            "limitations": [],
        }
    )
    manifests = {c: _manifest(c) for c in ("cam_a", "cam_b")}
    assert cited_frames(bundle, hypothesis, manifests) == {"cam_b": [0, 1, 2, 3]}

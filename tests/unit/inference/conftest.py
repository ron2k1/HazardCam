"""Shared fixtures for inference unit tests: tiny frame images, manifests, a mock server.

Images here only exercise request shaping (encoding, downscaling, labels); no model
decision is evaluated on them. Live behaviour on real footage is in tests/integration.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from apps.api.schemas import REPO_ROOT, EvidenceBundle, MediaManifest
from inference.profiles import ModelProfile, load_profile


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    out = tmp_path / "frames"
    out.mkdir()
    for i in range(6):
        Image.new("RGB", (1024, 576), (10 * i, 40, 80)).save(out / f"{i:04d}.jpg", "JPEG")
    return out


@pytest.fixture
def manifest(frames_dir: Path) -> MediaManifest:
    frames = [
        {"index": i, "frame_id": 30 * i, "t": float(i), "path": str(frames_dir / f"{i:04d}.jpg")}
        for i in range(6)
    ]
    return MediaManifest(
        camera_id="cam_01",
        source="data/prepared/scenario_001/cam_a.mp4",
        duration_s=6.0,
        src_fps=30.0,
        width=1024,
        height=576,
        sample_fps=1.0,
        frames=frames,
    )


@pytest.fixture
def lite_profile() -> ModelProfile:
    return load_profile("lite-local", env={})


@pytest.fixture
def fixture_profile(example_fixture_profile: ModelProfile) -> ModelProfile:
    return example_fixture_profile


@pytest.fixture
def bundle() -> EvidenceBundle:
    path = REPO_ROOT / "contracts" / "examples" / "evidence_bundle.json"
    return EvidenceBundle.model_validate_json(path.read_text(encoding="utf-8"))


def completion(
    content: Any, *, model: str = "m", finish: str = "stop", reasoning: str = ""
) -> dict:
    """An OpenAI-style chat completion body; dict/list content is JSON-encoded."""
    text = content if isinstance(content, str) else json.dumps(content)
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning"] = reasoning
    return {
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


class MockServer:
    """Records request bodies/headers and replays queued responses (dict, int status,
    or an exception instance to raise). The last response repeats when the queue empties."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        self.headers.append(request.headers)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return httpx.Response(item, json={"error": "boom"})
        return httpx.Response(200, json=item)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def mock_server() -> Callable[..., MockServer]:
    return MockServer


@pytest.fixture
def reply() -> Callable[..., dict]:
    return completion

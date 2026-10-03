"""Fixtures for the hazard pipeline tests (fast: no GPU, no network)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from hazards.detector.client import DetectorClient
from hazards.review import HazardReviewer
from inference.profiles import EndpointConfig
from tests.unit.hazards._helpers import (
    STUB_BASE_URL,
    STUB_MODEL,
    StubDetector,
    StubVLLM,
    make_synthetic_video,
    unreachable_transport,
)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg/ffprobe on PATH",
)


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """960x540, 40 frames at 10 fps, stored as a neutral ``clips/hz_99/source.mp4``."""
    root = tmp_path_factory.mktemp("synthetic")
    return make_synthetic_video(root / "clips" / "hz_99" / "source.mp4")


@pytest.fixture
def down_detector() -> DetectorClient:
    """A detector client whose every request fails to connect."""
    return DetectorClient("http://127.0.0.1:8003", transport=unreachable_transport())


@pytest.fixture
def stub_detector() -> Iterator[StubDetector]:
    stub = StubDetector(
        objects=[
            {
                "model": "yolo11s",
                "label": "suitcase",
                "conf": 0.61,
                "box": [420.0, 250.0, 470.0, 300.0],
            },
        ]
    ).start()
    try:
        yield stub
    finally:
        stub.stop()


def gb10_like_endpoint(**overrides: object) -> EndpointConfig:
    base = {
        "backend": "openai_compatible",
        "base_url": STUB_BASE_URL,
        "model": STUB_MODEL,
        "timeout_seconds": 120,
        "max_tokens": 1024,
        "retries": 2,
        "think": False,
        "think_param": "chat_template_kwargs",
        "structured_output": "json_schema",
    }
    return EndpointConfig(**{**base, **overrides})


@pytest.fixture
def stub_vllm() -> StubVLLM:
    return StubVLLM()


@pytest.fixture
def stub_reviewer(stub_vllm: StubVLLM) -> HazardReviewer:
    return HazardReviewer(
        gb10_like_endpoint(), profile_name="gb10", transport=stub_vllm.transport, env={}
    )

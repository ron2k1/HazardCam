"""API integration fixtures.

The scenario is ``contracts/examples/scenario_001.json`` written into a tmp manifests
dir. Its camera files are TEST MEDIA: tiny clips generated here with ffmpeg's lavfi
``testsrc2`` source, used only to exercise HTTP Range and file serving.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT
from apps.api.settings import Settings

EXAMPLE_SCENARIO = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"
FFMPEG = shutil.which("ffmpeg")


def make_test_clip(path: Path, seconds: float = 2.0) -> None:
    """Generate a tiny TEST MEDIA clip (synthetic lavfi pattern, not scenario footage)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=160x90:rate=10:duration={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def make_test_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x36",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        timeout=60,
    )


@pytest.fixture(scope="session")
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Media root holding TEST MEDIA at the scenario's repo-relative camera paths."""
    root = tmp_path_factory.mktemp("media_root")
    if FFMPEG is not None:
        doc = json.loads(EXAMPLE_SCENARIO.read_text(encoding="utf-8"))
        for cam in [*doc["visible_cameras"], doc["ground_truth_camera"]]:
            make_test_clip(root / cam["file"])
    return root


@pytest.fixture
def make_jpeg() -> Callable[[Path], None]:
    if FFMPEG is None:
        pytest.skip("ffmpeg not on PATH")
    return make_test_jpeg


@pytest.fixture
def scenario_doc() -> dict[str, Any]:
    return json.loads(EXAMPLE_SCENARIO.read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path, media_root: Path, scenario_doc: dict[str, Any]) -> Settings:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "scenario_001.json").write_text(json.dumps(scenario_doc), encoding="utf-8")
    return Settings(
        manifests_dir=manifests,
        prepared_dir=tmp_path / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=media_root,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE body into messages ``{id, event, data, raw_fields}``; comments dropped."""
    messages = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        data_lines = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data_lines.append(value)
            else:
                fields[key] = value
        if data_lines:
            messages.append(
                {
                    "id": fields.get("id"),
                    "event": fields.get("event"),
                    "fields": set(fields) | {"data"},
                    "data": json.loads("\n".join(data_lines)),
                }
            )
    return messages


@pytest.fixture
def read_events(client: httpx.AsyncClient) -> Callable[..., Any]:
    """``await read_events(run_id, params=..., headers=...) -> (response, messages)``.

    Fails instead of hanging if the server does not close the stream.
    """

    async def _read(run_id: str, *, timeout: float = 10.0, **kwargs: Any):
        response = await asyncio.wait_for(
            client.get(f"/api/runs/{run_id}/events", **kwargs), timeout=timeout
        )
        return response, parse_sse(response.text)

    return _read


@pytest.fixture
def start_run(client: httpx.AsyncClient) -> Callable[..., Any]:
    async def _start(**body: Any) -> dict[str, Any]:
        response = await client.post("/api/runs", json={"scenario_id": "scenario_001", **body})
        assert response.status_code == 202, response.text
        return response.json()

    return _start

"""P03: /healthz dependency report and /api/models/health endpoint probes."""

from __future__ import annotations

import json
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT

DEPENDENCIES = {"manifests_dir", "ffmpeg", "ffprobe", "runs_dir", "profile"}


async def test_healthz_shape(client, settings):
    body = (await client.get("/healthz")).json()
    assert set(body) == {"status", "service", "version", "profile", "dependencies"}
    assert set(body["dependencies"]) == DEPENDENCIES
    assert all(isinstance(d["ok"], bool) for d in body["dependencies"].values())
    deps = body["dependencies"]
    assert deps["manifests_dir"]["ok"] is True
    assert deps["manifests_dir"]["scenario_count"] == 1
    assert deps["runs_dir"]["ok"] is True and settings.runs_dir.is_dir()
    assert deps["profile"] == {"ok": True, "name": "fixture"}
    assert deps["ffmpeg"]["ok"] is (shutil.which("ffmpeg") is not None)
    expected = "ok" if all(d["ok"] for d in deps.values()) else "degraded"
    assert body["status"] == expected
    assert body["profile"] == "fixture"


async def test_healthz_degraded_without_manifests(settings, tmp_path):
    settings.manifests_dir = tmp_path / "missing"
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/healthz")).json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["manifests_dir"]["ok"] is False


async def test_healthz_reports_invalid_manifests(client, settings):
    (settings.manifests_dir / "broken.json").write_text('{"id": "x"}')
    (settings.manifests_dir / "scenario_001.provenance.json").write_text('{"source": "x"}')
    deps = (await client.get("/healthz")).json()["dependencies"]
    assert deps["manifests_dir"]["scenario_count"] == 1
    assert deps["manifests_dir"]["invalid_manifests"] == ["broken.json"]


async def test_models_health_fixture_profile(client):
    body = (await client.get("/api/models/health")).json()
    assert body["profile"] == "fixture"
    assert body["status"] == "fixture"
    for role in ("perception", "reasoning"):
        assert body[role]["status"] == "fixture"
        assert body[role]["reachable"] is None


async def test_models_health_rejects_unknown_profiles(client):
    assert (await client.get("/api/models/health", params={"profile": "nope"})).status_code == 404
    traversal = {"profile": "../../pyproject"}
    assert (await client.get("/api/models/health", params=traversal)).status_code == 404


class _ModelsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps({"object": "list", "data": [{"id": "test-vlm"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture
def models_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_models_health_probes_live_endpoints(settings, tmp_path, models_server, monkeypatch):
    for var in ("QWEN_BASE_URL", "QWEN_MODEL", "MISTRAL_BASE_URL", "MISTRAL_MODEL"):
        monkeypatch.delenv(var, raising=False)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    shutil.copy(REPO_ROOT / "config" / "models" / "fixture.yaml", models_dir)
    (models_dir / "p03-test-live.yaml").write_text(
        "profile: p03-test-live\nmode: local\n"
        f"perception:\n  backend: openai_compatible\n  base_url: {models_server}/v1\n"
        "  model: test-vlm\n"
        "reasoning:\n  backend: openai_compatible\n"
        f"  base_url: http://127.0.0.1:{_closed_port()}/v1\n  model: test-reasoner\n",
        encoding="utf-8",
    )
    settings.models_dir = models_dir
    settings.model_probe_timeout_s = 1.0
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/models/health", params={"profile": "p03-test-live"})).json()

    assert body["profile"] == "p03-test-live"
    assert body["source"] == "yaml"
    assert body["status"] == "degraded"
    perception, reasoning = body["perception"], body["reasoning"]
    assert perception["status"] == "ok" and perception["reachable"] is True
    assert perception["http_status"] == 200 and perception["model_listed"] is True
    assert perception["base_url"] == f"{models_server}/v1"
    assert reasoning["status"] == "unreachable" and reasoning["reachable"] is False
    assert reasoning["model"] == "test-reasoner"

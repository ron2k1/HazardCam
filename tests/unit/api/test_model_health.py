"""P03: the model-health helpers (profile description and endpoint probes)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from apps.api.services import model_health


def test_yaml_profile_info_applies_env_overrides(tmp_path, monkeypatch):
    (tmp_path / "live.yaml").write_text(
        "profile: live\nmode: local\n"
        "perception: {backend: openai_compatible, base_url: http://a/v1, model: q}\n"
        "reasoning: {backend: fixture, fixture: x.json}\n"
    )
    monkeypatch.setenv("QWEN_BASE_URL", "http://override:1/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-override")
    monkeypatch.setenv("MISTRAL_BASE_URL", "http://ignored/v1")
    info = model_health._from_yaml("live", tmp_path)
    assert info["perception"]["base_url"] == "http://override:1/v1"
    assert info["perception"]["model"] == "qwen-override"
    assert "base_url" not in info["reasoning"]  # fixture backends ignore endpoint overrides


_PLACEHOLDER_PROFILE = (
    "profile: {name}\nmode: local\n"
    "perception: {{backend: openai_compatible, base_url: http://a/v1, model: REPLACE_ME}}\n"
    "reasoning: {{backend: openai_compatible, base_url: http://b/v1, model: r}}\n"
)


@pytest.fixture
def no_model_env(monkeypatch):
    for var in ("QWEN_BASE_URL", "QWEN_MODEL", "MISTRAL_BASE_URL", "MISTRAL_MODEL"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.usefixtures("no_model_env")
def test_inference_profiles_describes_unfilled_profiles(tmp_path, monkeypatch):
    profiles = pytest.importorskip("inference.profiles")
    (tmp_path / "unfilled.yaml").write_text(_PLACEHOLDER_PROFILE.format(name="unfilled"))
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    with pytest.raises(profiles.ProfileError):
        profiles.load_profile("unfilled")  # selecting it is refused...
    info = model_health.load_profile_info("unfilled", tmp_path)  # ...describing it is not
    assert info["source"] == "inference.profiles"
    assert info["perception"]["model"] == "REPLACE_ME"


@pytest.mark.usefixtures("no_model_env")
def test_custom_models_dir_bypasses_inference_profiles(tmp_path):
    profiles = pytest.importorskip("inference.profiles")
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "lite-local.yaml").write_text(_PLACEHOLDER_PROFILE.format(name="lite-local"))
    assert (profiles.PROFILES_DIR / "lite-local.yaml").is_file()  # same name exists in P06's dir
    info = model_health.load_profile_info("lite-local", custom)
    assert info["source"] == "yaml"
    assert info["perception"]["base_url"] == "http://a/v1"


def test_profile_object_shapes_are_normalised():
    class Section:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    obj = Section(
        name="p",
        mode="local",
        perception=Section(backend="b", base_url="u", model="m"),
        reasoning={"backend": "fixture"},
    )
    info = model_health._from_profile_object(obj, "p")
    assert info["perception"] == {"backend": "b", "base_url": "u", "model": "m"}
    with pytest.raises(KeyError):
        model_health._from_profile_object({"perception": {}}, "p")


def test_userinfo_is_stripped_from_reported_urls():
    assert model_health._without_userinfo("http://u:secret@h:1/v1") == "http://h:1/v1"
    assert model_health._without_userinfo("http://h:1/v1") == "http://h:1/v1"
    assert model_health._without_userinfo(None) is None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = (
            (200, b'{"data": [{"id": "m1"}]}') if self.path == "/ok/models" else (503, b"{}")
        )
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def test_probe_role_statuses():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            ok = await model_health.probe_role(
                client, {"backend": "x", "base_url": f"{base}/ok", "model": "m1"}
            )
            missing = await model_health.probe_role(
                client, {"backend": "x", "base_url": f"{base}/ok", "model": "m2"}
            )
            bad = await model_health.probe_role(
                client, {"backend": "x", "base_url": f"{base}/bad", "model": "m1"}
            )
            unset = await model_health.probe_role(client, {"backend": "x"})
            placeholder = await model_health.probe_role(
                client, {"backend": "x", "base_url": f"{base}/ok", "model": "REPLACE_ON_GB10"}
            )
            fixture = await model_health.probe_role(client, {"backend": "fixture"})
    finally:
        server.shutdown()
        server.server_close()
    assert ok["status"] == "ok" and ok["model_listed"] is True and ok["reachable"] is True
    assert missing["model_listed"] is False
    assert bad["status"] == "http_error" and bad["http_status"] == 503 and bad["reachable"] is True
    assert unset["status"] == "unconfigured" and unset["reachable"] is None
    assert unset["missing"] == ["base_url", "model"]
    # a reachable endpoint does not make an unfilled profile "ok"
    assert placeholder["status"] == "unconfigured" and placeholder["missing"] == ["model"]
    assert "http_status" not in placeholder
    assert fixture == {
        "backend": "fixture",
        "base_url": None,
        "model": None,
        "status": "fixture",
        "reachable": None,
    }

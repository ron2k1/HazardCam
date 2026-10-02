"""P03: the temporary fixture replay executor and the model-health helpers."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from apps.api.schemas import EVENT_TYPES, TERMINAL_EVENT_TYPES, Hypothesis
from apps.api.services import model_health
from apps.api.services.fixture_executor import FIXTURES_DIR, HARNESS, FixtureReplayExecutor

NON_TERMINAL = set(EVENT_TYPES) - TERMINAL_EVENT_TYPES


def _record(executor, scenario, tmp_path, pace_s=0.0):
    events: list[tuple[str, dict]] = []
    result = executor(scenario, "fixture", lambda t, p: events.append((t, p)), tmp_path, pace_s)
    return result, events


def test_fixture_replay_covers_the_catalog(scenario, tmp_path):
    hypothesis, events = _record(FixtureReplayExecutor(), scenario, tmp_path)
    expected = Hypothesis.model_validate_json((FIXTURES_DIR / "final_hypothesis.json").read_bytes())
    assert hypothesis == expected
    types = [t for t, _ in events]
    assert set(types) == NON_TERMINAL
    assert types[:2] == ["run.started", "orchestrator.started"]
    assert events[0][1]["harness"] == HARNESS == "fixture-replay"
    assert events[1][1]["agent"] is False
    assert [p["camera_id"] for t, p in events if t == "camera.started"] == [
        "cam_01",
        "cam_02",
        "cam_03",
    ]
    observed = [p["observation"].id for t, p in events if t == "camera.observation"]
    assert observed == ["obs_a_001", "obs_b_001", "obs_c_001"]
    (cluster_payload,) = [p for t, p in events if t == "evidence.linked"]
    assert cluster_payload["cluster"].evidence_ids == observed
    (triangulation,) = [p for t, p in events if t == "triangulation.updated"]
    assert [c.id for c in triangulation["candidates"]] == ["blind_zone_02"]
    assert triangulation["candidates"][0].method == "zone_prior"
    finals = [p["final"] for t, p in events if t == "hypothesis.updated"]
    assert finals == [False, True]
    assert "cam_gt" not in repr(events) and "hidden_ground_truth" not in repr(events)


def test_fixture_replay_tool_pairs_balance(scenario, tmp_path):
    _, events = _record(FixtureReplayExecutor(), scenario, tmp_path)
    started = [p["call_id"] for t, p in events if t == "tool.started"]
    completed = [p["call_id"] for t, p in events if t == "tool.completed"]
    assert started == completed and len(set(started)) == len(started) == 6


def test_per_scenario_fixtures_take_precedence(scenario, tmp_path):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, fixtures, ignore=shutil.ignore_patterns("*.example.json"))
    scoped = fixtures / scenario.id
    scoped.mkdir()
    abstain = {"event_type": "unknown", "region": "unknown", "confidence": 0.2, "reason": "weak"}
    (scoped / "final_hypothesis.json").write_text(json.dumps(abstain), encoding="utf-8")
    (scoped / "qwen_observations.json").write_text(json.dumps({}), encoding="utf-8")
    hypothesis, events = _record(FixtureReplayExecutor(fixtures), scenario, tmp_path / "run")
    assert hypothesis.abstained
    assert not any(t in {"camera.observation", "evidence.linked"} for t, _ in events)
    (triangulation,) = [p for t, p in events if t == "triangulation.updated"]
    assert triangulation["candidates"] == []


def test_failed_tool_reports_and_reraises(scenario, tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    shutil.copy(FIXTURES_DIR / "final_hypothesis.json", fixtures)
    (fixtures / "qwen_observations.json").write_text(
        json.dumps({"cam_01": {"camera_id": "cam_01", "observations": [{"id": ""}]}})
    )
    events: list[tuple[str, dict]] = []
    with pytest.raises(ValueError):
        FixtureReplayExecutor(fixtures)(
            scenario, "fixture", lambda t, p: events.append((t, p)), tmp_path, 0.0
        )
    assert events[-1][0] == "tool.completed"
    assert events[-1][1]["ok"] is False and events[-1][1]["tool"] == "inspect_camera"


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

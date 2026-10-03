"""GET /api/runtime/status: the local stack as plain rows (no real probes here: the
subprocess, HTTP, TCP and PATH lookups are injected)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT
from apps.api.services import runtime_status as rs
from apps.api.settings import Settings

SCHEMA = json.loads((REPO_ROOT / "contracts" / "hazard_view.schema.json").read_text("utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
KEYS = ["nemoclaw", "openclaw", "openshell", "tool_server", "qwen", "detector", "network"]
SANDBOX_LIST = (
    "\x1b[1mNAME            CREATED              PHASE\x1b[0m\n"
    "ambient-mirror  2026-10-03 09:12:44  \x1b[32mReady\x1b[0m\n"
)
SECRET = "sk-test-0123456789abcdef"


def validate(doc: Any) -> None:
    ref = {"$ref": f"{SCHEMA['$id']}#/$defs/RuntimeStatus"}
    Draft202012Validator(ref, registry=REGISTRY).validate(doc)


class OpenClawAgentExecutor:  # same class name as the event-day executor
    pass


class DevExecutor:
    pass


class State:
    def __init__(self, executor: Any = None, runner_name: str | None = None) -> None:
        self.executor = executor
        self.hazard_review_runner_name = runner_name


class Fakes:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.urls: list[str] = []
        self.sandbox_output = SANDBOX_LIST
        self.code = 0
        self.http: dict[str, tuple[int, Any]] = {
            "http://127.0.0.1:8000/health": (200, None),
            "http://127.0.0.1:8003/health": (
                200,
                {"ok": True, "device": "cuda:0 (NVIDIA GB10)", "models": {"yolo11s": {}}},
            ),
        }
        self.open_ports = {8080, 8090}
        self.binary: str | None = "/home/x/.local/bin/openshell"

    def run(self, args: Sequence[str], timeout: float, env: Mapping[str, str]) -> tuple[int, str]:
        assert timeout == rs.COMMAND_TIMEOUT_S
        self.commands.append(list(args))
        return self.code, self.sandbox_output

    def get(self, url: str, timeout: float) -> tuple[int, Any]:
        self.urls.append(url)
        if url not in self.http:
            raise httpx.ConnectError("refused")
        return self.http[url]

    def tcp(self, host: str, port: int, timeout: float) -> bool:
        return port in self.open_ports

    def which(self, name: str, path: str) -> str | None:
        assert name == "openshell" and ".local/bin" in path
        return self.binary


def prober(fakes: Fakes, profile: str = "gb10", **kwargs: Any) -> rs.RuntimeStatus:
    env = {"PATH": "/usr/bin", "OPENSHELL_TOKEN": SECRET, **kwargs.pop("env", {})}
    return rs.RuntimeStatus(
        profile=profile,
        env=env,
        run_command=fakes.run,
        http_get=fakes.get,
        tcp_open=fakes.tcp,
        which=fakes.which,
        **kwargs,
    )


def rows(snapshot: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {r["key"]: r for r in snapshot["rows"]}


def test_everything_up_on_the_gb10() -> None:
    fakes = Fakes()
    snapshot = prober(fakes).status(State(OpenClawAgentExecutor(), "openclaw-agent"))
    validate(snapshot)
    assert [r["key"] for r in snapshot["rows"]] == KEYS
    by_key = rows(snapshot)
    assert {k: r["status"] for k, r in by_key.items()} == dict.fromkeys(KEYS, "ok")
    assert by_key["nemoclaw"]["value"] == "Ready"  # ANSI colour codes stripped
    assert by_key["nemoclaw"]["detail"] == "sandbox ambient-mirror"
    assert by_key["openclaw"]["value"] == "agent"
    assert by_key["openclaw"]["detail"] == "agent urban-mirror · safety checks: openclaw-agent"
    assert by_key["qwen"]["value"] == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert by_key["detector"] == {
        "key": "detector",
        "label": "Detector",
        "status": "ok",
        "value": "yolo11s",
        "detail": "cuda:0 (NVIDIA GB10)",
    }
    assert by_key["network"]["value"] == "local only" and snapshot["local_only"] is True
    assert fakes.commands == [["/home/x/.local/bin/openshell", "sandbox", "list"]]
    assert "http://127.0.0.1:8000/health" in fakes.urls


def test_rows_carry_no_tokens_or_env_values() -> None:
    fakes = Fakes()
    snapshot = prober(fakes, env={"HAZARDS_DETECTOR_URL": "http://127.0.0.1:8003/"}).status(
        State(OpenClawAgentExecutor())
    )
    text = json.dumps(snapshot)
    assert SECRET not in text and "token" not in text.lower()
    assert "/usr/bin" not in text


def test_dev_harness_and_missing_pieces_are_reported_not_raised() -> None:
    fakes = Fakes()
    fakes.sandbox_output = "NAME PHASE\nother-box Ready\n"
    fakes.open_ports = set()
    fakes.http = {}
    by_key = rows(prober(fakes).status(State(DevExecutor())))
    assert by_key["openclaw"]["status"] == "down" and by_key["openclaw"]["value"] == "dev harness"
    assert by_key["openclaw"]["detail"].endswith("safety checks: direct")
    assert by_key["nemoclaw"]["status"] == "down" and by_key["nemoclaw"]["value"] == "not found"
    assert by_key["openshell"]["status"] == "down"
    assert by_key["tool_server"]["value"] == "not reachable"
    assert by_key["qwen"]["status"] == "down"
    assert by_key["detector"]["status"] == "down"
    assert rows(prober(fakes).status(State()))["openclaw"]["status"] == "unknown"


def test_openshell_missing_failing_or_not_ready() -> None:
    fakes = Fakes()
    fakes.binary = None
    assert rows(prober(fakes).status(State()))["nemoclaw"]["value"] == "openshell not found"
    assert fakes.commands == []
    fakes = Fakes()
    fakes.code = 1
    assert rows(prober(fakes).status(State()))["nemoclaw"]["status"] == "unknown"
    fakes = Fakes()
    fakes.sandbox_output = "ambient-mirror  2026-10-03  Provisioning\n"
    nemo = rows(prober(fakes).status(State()))["nemoclaw"]
    assert (nemo["status"], nemo["value"]) == ("down", "Provisioning")


def test_probe_errors_become_unknown_rows() -> None:
    fakes = Fakes()

    def boom(*args: Any) -> Any:
        raise RuntimeError("probe crashed with secret " + SECRET)

    status = rs.RuntimeStatus(
        profile="gb10",
        env={"PATH": "/usr/bin"},
        run_command=boom,
        http_get=boom,
        tcp_open=boom,
        which=fakes.which,
    )
    snapshot = status.status(State())
    validate(snapshot)
    assert [r["key"] for r in snapshot["rows"]] == KEYS
    assert SECRET not in json.dumps(snapshot)
    by_key = rows(snapshot)
    assert by_key["nemoclaw"]["status"] == "unknown"
    assert by_key["openshell"]["status"] == "unknown"


def test_fixture_profile_has_no_model_to_check() -> None:
    fakes = Fakes()
    qwen = rows(prober(fakes, profile="fixture").status(State()))["qwen"]
    assert qwen["status"] == "unknown" and "fixture" in qwen["value"]
    assert "http://127.0.0.1:8000/health" not in fakes.urls


def test_non_local_addresses_fail_the_network_row() -> None:
    fakes = Fakes()
    snapshot = prober(fakes, env={"HAZARDS_DETECTOR_URL": "http://203.0.113.5:8003"}).status(
        State()
    )
    network = rows(snapshot)["network"]
    assert network["status"] == "down" and snapshot["local_only"] is False
    assert "203.0.113.5" not in json.dumps(snapshot)
    bridge = prober(Fakes(), env={"AUM_TOOLS_BIND": "127.0.0.1:8090,172.18.0.1:8090"})
    assert bridge.status(State())["local_only"] is True


def test_snapshot_is_cached_for_15_s() -> None:
    fakes = Fakes()
    now = [100.0]
    status = prober(fakes, clock=lambda: now[0])
    first = status.status(State())
    now[0] += 14.9
    assert status.status(State()) is first and len(fakes.commands) == 1
    now[0] += 0.2
    assert status.status(State()) is not first and len(fakes.commands) == 2


@pytest.mark.parametrize(
    ("base", "health"),
    [
        ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8000/health"),
        ("http://127.0.0.1:8000/v1/", "http://127.0.0.1:8000/health"),
        ("http://172.18.0.1:8000", "http://172.18.0.1:8000/health"),
    ],
)
def test_health_url(base: str, health: str) -> None:
    assert rs.health_url(base) == health


def test_sandbox_phase_parsing() -> None:
    assert rs.sandbox_phase(SANDBOX_LIST) == "Ready"
    assert rs.sandbox_phase("") is None
    assert rs.sandbox_phase("ambient-mirror-2  x  Ready") is None


async def test_route_uses_the_app_prober(tmp_path: Path) -> None:
    settings = Settings(
        manifests_dir=tmp_path / "m", prepared_dir=tmp_path / "p", runs_dir=tmp_path / "r"
    )
    app = create_app(settings)
    fakes = Fakes()
    app.state.runtime_status = prober(fakes)
    app.state.executor = OpenClawAgentExecutor()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/api/runtime/status")
    assert response.status_code == 200
    body = response.json()
    validate(body)
    assert rows(body)["openclaw"]["status"] == "ok"

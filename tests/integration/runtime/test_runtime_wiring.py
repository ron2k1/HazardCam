"""D02 (event day, 2026-10-03): NemoClaw/OpenShell runtime wiring and local model routes.

Acceptance: "No cloud model route", "Failure surfaced to UI", "Runtime command documented",
"Required stack status captured". The hermetic tests need no sandbox; the live one runs
only with ``AUM_LIVE_RUNTIME=1`` on the GB10.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
import yaml

from agent.event_day.app import create_agent_app
from agent.event_day.registration import REGISTERED_TOOLS, SERVER_NAME, TOOL_PREFIX
from apps.api.schemas import REPO_ROOT
from apps.api.settings import Settings
from inference.profiles import load_profile
from tools.session import TOOL_NAMES

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PRESET = REPO_ROOT / "runtime" / "nemoclaw" / "mirror-tools.policy.yaml"
START = REPO_ROOT / "scripts" / "runtime" / "start_api.sh"
EXAMPLE = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"


def _deploy_module():
    path = REPO_ROOT / "scripts" / "runtime" / "deploy_agent.py"
    spec = importlib.util.spec_from_file_location("deploy_agent", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# -- no cloud model route -------------------------------------------------------------


def test_gb10_profile_is_filled_and_every_route_is_local():
    profile = load_profile("gb10", env={})
    assert profile.perception.model == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    # Operator choice (2026-10-03): Qwen fills the reasoning slot too, like the safety notebook.
    assert profile.reasoning.model == "nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert profile.reasoning.think_param == "chat_template_kwargs"
    for slot in (profile.perception, profile.reasoning):
        assert urlparse(slot.base_url).hostname in LOCAL_HOSTS, slot.base_url
        assert "REPLACE" not in slot.model
    raw = (REPO_ROOT / "config" / "models" / "gb10.yaml").read_text(encoding="utf-8")
    assert "DEVIATION" in raw and "Mistral" in raw  # the Mistral swap is recorded


def test_the_egress_preset_opens_only_the_host_tool_server():
    doc = yaml.safe_load(PRESET.read_text(encoding="utf-8"))
    policies = doc["network_policies"]
    assert list(policies) == ["mirror_tools"]
    endpoints = policies["mirror_tools"]["endpoints"]
    assert len(endpoints) == 1
    ep = endpoints[0]
    assert (ep["host"], ep["port"]) == ("host.openshell.internal", 8090)
    assert ep["allowed_ips"] == ["172.18.0.1/32"]
    assert ep["enforcement"] == "enforce"
    assert {(r["allow"]["method"], r["allow"]["path"]) for r in ep["rules"]} == {
        ("POST", "/mcp"),
        ("DELETE", "/mcp"),
    }


def _sandbox_like_config() -> dict:
    """The shape of the sandbox's ``openclaw.json`` that the deploy merges into."""
    return {
        "agents": {
            "defaults": {"workspace": "/sandbox/.openclaw/workspace"},
            "list": [{"id": "main"}],
        },
        "models": {
            "mode": "merge",
            "providers": {
                "inference": {
                    "baseUrl": "https://inference.local/v1",
                    "models": [{"id": "nvidia/Qwen3.6-35B-A3B-NVFP4"}],
                }
            },
        },
        "tools": {"alsoAllow": ["bundle-mcp"]},
    }


def test_the_deploy_merge_adds_the_agent_and_tool_server_and_no_model_route():
    deploy = _deploy_module()
    base = _sandbox_like_config()
    merged = deploy.merged_config(base, "test-token")
    providers = merged["models"]["providers"]
    assert list(providers) == ["inference"]  # the only model route stays inference.local
    assert providers["inference"]["baseUrl"] == "https://inference.local/v1"
    assert providers["inference"]["models"][0]["maxTokens"] == deploy.AGENT_MAX_TOKENS
    server = merged["mcp"]["servers"][SERVER_NAME]
    assert server["url"] == "http://host.openshell.internal:8090/mcp"
    assert server["headers"] == {"Authorization": "Bearer test-token"}
    assert server["toolFilter"]["include"] == list(REGISTERED_TOOLS)
    assert server["toolFilter"]["include"][: len(TOOL_NAMES)] == list(TOOL_NAMES)
    agents = {a["id"]: a for a in merged["agents"]["list"]}
    mirror = agents["urban-mirror"]
    assert mirror["model"]["primary"] == "inference/nvidia/Qwen3.6-35B-A3B-NVFP4"
    assert mirror["model"]["fallbacks"] == []
    assert "message" not in mirror["tools"]["alsoAllow"]  # Telegram stays deferred
    assert f"{TOOL_PREFIX}*" in agents["main"]["tools"]["deny"]
    blob = json.dumps(merged)
    for cloud in ("integrate.api.nvidia.com", "api.openai.com", "api.mistral.ai", "openrouter"):
        assert cloud not in blob


# -- runtime command ------------------------------------------------------------------


def test_the_start_script_runs_the_sandboxed_agent_and_keeps_the_dev_fallback():
    subprocess.run(["bash", "-n", str(START)], check=True)
    text = START.read_text(encoding="utf-8")
    assert "sandbox exec -n $AUM_SANDBOX -- openclaw" in text
    assert "agent.event_day.app:create_agent_app" in text
    assert 'AUM_EXECUTOR" == "dev"' in text and "apps.api.main:app" in text
    assert "API_PORT:-8088" in text


# -- failure surfaced to the UI -------------------------------------------------------


@pytest.fixture
def fake_openshell(tmp_path: Path) -> Path:
    """An ``openshell`` stand-in that fails like a missing sandbox does."""
    path = tmp_path / "openshell"
    path.write_text(
        "#!/bin/sh\n"
        "echo \"Error: × code: 'Some requested entity was not found', "
        'message: \\"sandbox not found\\"" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


async def test_a_broken_sandbox_reaches_the_stream_as_run_failed(tmp_path: Path, fake_openshell):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    shutil.copy(EXAMPLE, manifests / "scenario_001.json")
    settings = Settings(
        manifests_dir=manifests,
        prepared_dir=tmp_path / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=tmp_path,
    )
    env = {  # what start_api.sh exports, with the sandbox command stubbed
        "AUM_OPENCLAW_CMD": f"{fake_openshell} sandbox exec -n ambient-mirror -- openclaw",
        "AUM_TOOLS_BIND": "127.0.0.1:0",
        "AUM_TOOLS_TOKEN": "t" * 32,
    }
    app = create_agent_app(settings, env=env)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            created = await c.post(
                "/api/runs", json={"scenario_id": "scenario_001", "profile": "fixture"}
            )
            assert created.status_code == 202, created.text
            run_id = created.json()["run_id"]
            body = await asyncio.wait_for(c.get(f"/api/runs/{run_id}/events"), timeout=60)
            record = (await c.get(f"/api/runs/{run_id}")).json()
    finally:
        app.state.tool_server.close()
    envelopes = [
        json.loads(line[5:].strip()) for line in body.text.splitlines() if line.startswith("data:")
    ]
    types = [e["type"] for e in envelopes]
    assert types == ["run.started", "orchestrator.started", "run.failed"]
    failed = envelopes[-1]["payload"]
    assert failed["stage"] == "agent"
    assert "sandbox not found" in failed["error"]
    assert str(tmp_path) not in failed["error"]
    assert record["state"] == "failed"


# -- live stack (GB10 only) -----------------------------------------------------------

live = pytest.mark.skipif(
    os.environ.get("AUM_LIVE_RUNTIME") != "1", reason="set AUM_LIVE_RUNTIME=1 on the GB10"
)


@live
def test_live_sandbox_status_shows_the_local_route_and_the_tool_preset():
    nemoclaw = shutil.which("nemoclaw") or str(Path.home() / ".local" / "bin" / "nemoclaw")
    out = subprocess.run(
        [nemoclaw, os.environ.get("AUM_SANDBOX", "ambient-mirror"), "status"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout
    assert "Inference: healthy (https://inference.local/v1/models)" in out
    assert "Provider: vllm-local" in out
    assert "mirror-tools" in out
    assert "integrate.api.nvidia.com" not in out  # the cloud baseline entry is excluded

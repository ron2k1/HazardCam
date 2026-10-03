"""The site lead (agent ``site-lead``) and concurrent checker leases on the tool gateway.

Hermetic: a fake launcher plays the lead's OpenClaw turn by calling the ``mirror__site_*``
tools through the real ``ToolGateway``, like the MCP server does.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from agent.event_day.executor import AgentTurn
from agent.event_day.mcp_server import ToolGateway
from agent.event_day.policy import ToolOutcome
from agent.event_day.registration import (
    LEAD_AGENT_ID,
    SITE_TOOL_NAMES,
    lead_agent_entry,
    openclaw_name,
    tool_specs,
)
from agent.event_day.site_lead import AgentSiteLead, lead_brief
from apps.api.services.site_runs import SiteService
from tests.unit.api.test_site_runs import CAMS, FakeHazards


class Echo:
    tool_names = ("hazard_scan_clip",)

    def __init__(self, clip_id: str) -> None:
        self.run_id = f"run-{clip_id}"
        self.clip_id = clip_id

    def call(self, name: str, arguments: Any = None) -> ToolOutcome:
        return ToolOutcome(name, ok=True, result={"served": self.clip_id})


def test_keyed_leases_route_each_call_to_its_own_clip_side_by_side():
    gateway = ToolGateway()
    leases = [gateway.acquire_keyed(Echo(c), c) for c in ("hz_01", "hz_02", "bs_01")]
    for clip in ("hz_01", "hz_02", "bs_01"):
        reply = gateway.call("hazard_scan_clip", {"clip_id": clip})
        assert reply["result"] == {"served": clip}
    assert gateway.call("hazard_scan_clip", {"clip_id": "other"})["refused"]
    assert gateway.call("site_check_status", {"clip_id": "hz_01"})["refused"]
    leases[0].release()
    assert gateway.call("hazard_scan_clip", {"clip_id": "hz_01"})["refused"]
    # a second lease on a held key waits, then gets it once the first is released
    got: list[Any] = []
    t = threading.Thread(
        target=lambda: got.append(gateway.acquire_keyed(Echo("hz_02"), "hz_02", timeout=5))
    )
    t.start()
    time.sleep(0.2)
    assert not got
    leases[1].release()
    t.join(5)
    assert got and gateway.call("hazard_scan_clip", {"clip_id": "hz_02"})["ok"]


def test_the_lead_is_granted_only_the_three_site_tools():
    entry = lead_agent_entry()
    assert entry["id"] == LEAD_AGENT_ID == "site-lead"
    assert entry["tools"]["alsoAllow"] == [openclaw_name(t) for t in SITE_TOOL_NAMES]
    assert entry["workspace"].endswith("workspace-site-lead")
    listed = {t["name"]: t for t in tool_specs()}
    for tool in SITE_TOOL_NAMES:
        assert listed[tool]["inputSchema"]["required"][0] == "site_run_id"
    brief = lead_brief("site-x", [{"cam": 1, "kind": "hazard"}])
    assert "site-x" in brief and "FINAL site alerts" in brief


class FakeLeadLauncher:
    """Plays the lead turn: start, poll, a refused invented alert, then a grounded one."""

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway
        self.replies: list[dict[str, Any]] = []

    def __call__(self, brief: str, *, run_id: str, timeout_s: float) -> AgentTurn:
        call = self.gateway.call
        self.replies.append(call("site_start_checks", {"site_run_id": run_id}))
        while True:
            status = call("site_check_status", {"site_run_id": run_id})
            if status["result"]["all_finished"]:
                break
        cams = {c["cam"]: c for c in status["result"]["cameras"]}
        assert cams[1]["findings"][0]["id"] == "H01"
        invented = call(
            "site_submit_alerts",
            {
                "site_run_id": run_id,
                "alerts": [
                    {"cam": 3, "severity": "high", "finding_ids": ["H07"], "line": "CAM 3 fire"}
                ],
            },
        )
        self.replies.append(invented)
        ok = call(
            "site_submit_alerts",
            {
                "site_run_id": run_id,
                "alerts": [
                    {
                        "cam": 1,
                        "severity": "high",
                        "finding_ids": ["H01"],
                        "line": "CAM 1: forklift near walkers",
                    }
                ],
            },
        )
        self.replies.append(ok)
        wrong_run = call("site_check_status", {"site_run_id": "site-other"})
        self.replies.append(wrong_run)
        return AgentTurn(ok=True, reply="FINAL site alerts=1", duration_s=0.1)


def test_the_lead_turn_runs_the_site_through_the_gateway(tmp_path: Path):
    gateway = ToolGateway()
    launcher = FakeLeadLauncher(gateway)
    sites = SiteService(
        FakeHazards(0.2),
        lambda: list(CAMS),
        tmp_path / "site_runs",
        lead_runner=AgentSiteLead(launcher, gateway),
        poll_s=0.05,
    )
    run = sites.start("live")
    deadline = time.monotonic() + 15
    while run.state == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    snap = run.snapshot()
    assert snap["state"] == "done" and snap["alerts_source"] == "lead"
    assert snap["alerts"][0]["cam"] == 1 and snap["alerts"][0]["job_id"]
    started, invented, ok, wrong_run = launcher.replies
    assert started["ok"] and started["result"]["started"]
    assert not invented["ok"] and "CAM 3" in invented["error"]
    assert ok["ok"]
    assert wrong_run["refused"]  # the lease routes only this site run's calls
    assert snap["lead_turn"]["agent"] == "site-lead" and snap["lead_turn"]["tool_calls"] >= 4
    assert not gateway.keyed_run_ids  # the lead's lease is released

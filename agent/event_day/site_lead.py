"""The site lead: OpenClaw agent ``site-lead`` over six concurrent checkers (event day).

Written on event day (2026-10-03, 14:30) for "1 main and 6 subagents running, 1 lead
6 checkers". OpenClaw 2026.7.1 lists ``group:sessions`` / ``group:agents`` sub-agent tools,
but the checkers must keep their gateway-leased, ground-truth-guarded tool surface, so the
fan-out is host-side: the lead's ``mirror__site_start_checks`` starts six urban-mirror
OpenClaw turns at once (the hazard runner seam, one keyed gateway lease per clip), and the
lead reads their validated reports and submits the alert list.

``AgentSiteLead`` is ``app.state.site_lead_runner`` (``apps/api/services/site_runs.py``):
one ``openclaw agent --agent site-lead`` turn, with ``SiteLeadSession`` holding the keyed
lease ``site_run_id`` so the three ``mirror__site_*`` tools reach this site run only.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from typing import Any

from .executor import AgentLauncher, AgentTurn, _short
from .mcp_server import ToolGateway
from .policy import ToolOutcome
from .registration import SITE_TOOL_NAMES, openclaw_name

logger = logging.getLogger(__name__)

LEAD_TIMEOUT_S = 900.0


def lead_brief(site_run_id: str, cams: list[dict[str, Any]]) -> str:
    start, status, submit = (openclaw_name(t) for t in SITE_TOOL_NAMES)
    wall = ", ".join(f"CAM {c['cam']} {c.get('kind', 'hazard')}" for c in cams)
    return "\n".join(
        [
            "SITE BRIEF",
            f"site_run_id: {site_run_id}",
            f"cameras: {wall}",
            "Follow AGENTS.md. Call, in this order:",
            f'  1. {start} {{"site_run_id": "{site_run_id}"}}',
            f'  2. {status} {{"site_run_id": "{site_run_id}"}} until all_finished is true',
            f'  3. {submit} {{"site_run_id": "{site_run_id}", "alerts": [...]}}',
            "Then reply with one line: FINAL site alerts=<count>",
        ]
    )


class SiteLeadSession:
    """The gateway policy for one site run's lead turn."""

    tool_names = SITE_TOOL_NAMES

    def __init__(self, run: Any, sites: Any) -> None:
        self.run = run
        self.sites = sites
        self.calls = 0

    @property
    def run_id(self) -> str:
        return str(self.run.site_run_id)

    def call(self, name: Any, arguments: Any = None) -> ToolOutcome:
        self.calls += 1
        tool = str(name)
        args = arguments if isinstance(arguments, dict) else {}
        if args.get("site_run_id") != self.run_id:
            return ToolOutcome(tool, ok=False, error="unknown site_run_id", refused=True)
        if tool == "site_start_checks":
            self.run.say("Lead agent started the six camera checkers", "tool")
            reply = self.sites.start_checks(self.run)
        elif tool == "site_check_status":
            reply = self.sites.check_status(self.run)
            res = reply.get("result") or {}
            done = sum(1 for c in res.get("cameras", []) if c["state"] in ("done", "failed"))
            self.run.say(f"Lead agent checked status: {done}/6 checkers finished", "tool")
        elif tool == "site_submit_alerts":
            reply = self.sites.submit_alerts(self.run, args.get("alerts"))
        else:
            return ToolOutcome(tool, ok=False, error="not a site tool", refused=True)
        if reply.get("ok"):
            return ToolOutcome(tool, ok=True, result=reply.get("result"))
        return ToolOutcome(
            tool, ok=False, error=reply.get("error"), refused=bool(reply.get("refused"))
        )


class AgentSiteLead:
    """``site_lead_runner(run, sites)``: one ``site-lead`` OpenClaw turn for the run."""

    def __init__(
        self,
        launcher: AgentLauncher,
        gateway: ToolGateway,
        *,
        timeout_s: float = LEAD_TIMEOUT_S,
    ) -> None:
        self.launcher = launcher
        self.gateway = gateway
        self.timeout_s = timeout_s

    def __call__(self, run: Any, sites: Any) -> None:
        session = SiteLeadSession(run, sites)
        lease = self.gateway.acquire_keyed(session, run.site_run_id, timeout=30.0)
        cams = [{"cam": c, "kind": k["kind"]} for c, k in sorted(run.checkers.items())]
        box: dict[str, AgentTurn] = {}
        t0 = time.monotonic()

        def turn() -> None:
            try:
                box["turn"] = self.launcher(
                    lead_brief(run.site_run_id, cams),
                    run_id=run.site_run_id,
                    timeout_s=self.timeout_s,
                )
            except Exception as exc:
                logger.warning("site lead launcher failed", exc_info=True)
                box["turn"] = AgentTurn(ok=False, error=_short(f"{type(exc).__name__}: {exc}"))

        thread = threading.Thread(target=turn, name=f"site-lead:{run.site_run_id}", daemon=True)
        thread.start()
        try:
            thread.join(self.timeout_s + 30.0)
        finally:
            lease.release()
        result = box.get("turn")
        run.lead_turn = {
            "agent": "site-lead",
            "wall_s": round(time.monotonic() - t0, 2),
            "tool_calls": session.calls,
            "turn": asdict(result) if result is not None else None,
        }
        state = "ok" if result is not None and result.ok else "failed"
        reply = _short(result.reply, 160) if result is not None else ""
        run.say(
            f"lead turn ended {state} after {run.lead_turn['wall_s']:.1f} s; {reply or ''}", "turn"
        )


__all__ = ["AgentSiteLead", "SiteLeadSession", "lead_brief"]

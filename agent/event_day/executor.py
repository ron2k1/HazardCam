"""Run executor that hands a run to the OpenClaw agent ``urban-mirror`` (D01).

Written on event day (2026-10-03, task D01). It implements the API's ``RunExecutor``
(``apps/api/services/runs.py``) and replaces the NON-AGENT dev-sequence harness the same
way: ``app.state.executor = OpenClawAgentExecutor(...)`` after ``create_app()``.

For one run it:

1. builds the leak guard, reduces the ``Scenario`` to its ``ModelScenarioView`` and drops
   the scenario;
2. opens a ``ToolSession`` and the D00 ``AgentPolicy`` over it;
3. takes the ``ToolGateway`` lease, so the ``mirror`` MCP tools reach this run only;
4. starts one agent turn with the policy's brief (``AgentLauncher``);
5. returns the final hypothesis as soon as the policy closes on a submit. If the turn
   ends without one, the policy abstains (``finalize``). If the agent never made a
   single call because the turn failed, the run fails at stage ``agent`` instead, so a
   broken runtime shows in the UI rather than as an abstention.

The lease is released when the agent's turn has ended, not when the run completes, so
an old turn can never call into the next run. Starting a turn inside NemoClaw/OpenShell
is the launcher's job: ``OpenClawCliLauncher`` takes the command prefix (D02 wires the
sandboxed one).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from apps.api.schemas import REPO_ROOT, Hypothesis, Scenario
from apps.api.services.gt_guard import GtGuard
from apps.api.services.media import frame_url
from inference.profiles import ModelProfile, load_profile
from tools.session import TOOL_NAMES, Emit, ToolSession

from .mcp_server import Lease, ToolGateway
from .policy import AGENT_ID, DEFAULT_BUDGET, AgentPolicy, AlertRoute, Budget, redact
from .registration import scrub_paths

logger = logging.getLogger(__name__)

HARNESS_ID = "openclaw-agent"
TURN_FILE = "agent_turn.json"
POLICY_FILE = "agent_policy.json"
MAX_REPLY_CHARS = 2000
MAX_ERROR_CHARS = 300


class AgentRunError(RuntimeError):
    """The agent could not run at all. ``stage`` is what ``run.failed`` reports."""

    def __init__(self, message: str, stage: str = "agent") -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class AgentTurn:
    """How one agent turn ended. ``reply`` is the agent's last text (its FINAL line)."""

    ok: bool
    reply: str = ""
    error: str | None = None
    duration_s: float = 0.0
    exit_code: int | None = None


class AgentLauncher(Protocol):
    """Runs one agent turn to its end. Must not raise for an agent-side failure."""

    def __call__(self, brief: str, *, run_id: str, timeout_s: float) -> AgentTurn: ...


def _short(text: str | None, limit: int = MAX_ERROR_CHARS) -> str | None:
    if text is None:
        return None
    return (redact(scrub_paths(text)) or "")[:limit]


def reply_text(stdout: str) -> str:
    """The agent's reply text from ``openclaw agent --json`` output (empty if none).

    The JSON shape differs between gateway and embedded runs, so this collects every
    ``text`` under a ``payloads`` list, else a top-level ``reply``/``text``.
    """
    try:
        doc = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        lines = [ln for ln in (stdout or "").splitlines() if ln.strip().startswith("{")]
        if not lines:
            return ""
        try:
            doc = json.loads(lines[-1])
        except json.JSONDecodeError:
            return ""
    texts: list[str] = []

    def walk(node: Any, under_payloads: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "payloads":
                    walk(value, True)
                elif key == "text" and under_payloads and isinstance(value, str):
                    texts.append(value)
                else:
                    walk(value, under_payloads)
        elif isinstance(node, list):
            for item in node:
                walk(item, under_payloads)

    walk(doc, False)
    if not texts and isinstance(doc, dict):
        for key in ("reply", "text"):
            if isinstance(doc.get(key), str):
                texts.append(doc[key])
    return "\n".join(t for t in texts if t.strip()).strip()


class OpenClawCliLauncher:
    """One ``openclaw agent`` turn as a subprocess.

    ``command`` is the prefix that runs the ``openclaw`` CLI: inside the sandbox that is
    ``openshell sandbox exec -n <sandbox> -- openclaw`` (D02), on the host a ``node``
    call to ``openclaw.mjs``. Each run gets its own session (``--session-key <run_id>``
    under ``--agent urban-mirror``), so no history carries over between runs. stdin is
    closed: ``openclaw agent`` waits on an open stdin when it is not a TTY.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        agent_id: str = AGENT_ID,
        local: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        kill_grace_s: float = 30.0,
    ) -> None:
        if not command:
            raise ValueError("command must name the openclaw CLI")
        self.command = list(command)
        self.agent_id = agent_id
        self.local = local
        self.env = dict(env) if env is not None else None
        self.cwd = cwd
        self.kill_grace_s = kill_grace_s

    def argv(self, brief: str, *, run_id: str, timeout_s: float) -> list[str]:
        argv = [
            *self.command,
            "agent",
            "--agent",
            self.agent_id,
            "--session-key",
            run_id,
            "--message",
            brief,
            "--json",
            "--timeout",
            str(max(1, int(timeout_s))),
        ]
        if self.local:
            argv.append("--local")
        return argv

    def __call__(self, brief: str, *, run_id: str, timeout_s: float) -> AgentTurn:
        started = time.monotonic()
        env = None if self.env is None else {**os.environ, **self.env}
        try:
            proc = subprocess.run(
                self.argv(brief, run_id=run_id, timeout_s=timeout_s),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_s + self.kill_grace_s,
                env=env,
                cwd=self.cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AgentTurn(
                ok=False,
                error=f"the agent turn exceeded {timeout_s:.0f} s",
                duration_s=time.monotonic() - started,
            )
        except OSError as exc:
            return AgentTurn(
                ok=False,
                error=_short(f"could not start openclaw: {type(exc).__name__}: {exc}"),
                duration_s=time.monotonic() - started,
            )
        duration = time.monotonic() - started
        reply = reply_text(proc.stdout)
        if proc.returncode != 0 or not reply:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            why = "exit code " + str(proc.returncode) if proc.returncode else "empty reply"
            return AgentTurn(
                ok=False,
                reply=_short(reply, MAX_REPLY_CHARS) or "",
                error=_short(f"{why}: {' | '.join(tail)}" if tail else why),
                duration_s=duration,
                exit_code=proc.returncode,
            )
        return AgentTurn(
            ok=True,
            reply=_short(reply, MAX_REPLY_CHARS) or "",
            duration_s=duration,
            exit_code=0,
        )


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("could not write %s", path.name, exc_info=True)


class OpenClawAgentExecutor:
    """``RunExecutor`` for the OpenClaw agent. ``pace_s`` is ignored: the agent's own
    model calls pace the run."""

    harness_id = HARNESS_ID

    def __init__(
        self,
        launcher: AgentLauncher,
        gateway: ToolGateway,
        *,
        media_root: Path = REPO_ROOT,
        budget: Budget = DEFAULT_BUDGET,
        alert_route: AlertRoute | None = None,
        grace_s: float = 60.0,
        bind_timeout_s: float = 120.0,
        poll_s: float = 0.2,
        profile_loader: Callable[[str], ModelProfile] = load_profile,
    ) -> None:
        self.launcher = launcher
        self.gateway = gateway
        self.media_root = media_root
        self.budget = budget
        self.alert_route = alert_route
        self.grace_s = grace_s
        self.bind_timeout_s = bind_timeout_s
        self.poll_s = poll_s
        self.profile_loader = profile_loader
        self.last_policy: AgentPolicy | None = None  # for tests and diagnostics

    def __call__(
        self, scenario: Scenario, profile_name: str, emit: Emit, run_dir: Path, pace_s: float
    ) -> Hypothesis:
        guard = GtGuard.for_scenario(scenario)  # blocks the withheld ids in agent replies
        view = scenario.model_view()
        del scenario
        run_id = run_dir.name
        profile = self.profile_loader(profile_name)
        session = ToolSession(
            view,
            profile,
            emit,
            run_dir=run_dir,
            frame_url=lambda camera_id, index: frame_url(run_id, camera_id, index),
            media_root=self.media_root,
        )
        policy = AgentPolicy(
            session, budget=self.budget, emit=emit, run_id=run_id, alert_route=self.alert_route
        )
        self.last_policy = policy
        lease = self.gateway.acquire(policy, guard=guard, timeout=self.bind_timeout_s)
        emit(
            "run.started",
            {
                "scenario_id": view.id,
                "profile": profile.profile,
                "camera_ids": session.camera_ids,
                "harness": HARNESS_ID,
            },
        )
        emit(
            "orchestrator.started",
            {"harness": HARNESS_ID, "agent": True, "sequence": list(TOOL_NAMES)},
        )
        turn_box: dict[str, AgentTurn] = {}
        timeout_s = self.budget.deadline_s + self.grace_s
        thread = threading.Thread(
            target=self._turn,
            args=(policy, lease, run_dir, timeout_s, turn_box),
            name=f"agent:{run_id}",
            daemon=True,
        )
        thread.start()

        give_up = time.monotonic() + timeout_s
        while not policy.wait_closed(self.poll_s):
            if not thread.is_alive() or time.monotonic() > give_up:
                break
        if not policy.closed:
            turn = turn_box.get("turn")
            calls = policy.summary()["calls"]
            if turn is not None and not turn.ok and calls == 0:
                _write_json(run_dir / POLICY_FILE, policy.summary())
                raise AgentRunError(f"the OpenClaw agent did not run ({turn.error})")
            if turn is None:
                why = f"The agent did not submit within {timeout_s:.0f} s."
            elif turn.ok:
                why = "The agent ended its turn without submitting a hypothesis."
            else:
                why = "The agent's turn failed before it submitted a hypothesis."
            policy.finalize(why)
        _write_json(run_dir / POLICY_FILE, policy.summary())
        final = policy.final_hypothesis
        if final is None:  # finalize always closes the run; this is a guard
            raise AgentRunError("the agent run closed without a hypothesis", stage="submit")
        return final

    def _turn(
        self,
        policy: AgentPolicy,
        lease: Lease,
        run_dir: Path,
        timeout_s: float,
        box: dict[str, AgentTurn],
    ) -> None:
        """Worker thread: one agent turn, then free the tool surface."""
        try:
            try:
                turn = self.launcher(
                    policy.brief(), run_id=policy.run_id or "", timeout_s=timeout_s
                )
            except Exception as exc:
                logger.warning("agent launcher failed", exc_info=True)
                turn = AgentTurn(ok=False, error=_short(f"{type(exc).__name__}: {exc}"))
            box["turn"] = turn
            policy.expire_alert()
            _write_json(run_dir / TURN_FILE, {"harness": HARNESS_ID, **asdict(turn)})
        finally:
            lease.release()


__all__ = [
    "HARNESS_ID",
    "AgentLauncher",
    "AgentRunError",
    "AgentTurn",
    "OpenClawAgentExecutor",
    "OpenClawCliLauncher",
    "reply_text",
]

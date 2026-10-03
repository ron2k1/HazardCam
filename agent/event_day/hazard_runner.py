"""Safety hazard reviews through the OpenClaw agent ``urban-mirror`` (event day, 2026-10-03).

Written on event day for the hazard agent task. ``AgentHazardRunner`` implements the
API's hazard review seam (``apps/api/services/hazards.py``):

    runner(video, output_root, *, source_name, refresh, progress) -> run_dir

``create_agent_app`` sets it as ``app.state.hazard_review_runner`` (name
``"openclaw-agent"``), so every live review on ``/hazards`` runs as one agent turn in
the NemoClaw sandbox instead of a direct Python call. For one clip it:

1. builds a ``HazardJobSession`` (``hazard_tools.py``) for that clip only and takes the
   ``ToolGateway`` lease, so the ``mirror__hazard_*`` tools reach this job and no other;
2. starts one OpenClaw turn with a short HAZARD BRIEF through the same launcher the
   run executor uses (``openshell sandbox exec -n ambient-mirror -- openclaw agent``);
3. serves the agent's calls: scan, then the local Qwen review and audit, then the worker
   summary. ``review_clip``'s numbered steps go to ``progress``; agent narration goes to
   ``progress(0, 6, text)`` in plain words;
4. writes ``agent_trace.json``, ``agent_summary.json`` (on a valid submit) and
   ``agent_turn.json`` into the run directory and returns it.

If the turn ends without a summary but the review finished, the run directory is kept
and the failure is recorded in the trace. It raises only if nothing ran.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .executor import AgentLauncher, AgentRunError, AgentTurn, _short
from .hazard_tools import (
    REVIEW,
    SCAN,
    SUBMIT,
    HazardJobSession,
    HazardTrace,
    ProgressFn,
    ReviewFn,
)
from .mcp_server import Lease, ToolGateway
from .registration import openclaw_name

logger = logging.getLogger(__name__)

RUNNER_NAME = "openclaw-agent"
TRACE_FILE = "agent_trace.json"
TURN_FILE = "agent_turn.json"
DEFAULT_TIMEOUT_S = 600.0


def hazard_brief(clip_id: str, run_id: str) -> str:
    """The one message that starts a hazard job. It names the clip id and nothing else
    about the clip: no file name, label or path."""
    scan, review, submit = (openclaw_name(t) for t in (SCAN, REVIEW, SUBMIT))
    return "\n".join(
        [
            "HAZARD BRIEF",
            f"job: {run_id}",
            "task: safety hazard review of one factory camera clip",
            f"clip_id: {clip_id}",
            "Follow the Safety hazard review section of AGENTS.md. Call, in this order:",
            f'  1. {scan} {{"clip_id": "{clip_id}"}}',
            f'  2. {review} {{"clip_id": "{clip_id}"}}',
            (
                f'  3. {submit} {{"clip_id": "{clip_id}", "headline": "...", '
                '"first_action": "...", "priority": "high|medium|low|none", '
                '"confirmed_finding_ids": [...]}'
            ),
            "Use only findings the review returns. When the submit succeeds, reply with one line:",
            f"FINAL hazard clip={clip_id} priority=<priority> confirmed=<count>",
        ]
    )


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("could not write %s", path.name, exc_info=True)


def _default_review_fn() -> ReviewFn:
    from hazards.pipeline import review_clip

    return review_clip


class AgentHazardRunner:
    """The hazard review seam, served by the OpenClaw agent."""

    name = RUNNER_NAME

    def __init__(
        self,
        launcher: AgentLauncher,
        gateway: ToolGateway,
        *,
        review_fn: ReviewFn | None = None,
        profile: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        bind_timeout_s: float = 180.0,
        grace_s: float = 30.0,
        poll_s: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
        concurrent: bool = False,
    ) -> None:
        self.launcher = launcher
        self.gateway = gateway
        self._review_fn = review_fn
        self.profile = profile
        self.timeout_s = timeout_s
        self.bind_timeout_s = bind_timeout_s
        self.grace_s = grace_s
        self.poll_s = poll_s
        self.clock = clock
        # concurrent: each clip takes its own keyed gateway lease (key = clip_id), so the
        # six wall checkers run side by side; otherwise one hazard turn at a time.
        self.concurrent = concurrent
        self.last_session: HazardJobSession | None = None  # for tests and diagnostics

    @property
    def review_fn(self) -> ReviewFn:
        if self._review_fn is None:
            self._review_fn = _default_review_fn()
        return self._review_fn

    def __call__(
        self,
        video: Path,
        output_root: Path,
        *,
        source_name: str,
        refresh: bool = False,
        progress: ProgressFn | None = None,
        profile: str | None = None,
        **_ignored: Any,
    ) -> Path:
        clip_id = source_name
        run_id = f"hazard-{clip_id}-{uuid.uuid4().hex[:8]}"
        trace = HazardTrace(progress, clock=self.clock)
        session = HazardJobSession(
            clip_id,
            Path(video),
            Path(output_root),
            review_fn=self.review_fn,
            trace=trace,
            run_id=run_id,
            profile=profile or self.profile,
            refresh=refresh,
            progress=progress,
        )
        self.last_session = session
        trace.say("The safety agent picked up this clip and is planning its check")
        if self.concurrent:
            lease = self.gateway.acquire_keyed(session, clip_id, timeout=self.bind_timeout_s)
        else:
            lease = self.gateway.acquire(session, timeout=self.bind_timeout_s)
        trace.tool("turn", f"agent turn started: {run_id} (timeout {self.timeout_s:.0f} s)")

        box: dict[str, AgentTurn] = {}
        thread = threading.Thread(
            target=self._turn,
            args=(hazard_brief(clip_id, run_id), run_id, lease, box),
            name=f"hazard-agent:{clip_id}",
            daemon=True,
        )
        thread.start()
        give_up = self.clock() + self.timeout_s + self.grace_s
        while not session.wait_closed(self.poll_s):
            if not thread.is_alive() or self.clock() > give_up:
                break
        if session.closed:
            thread.join(self.grace_s)  # the agent's FINAL line follows the submit
        turn = box.get("turn")
        self._record_turn(trace, turn)

        run_dir = session.run_dir
        if not session.closed:
            if turn is None:
                why = f"the agent did not submit a summary within {self.timeout_s:.0f} s"
            elif turn.ok:
                why = "the agent ended its turn without submitting a summary"
            else:
                why = f"the agent turn failed before a summary ({turn.error})"
            trace.tool("turn", f"no summary: {why}")
            if run_dir is not None:
                trace.say("The safety agent did not finish its summary; the review is saved")
            elif session.scan_dir is not None:
                trace.say("The safety agent stopped after the camera scan")
                run_dir = session.scan_dir
            else:
                logger.warning("hazard agent for %s did not run: %s", clip_id, why)
                raise AgentRunError(f"the OpenClaw agent did not run the hazard review ({why})")
        assert run_dir is not None
        _write_json(run_dir / TRACE_FILE, trace.snapshot())
        _write_json(
            run_dir / TURN_FILE,
            {
                "harness": RUNNER_NAME,
                "job": run_id,
                "clip_id": clip_id,
                "submitted": session.closed,
                "session": session.stats(),
                "turn": asdict(turn) if turn is not None else None,
            },
        )
        return run_dir

    def _record_turn(self, trace: HazardTrace, turn: AgentTurn | None) -> None:
        if turn is None:
            trace.tool("turn", "agent turn still running when the job ended")
            return
        state = "ok" if turn.ok else f"failed ({turn.error})"
        reply = _short(turn.reply, 200) or ""
        trace.tool(
            "turn",
            f"agent turn ended {state} after {turn.duration_s:.1f} s"
            + (f"; reply: {reply}" if reply else ""),
        )

    def _turn(self, brief: str, run_id: str, lease: Lease, box: dict[str, AgentTurn]) -> None:
        """Worker thread: one agent turn, then free the tool surface."""
        try:
            try:
                box["turn"] = self.launcher(brief, run_id=run_id, timeout_s=self.timeout_s)
            except Exception as exc:
                logger.warning("hazard agent launcher failed", exc_info=True)
                box["turn"] = AgentTurn(ok=False, error=_short(f"{type(exc).__name__}: {exc}"))
        finally:
            lease.release()


__all__ = ["RUNNER_NAME", "AgentHazardRunner", "hazard_brief"]

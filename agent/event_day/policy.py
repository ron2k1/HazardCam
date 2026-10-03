"""Bounded tool policy for the event-day OpenClaw agent ``urban-mirror``.

Written on event day (2026-10-03, task D00). The OpenClaw agent chooses which tool to
call next; this module decides whether that call may run. It wraps one run's
``tools.session.ToolSession`` and is the only object the D01 tool registration exposes
to the agent:

* Only the seven tools in ``contracts/tools.schema.json`` exist. Their arguments are
  checked against that contract by the session, which also reports bad calls.
* A ``camera_id`` must be a visible camera of the run (the session's
  ``ModelScenarioView``). A refusal lists the allowed ids and never repeats the
  rejected one.
* Calls are capped per tool, per camera and in total, and the run has a deadline.
  Once a run is out of budget, only ``submit_hypothesis`` is accepted.
* A successful ``submit_hypothesis`` closes the run. Every later call is refused.
* A submitted claim may only weaken the reasoner's hypothesis, and it keeps every one
  of the reasoner's alternatives and limitations. An abstention the agent writes is
  rebuilt in the policy's own form (``normalize_abstention``). The abstention rules
  below run on every submission, before the deterministic gate in ``tools/submit.py``.
* ``finalize`` closes a run the agent left without a submission by abstaining.
* Telegram alert (operator addendum): a run that closes on a known event type at or
  above ``ABSTAIN_BELOW`` gets exactly one alert, composed here from the final
  hypothesis and the evidence bundle. The agent sends it with OpenClaw's ``message``
  tool; ``authorize_alert`` is the guard D01 wires in front of that tool. OpenClaw
  2026.7.1 merges a hook's params into the agent's instead of replacing them, so the
  guard refuses any call that carries a key besides ``action``, ``channel``, ``target``
  and ``message``. The text that goes out is always the policy's and only one send per
  run is granted. A failed send is recorded as skipped. It never changes the
  hypothesis or the run.

The policy never computes times, geometry or hypotheses itself: those stay in the
tested tools. It holds no ``Scenario`` and no path to media or labels, and it imports
nothing from ``eval/``.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from pydantic import ValidationError

from apps.api.schemas import UNKNOWN, Alternative, EvidenceBundle, Hypothesis, ModelScenarioView
from inference.vocab import EVENT_TYPES
from tools.session import (
    TOOL_NAMES,
    UNKNOWN_TOOL,
    Emit,
    ToolCallError,
    ToolSession,
    tool_call_error,
)
from tools.submit import NOT_DIRECTLY_VISIBLE

logger = logging.getLogger(__name__)

AGENT_ID = "urban-mirror"
HARNESS_ID = "openclaw-agent"

SUBMIT = "submit_hypothesis"
CAMERA_TOOLS = frozenset({"sample_video", "inspect_camera", "get_supporting_frames"})
NOT_VISIBLE = "not_visible"
REFUSAL_PREFIX = "policy"

# A claim below this confidence is not worth asserting: the agent abstains instead.
ABSTAIN_BELOW = 0.3
# Confidence of an abstention the policy builds (the gate uses the same ceiling).
ABSTENTION_CONFIDENCE = 0.2
# An alternative this close to the main claim is reported as a limitation.
CLOSE_MARGIN = 0.1

# -- Telegram alert --------------------------------------------------------------------
# The one OpenClaw tool, action and channel the alert may use (agent.json allows no other).
ALERT_TOOL = "message"
ALERT_ACTION = "send"
ALERT_CHANNEL = "telegram"
# The only keys a granted ``message`` call may carry. OpenClaw merges the hook's params
# over the agent's ({...agent, ...hook}), so any other key the agent typed (media,
# attachments, buttons, targets, dryRun, ...) would reach the send: such a call is refused.
ALERT_PARAM_KEYS = frozenset({"action", "channel", "target", "message"})
# The same threshold as abstention: anything the agent would assert is worth an alert.
ALERT_MIN_CONFIDENCE = ABSTAIN_BELOW
ALERT_MAX_CAMERAS = 6
MAX_ALERT_REASON_CHARS = 160

# Alert states. "pending": the run is open. "not_due": the run closed without an alertable
# claim. "due": composed and handed to the agent. "sending": the one send was granted.
# "sent" / "skipped": final. A failed or impossible send is "skipped", never "failed".
ALERT_PENDING = "pending"
ALERT_NOT_DUE = "not_due"
ALERT_DUE = "due"
ALERT_SENDING = "sending"
ALERT_SENT = "sent"
ALERT_SKIPPED = "skipped"

_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
# A Telegram chat id, @channel username, or forum topic target. A bot token
# (``<digits>:<secret>``) does not match, so one pasted by mistake is rejected.
_TELEGRAM_TARGET = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})(:topic:\d{1,10})?$")
_REGION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_URL = re.compile(r"(?i)\b(?:https?|tg|ftp)://\S+|\bwww\.\S+")
_BOT_TOKEN = re.compile(r"(?i)\b(?:bot)?\d{5,}:[A-Za-z0-9_-]{20,}")


@dataclass(frozen=True)
class Budget:
    """Hard bounds for one run. D03 may tune the numbers; the rules stay."""

    per_camera_calls: int = 2  # each of sample_video / inspect_camera / get_supporting_frames
    fusion_calls: int = 3  # each of correlate_observations / triangulate_region
    reason_calls: int = 2
    submit_calls: int = 2
    spare_calls: int = 12
    max_consecutive_failures: int = 4
    deadline_s: float = 900.0

    def total_calls(self, cameras: int) -> int:
        """A clean run takes at most 3 x cameras + 4 calls; this leaves room to recover."""
        return 4 * cameras + self.spare_calls

    def tool_cap(self, name: str) -> int:
        if name in CAMERA_TOOLS:
            return self.per_camera_calls
        if name in ("correlate_observations", "triangulate_region"):
            return self.fusion_calls
        if name == "reason_hypothesis":
            return self.reason_calls
        return self.submit_calls


DEFAULT_BUDGET = Budget()


@dataclass(frozen=True)
class ToolOutcome:
    """What one agent tool call produced. ``refused`` means the session never ran it.

    ``result`` is exactly the contract's ``$defs/<tool>_result``. The closing
    ``submit_hypothesis`` also carries ``alert``, the agent's instruction for its one
    Telegram send, next to the result rather than inside it.
    """

    tool: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    refused: bool = False
    alert: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        if self.ok:
            out: dict[str, Any] = {"ok": True, "result": self.result}
            if self.alert is not None:
                out["alert"] = self.alert
            return out
        return {"ok": False, "error": self.error, "refused": self.refused}


@dataclass(frozen=True)
class AlertRoute:
    """Where a run's alert goes: a Telegram chat id, ``@channel`` or forum topic target.

    The runner builds it from operator configuration. It carries no credential: the bot
    token lives only in the OpenShell gateway credential store.
    """

    target: str
    channel: str = ALERT_CHANNEL

    def __post_init__(self) -> None:
        if self.channel != ALERT_CHANNEL:
            raise ValueError(f"alerts go to {ALERT_CHANNEL!r} only")
        if not _TELEGRAM_TARGET.match(self.target):
            raise ValueError("alert target must be a Telegram chat id, @channel or topic target")


@dataclass(frozen=True)
class AlertGrant:
    """``authorize_alert``'s answer.

    When allowed, D01's hook returns ``arguments`` as its params. OpenClaw merges them
    over the agent's key by key; the guard has already refused any call that carries
    another key, so the call that runs is exactly ``arguments``.
    """

    allowed: bool
    arguments: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class _AlertState:
    status: str = ALERT_PENDING
    reason: str | None = None
    event_type: str | None = None
    text: str | None = None
    arguments: dict[str, Any] | None = None
    grants: int = 0
    refused: int = 0


@dataclass
class _Ledger:
    calls: int = 0
    refusals: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    per_tool: Counter[str] = field(default_factory=Counter)
    per_camera: Counter[tuple[str, str]] = field(default_factory=Counter)
    trace: list[dict[str, Any]] = field(default_factory=list)


# -- abstention rules (pure) -----------------------------------------------------------


def abstain(claim: Hypothesis | None, why: str) -> Hypothesis:
    """An abstention that keeps ``claim`` (if any) visible as an alternative."""
    if claim is None:
        return Hypothesis(
            event_type=UNKNOWN,
            region=UNKNOWN,
            confidence=0.0,
            evidence_ids=[],
            reason=why,
            alternatives=[],
            limitations=[why, NOT_DIRECTLY_VISIBLE],
        )
    alternatives = list(claim.alternatives)
    if not claim.abstained:
        alternatives.insert(
            0, Alternative(event_type=claim.event_type, confidence=claim.confidence)
        )
        reason = f"{why} The reasoner's claim ({claim.event_type} in {claim.region}) is kept as an alternative."
    else:
        reason = f"{why} {claim.reason}".strip()
    return Hypothesis(
        event_type=UNKNOWN,
        region=UNKNOWN,
        confidence=min(claim.confidence, ABSTENTION_CONFIDENCE),
        evidence_ids=list(claim.evidence_ids),
        reason=reason,
        alternatives=alternatives,
        limitations=[*claim.limitations, why],
    )


def apply_abstention_rules(claim: Hypothesis) -> Hypothesis:
    """The agent's own submission rules, applied before the deterministic gate.

    1. A claim below ``ABSTAIN_BELOW`` confidence becomes an abstention.
    2. A claim the reasoner ranked at or below one of its own alternatives becomes an
       abstention: the evidence does not single it out.
    3. A claim with no alternatives gets a limitation saying none were ranked.
    4. An alternative within ``CLOSE_MARGIN`` of the claim gets a limitation.

    Abstentions pass through unchanged. Rules 1 and 2 keep the claim as an alternative.
    """
    if claim.abstained:
        return claim
    if claim.confidence < ABSTAIN_BELOW:
        return abstain(
            claim,
            f"The reasoner's confidence {claim.confidence:.2f} is below the agent's "
            f"abstention floor of {ABSTAIN_BELOW:.2f}.",
        )
    rivals = sorted(
        (a for a in claim.alternatives if a.event_type != claim.event_type),
        key=lambda a: (-a.confidence, a.event_type),
    )
    if rivals and rivals[0].confidence >= claim.confidence:
        top = rivals[0]
        return abstain(
            claim,
            f"The reasoner ranked alternative {top.event_type!r} ({top.confidence:.2f}) at or "
            f"above its own claim ({claim.confidence:.2f}).",
        )
    notes: list[str] = []
    if not rivals:
        notes.append("The reasoner ranked no alternative explanation.")
    elif round(claim.confidence - rivals[0].confidence, 4) < CLOSE_MARGIN:
        top = rivals[0]
        notes.append(
            f"Alternative {top.event_type!r} ({top.confidence:.2f}) is within {CLOSE_MARGIN:.2f} "
            "of the main claim; the evidence separates them only weakly."
        )
    notes = [n for n in notes if n not in claim.limitations]
    if not notes:
        return claim
    return claim.model_copy(update={"limitations": [*claim.limitations, *notes]})


def weakening_violations(claim: Hypothesis, raw: Hypothesis | None) -> list[str]:
    """Why ``claim`` is not a weakening of the reasoner's hypothesis ``raw`` (empty if it is).

    The agent coordinates; it does not conclude. An explicit hypothesis may abstain or
    soften the reasoner's claim, never replace or strengthen it. Dropping or lowering one
    of the reasoner's alternatives would strengthen the claim against its rivals and hide
    them from the abstention rules, so a non-abstaining claim keeps every alternative at
    the reasoner's confidence, and every limitation. An abstention's alternatives are
    only checked for their source here: ``normalize_abstention`` rebuilds them from
    ``raw``.
    """
    problems: list[str] = []
    allowed_alts: dict[str, float] = {}
    if raw is not None:
        for alt in raw.alternatives:
            allowed_alts[alt.event_type] = max(
                allowed_alts.get(alt.event_type, 0.0), alt.confidence
            )
    raw_ids = set(raw.evidence_ids) if raw is not None else set()

    if not claim.abstained:
        if raw is None:
            return [
                (
                    "only an abstention (event_type 'unknown') may be submitted before "
                    "reason_hypothesis has returned a hypothesis"
                )
            ]
        if claim.event_type != raw.event_type:
            problems.append(f"event_type must stay {raw.event_type!r}")
        if claim.region not in (raw.region, UNKNOWN):
            problems.append(f"region must stay {raw.region!r} or become 'unknown'")
        if claim.confidence > raw.confidence:
            problems.append(f"confidence may not exceed the reasoner's {raw.confidence:.2f}")
        kept: dict[str, float] = {}
        for alt in claim.alternatives:
            kept[alt.event_type] = max(kept.get(alt.event_type, 0.0), alt.confidence)
        if any(
            kept.get(event_type, -1.0) < confidence
            for event_type, confidence in allowed_alts.items()
            if event_type != claim.event_type
        ):
            problems.append(
                "alternatives must keep every one of the reasoner's alternatives at its confidence"
            )
        if any(lim not in claim.limitations for lim in raw.limitations):
            problems.append("limitations must keep every one of the reasoner's limitations")
    else:
        if claim.region != UNKNOWN:
            problems.append("an abstention's region must be 'unknown'")
        if raw is not None and not raw.abstained:
            allowed_alts[raw.event_type] = max(
                allowed_alts.get(raw.event_type, 0.0), raw.confidence
            )

    if not set(claim.evidence_ids) <= raw_ids:
        problems.append("evidence_ids must come from the reasoner's evidence_ids")
    for alt in claim.alternatives:
        if alt.event_type == claim.event_type:
            continue
        if alt.event_type not in allowed_alts:
            problems.append("alternatives must come from the reasoner's hypothesis")
            break
        if alt.confidence > allowed_alts[alt.event_type]:
            problems.append("an alternative's confidence may not exceed the reasoner's")
            break
    return problems


def normalize_abstention(claim: Hypothesis, raw: Hypothesis | None) -> Hypothesis:
    """An abstention the agent wrote, rebuilt in the policy's own form ``abstain(raw, …)``.

    The agent says why it abstains; the policy decides what the abstention holds. The
    result keeps the reasoner's claim (as an alternative), its alternatives, evidence ids
    and limitations, takes at most ``ABSTENTION_CONFIDENCE``, and adds the agent's reason
    and limitations as limitations. The agent's confidence, evidence ids and
    alternatives are not used.
    """
    why = " ".join(claim.reason.split()) or "The agent abstained."
    out = abstain(raw, why)
    extra = [lim for lim in dict.fromkeys(claim.limitations) if lim not in out.limitations]
    if not extra:
        return out
    return out.model_copy(update={"limitations": [*out.limitations, *extra]})


# -- Telegram alert rules (pure) -------------------------------------------------------


def alert_decision(final: Hypothesis) -> str | None:
    """Why the submitted hypothesis ``final`` gets no alert, or ``None`` when it does."""
    if final.abstained:
        return "the run abstained"
    if final.event_type not in EVENT_TYPES:
        return f"{final.event_type!r} is not an abnormal event type"
    if final.confidence < ALERT_MIN_CONFIDENCE:
        return (
            f"confidence {final.confidence:.2f} is below the alert threshold "
            f"{ALERT_MIN_CONFIDENCE:.2f}"
        )
    return None


def cited_spans(final: Hypothesis, bundle: EvidenceBundle) -> list[tuple[str, float, float]]:
    """``(camera_id, t_start, t_end)`` per camera the hypothesis cites, in bundle camera
    order. Times are scenario seconds, the span of that camera's cited evidence."""
    cited = set(final.evidence_ids)
    spans: dict[str, tuple[float, float]] = {}
    for item in bundle.evidence:
        if item.id in cited:
            lo, hi = spans.get(item.camera_id, (item.t_start, item.t_end))
            spans[item.camera_id] = (min(lo, item.t_start), max(hi, item.t_end))
    order = [c.id for c in bundle.cameras]
    ranked = sorted(spans, key=lambda c: (order.index(c) if c in order else len(order), c))
    return [(c, *spans[c]) for c in ranked]


def unsafe_alert_text(text: str) -> bool:
    """True when ``text`` holds a URL or something shaped like a bot token."""
    return bool(_URL.search(text) or _BOT_TOKEN.search(text))


def compose_alert(final: Hypothesis, bundle: EvidenceBundle, run_id: str) -> str:
    """The alert text: event type, confidence, coarse region, the cited cameras with
    their times, and the run id. Built only from model-view data, so it holds no ground
    truth; it holds no frames, URLs or tokens either (checked, ``ValueError`` if so)."""
    if not _RUN_ID.match(run_id):
        raise ValueError("run id has unexpected characters")
    region = final.region if _REGION_ID.match(final.region) else UNKNOWN
    spans = cited_spans(final, bundle)
    cameras = "; ".join(f"{c} t={a:.1f}-{b:.1f}s" for c, a, b in spans[:ALERT_MAX_CAMERAS])
    if len(spans) > ALERT_MAX_CAMERAS:
        cameras += f"; +{len(spans) - ALERT_MAX_CAMERAS} more"
    text = "\n".join(
        [
            "Urban Mirror alert",
            f"event: {final.event_type}",
            f"confidence: {final.confidence:.2f}",
            f"region: {region} (coarse)",
            f"cameras: {cameras or 'none cited'}",
            f"run: {run_id}",
            "Inferred from the visible cameras; the event itself was not directly observed.",
        ]
    )
    if unsafe_alert_text(text):
        raise ValueError("alert text failed the content check")
    return text


def redact(message: str | None) -> str | None:
    """A delivery error safe for logs and artifacts: one line, no URLs, no tokens."""
    if message is None:
        return None
    line = " ".join(str(message).split())
    line = _BOT_TOKEN.sub("<redacted>", _URL.sub("<url>", line))
    return line[:MAX_ALERT_REASON_CHARS]


def run_brief(
    view: ModelScenarioView,
    budget: Budget = DEFAULT_BUDGET,
    *,
    run_id: str | None = None,
    alert_armed: bool = False,
) -> str:
    """The message that starts one agent run. It carries model-view data only."""
    lines = ["RUN BRIEF"]
    if run_id:
        lines.append(f"run: {run_id}")
    lines.append(f"scenario: {view.id}")
    if view.title:
        lines.append(f"title: {view.title}")
    lines.append("visible cameras, in order (the only cameras that exist for this run):")
    for cam in view.cameras:
        label = f" - {cam.label}" if cam.label else ""
        lines.append(f"  {cam.id}{label}")
    lines += [
        (
            f"budget: {budget.total_calls(len(view.cameras))} tool calls, {budget.deadline_s:.0f} s;"
            f" at most {budget.per_camera_calls} calls per camera per tool."
        ),
        "alert: Telegram alert armed; submit_hypothesis's reply says whether to send it."
        if alert_armed
        else "alert: none for this run; never call the message tool.",
        "Follow the playbook in AGENTS.md. Start with sample_video for the first camera.",
    ]
    return "\n".join(lines)


# -- the guard -------------------------------------------------------------------------


class AgentPolicy:
    """Runs agent tool calls against one ``ToolSession`` within the bounds above.

    ``call`` never raises for a bad call: it returns a ``ToolOutcome`` whose ``error``
    says how to continue. When ``emit`` is given, a refused call still shows in the
    agent trace as a failed ``tool.started`` / ``tool.completed`` pair (call ids
    ``policy_NNN``), just as the session shows the calls it rejects. Once the runner has
    completed the run, ``emit`` raises; the refusal is then still returned and kept in
    ``summary()``, only not emitted.

    The run's result is final once the policy closes (``wait_closed``): the runner
    completes the run then, without waiting for the alert or the agent's last reply.
    ``alert_listener`` gets ``alert_summary()`` on every alert state change; it runs
    outside the policy lock and its errors are logged, never raised.
    """

    def __init__(
        self,
        session: ToolSession,
        *,
        budget: Budget = DEFAULT_BUDGET,
        emit: Emit | None = None,
        clock: Callable[[], float] = time.monotonic,
        run_id: str | None = None,
        alert_route: AlertRoute | None = None,
        alert_listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if run_id is not None and not _RUN_ID.match(run_id):
            raise ValueError("run id has unexpected characters")
        self.session = session
        self.budget = budget
        self.run_id = run_id
        self.alert_route = alert_route
        self._emit = emit
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._closed_event = threading.Event()
        self._refusal_ids = count(1)
        self._ledger = _Ledger()
        self._alert = _AlertState()
        self._alert_listener = alert_listener
        self.closed = False
        self.stop_reason: str | None = None
        self.finalized_by_policy = False

    # -- read-only state ----------------------------------------------------------------

    @property
    def allowed_cameras(self) -> tuple[str, ...]:
        return tuple(self.session.camera_ids)

    @property
    def total_calls(self) -> int:
        return self.budget.total_calls(len(self.allowed_cameras))

    @property
    def final_hypothesis(self) -> Hypothesis | None:
        """The submitted hypothesis once the run is closed, else ``None``."""
        return self.session.hypothesis if self.closed else None

    @property
    def alert_armed(self) -> bool:
        return self.alert_route is not None and self.run_id is not None

    def elapsed_s(self) -> float:
        return self._clock() - self._started

    def brief(self) -> str:
        """The run brief for this policy's session (see ``run_brief``)."""
        return run_brief(
            self.session.view, self.budget, run_id=self.run_id, alert_armed=self.alert_armed
        )

    def wait_closed(self, timeout: float | None = None) -> bool:
        """Block until the run has a final hypothesis (or ``timeout``); True if closed."""
        return self._closed_event.wait(timeout)

    def alert_summary(self) -> dict[str, Any]:
        """The alert's state for artifacts and the UI. Holds no chat id and no token."""
        alert = self._alert
        return {
            "channel": ALERT_CHANNEL,
            "armed": self.alert_armed,
            "status": alert.status,
            "reason": alert.reason,
            "event_type": alert.event_type,
            "text": alert.text,
            "grants": alert.grants,
            "refused": alert.refused,
        }

    def summary(self) -> dict[str, Any]:
        """Telemetry for run artifacts. Camera ids in it are visible ids or ``not_visible``."""
        ledger = self._ledger
        return {
            "agent": AGENT_ID,
            "run_id": self.run_id,
            "alert": self.alert_summary(),
            "calls": ledger.calls,
            "refusals": ledger.refusals,
            "failures": ledger.failures,
            "per_tool": dict(ledger.per_tool),
            "total_calls_allowed": self.total_calls,
            "deadline_s": self.budget.deadline_s,
            "elapsed_s": round(self.elapsed_s(), 3),
            "closed": self.closed,
            "finalized_by_policy": self.finalized_by_policy,
            "stop_reason": self.stop_reason,
            "trace": list(ledger.trace),
        }

    # -- the one entry point ------------------------------------------------------------

    def call(self, name: Any, arguments: Any = None) -> ToolOutcome:
        with self._lock:
            outcome = self._call(name, {} if arguments is None else arguments)
        if outcome.alert is not None:
            self._notify_alert()
        return outcome

    def _call(self, name: Any, arguments: Any) -> ToolOutcome:
        self._ledger.calls += 1
        tool = name if name in TOOL_NAMES else UNKNOWN_TOOL

        if self.closed:
            return self._refuse(
                tool,
                arguments,
                "the run is closed: a hypothesis was already submitted. Call no more of "
                "these tools. Send the alert only if the submit reply said send: true and "
                "you have not called message yet; then reply with the final line.",
            )
        if tool_call_error(name, arguments) is not None:
            # The session owns contract errors: it reports them from the schema alone.
            return self._forward(tool, name, arguments, count_against_caps=False)

        stopped = self._out_of_budget()
        if stopped and name != SUBMIT:
            return self._refuse(
                tool,
                arguments,
                f"the run is out of budget ({stopped}). Only submit_hypothesis is accepted "
                "now: call it with no arguments to submit the reasoner's hypothesis, or with "
                "an abstention.",
            )

        camera_id = arguments.get("camera_id")
        if name in CAMERA_TOOLS and camera_id not in self.allowed_cameras:
            return self._refuse(
                tool,
                arguments,
                "camera_id is not a visible camera of this run; use one of: "
                + ", ".join(self.allowed_cameras),
            )

        cap = self.budget.tool_cap(name)
        used = (
            self._ledger.per_camera[(name, camera_id)]
            if name in CAMERA_TOOLS
            else self._ledger.per_tool[name]
        )
        if used >= cap:
            scope = f" for camera {camera_id}" if name in CAMERA_TOOLS else ""
            return self._refuse(
                tool,
                arguments,
                f"{name} has reached its limit of {cap} call(s){scope}. Continue with the "
                "next playbook step, or submit.",
            )

        if name == SUBMIT:
            vetted = self._vet_submission(arguments)
            if isinstance(vetted, str):
                return self._refuse(tool, arguments, vetted)
            arguments = vetted
        return self._forward(tool, name, arguments, count_against_caps=True)

    # -- helpers ------------------------------------------------------------------------

    def _out_of_budget(self) -> str | None:
        if self.stop_reason is None:
            if self.elapsed_s() > self.budget.deadline_s:
                self.stop_reason = f"the {self.budget.deadline_s:.0f} s deadline has passed"
            elif self._ledger.calls > self.total_calls:
                self.stop_reason = f"the limit of {self.total_calls} tool calls is reached"
        return self.stop_reason

    def _shown_camera(self, arguments: Any) -> str | None:
        if not isinstance(arguments, dict) or "camera_id" not in arguments:
            return None
        camera_id = arguments["camera_id"]
        return camera_id if camera_id in self.allowed_cameras else NOT_VISIBLE

    def _note(self, tool: str, arguments: Any, outcome: ToolOutcome) -> ToolOutcome:
        ledger = self._ledger
        if outcome.ok:
            ledger.consecutive_failures = 0
        else:
            ledger.failures += 0 if outcome.refused else 1
            ledger.refusals += 1 if outcome.refused else 0
            ledger.consecutive_failures += 1
            if (
                self.stop_reason is None
                and ledger.consecutive_failures >= self.budget.max_consecutive_failures
            ):
                self.stop_reason = f"{ledger.consecutive_failures} failed or refused calls in a row"
        entry: dict[str, Any] = {
            "n": ledger.calls,
            "tool": tool,
            "ok": outcome.ok,
            "refused": outcome.refused,
            "t_s": round(self.elapsed_s(), 3),
        }
        shown = self._shown_camera(arguments)
        if shown is not None:
            entry["camera_id"] = shown
        if outcome.error:
            entry["error"] = outcome.error
        ledger.trace.append(entry)
        return outcome

    def _refuse(self, tool: str, arguments: Any, message: str) -> ToolOutcome:
        error = f"refused by policy: {message}"
        if self._emit is not None:
            call_id = f"{REFUSAL_PREFIX}_{next(self._refusal_ids):03d}"
            args_summary: dict[str, Any] = {"refused": True}
            shown = self._shown_camera(arguments)
            if shown is not None:
                args_summary["camera_id"] = shown
            try:
                self._emit(
                    "tool.started",
                    {"call_id": call_id, "tool": tool, "args_summary": args_summary},
                )
                self._emit(
                    "tool.completed",
                    {
                        "call_id": call_id,
                        "tool": tool,
                        "ok": False,
                        "latency_ms": 0.0,
                        "result_summary": {},
                        "error": error,
                    },
                )
            except Exception:  # best effort: e.g. the runner already published run.complete
                level = logging.DEBUG if self.closed else logging.WARNING
                logger.log(level, "refusal %s was not emitted", call_id, exc_info=True)
        return self._note(tool, arguments, ToolOutcome(tool, ok=False, error=error, refused=True))

    def _forward(
        self, tool: str, name: Any, arguments: Any, *, count_against_caps: bool
    ) -> ToolOutcome:
        if count_against_caps:
            if name in CAMERA_TOOLS:
                self._ledger.per_camera[(name, arguments["camera_id"])] += 1
            self._ledger.per_tool[name] += 1
        try:
            result = self.session.call_tool(name, arguments)
        except ToolCallError as exc:
            return self._note(tool, arguments, ToolOutcome(tool, ok=False, error=str(exc)))
        alert = None
        if name == SUBMIT:
            alert = self._close()
        return self._note(tool, arguments, ToolOutcome(tool, ok=True, result=result, alert=alert))

    def _vet_submission(self, arguments: dict[str, Any]) -> dict[str, Any] | str:
        """The arguments to submit with, or why the submission is refused."""
        raw = self.session.raw_hypothesis
        if "hypothesis" in arguments:
            try:
                claim = Hypothesis.model_validate(arguments["hypothesis"])
            except ValidationError:
                return arguments  # the session reports it from the contract
            problems = weakening_violations(claim, raw)
            if problems:
                return (
                    "a submitted hypothesis may only weaken the reasoner's: "
                    + "; ".join(problems)
                    + ". Submit with no arguments to keep the reasoner's hypothesis, or submit "
                    "event_type 'unknown' with region 'unknown' to abstain."
                )
            if claim.abstained:
                claim = normalize_abstention(claim, raw)
        elif raw is None:
            return arguments  # the session says which tool has to run first
        else:
            claim = raw
        vetted = apply_abstention_rules(claim)
        if vetted is claim and "hypothesis" not in arguments:
            return arguments
        return {"hypothesis": vetted.model_dump(mode="json")}

    # -- closing a run ------------------------------------------------------------------

    def finalize(
        self, why: str = "The agent ended its turn without submitting a hypothesis."
    ) -> Hypothesis:
        """The run's final hypothesis, abstaining if the agent never submitted one.

        With an evidence bundle, the abstention goes through ``submit_hypothesis`` (the
        gate, with its events). Without one there is nothing to gate against, so the
        bare abstention is returned for ``run.complete``.
        """
        with self._lock:
            if self.session.hypothesis is not None:
                return self.session.hypothesis
            self.finalized_by_policy = True
            claim = abstain(self.session.raw_hypothesis, why)
            if self.session.bundle is not None:
                try:
                    claim = self.session.submit_hypothesis(claim)
                except ToolCallError:
                    pass
            self._close(claim)
        self._notify_alert()
        return claim

    def _close(self, final: Hypothesis | None = None) -> dict[str, Any]:
        """Close the run on its final hypothesis and settle the alert. Caller holds the
        lock; the result is the agent's alert instruction for the submit reply."""
        final = final if final is not None else self.session.hypothesis
        self.closed = True
        alert = self._alert
        why = alert_decision(final) if final is not None else "the run has no hypothesis"
        if why is not None:
            alert.status = ALERT_NOT_DUE
        else:
            alert.event_type = final.event_type
            if not self.alert_armed:
                why = "no alert channel is configured for this run"
            elif self.session.bundle is None:
                why = "the run has no evidence bundle to cite"
            else:
                try:
                    alert.text = compose_alert(final, self.session.bundle, self.run_id)
                except ValueError as exc:
                    why = f"the alert could not be composed ({exc})"
            alert.status = ALERT_SKIPPED if why else ALERT_DUE
        self._closed_event.set()
        if why is not None:
            alert.reason = why
            return {"send": False, "reason": f"No alert for this run: {why}. Do not call message."}
        alert.arguments = {
            "action": ALERT_ACTION,
            "channel": ALERT_CHANNEL,
            "target": self.alert_route.target,
            "message": alert.text,
        }
        return {
            "send": True,
            "tool": ALERT_TOOL,
            "arguments": dict(alert.arguments),
            "note": "Call message once with exactly these arguments. Do not retry it, "
            "whatever it returns; then reply with the final line.",
        }

    # -- the alert send (D01 wires these to OpenClaw's message tool) --------------------

    def authorize_alert(self, params: Any) -> AlertGrant:
        """Decide one ``message`` tool call. Allowed once per run, only for a due alert,
        only ``send`` to Telegram, and only when the call carries no key outside
        ``ALERT_PARAM_KEYS``. The granted ``arguments`` are the policy's own, so the agent
        cannot change the text or the target. OpenClaw merges the hook's params over the
        agent's rather than replacing them; refusing every other key is what keeps the
        call that runs equal to ``arguments`` (no media, buttons, extra targets or
        ``dryRun``). A refused call does not use up the grant."""
        with self._lock:
            grant = self._authorize_alert(params)
            if not grant.allowed:
                self._alert.refused += 1
        self._notify_alert()
        return grant

    def _authorize_alert(self, params: Any) -> AlertGrant:
        alert = self._alert
        if alert.status == ALERT_PENDING:
            return AlertGrant(False, reason="no alert before submit_hypothesis has succeeded")
        if alert.status in (ALERT_NOT_DUE, ALERT_SKIPPED) and alert.grants == 0:
            return AlertGrant(False, reason=f"this run sends no alert: {alert.reason}")
        if alert.status != ALERT_DUE:
            return AlertGrant(False, reason="this run's one alert was already sent or tried")
        if not isinstance(params, dict):
            return AlertGrant(False, reason="message arguments must be an object")
        extra = [key for key in params if key not in ALERT_PARAM_KEYS]
        if extra:
            # The keys are not echoed: they are agent text.
            return AlertGrant(
                False,
                reason=(
                    f"the call carries {len(extra)} key(s) besides action, channel, target "
                    "and message; call message with exactly alert.arguments and nothing else"
                ),
            )
        action = str(params.get("action") or "").strip().lower()
        if action != ALERT_ACTION:
            return AlertGrant(False, reason=f"only action {ALERT_ACTION!r} is allowed")
        channel = str(params.get("channel") or ALERT_CHANNEL).strip().lower()
        if channel != ALERT_CHANNEL:
            return AlertGrant(False, reason=f"alerts go to {ALERT_CHANNEL!r} only")
        alert.status = ALERT_SENDING
        alert.grants += 1
        return AlertGrant(True, arguments=dict(alert.arguments))

    def record_alert(self, delivered: bool, error: str | None = None) -> dict[str, Any]:
        """Record the outcome of the granted send: ``sent``, or ``skipped`` with a
        redacted reason. Ignored unless a send is in flight. Never raises."""
        with self._lock:
            alert = self._alert
            if alert.status == ALERT_SENDING:
                if delivered:
                    alert.status, alert.reason = ALERT_SENT, None
                else:
                    alert.status = ALERT_SKIPPED
                    alert.reason = "delivery failed: " + (redact(error) or "no detail")
        self._notify_alert()
        return self.alert_summary()

    def expire_alert(
        self, why: str = "the agent ended its turn without sending the alert"
    ) -> dict[str, Any]:
        """Skip a due alert the agent never sent. A send in flight is left to finish."""
        with self._lock:
            if self._alert.status == ALERT_DUE:
                self._alert.status = ALERT_SKIPPED
                self._alert.reason = redact(why)
        self._notify_alert()
        return self.alert_summary()

    def _notify_alert(self) -> None:
        if self._alert_listener is None:
            return
        try:
            self._alert_listener(self.alert_summary())
        except Exception:  # best effort: an alert listener never breaks the run
            logger.warning("alert listener failed", exc_info=True)


__all__ = [
    "ABSTAIN_BELOW",
    "ABSTENTION_CONFIDENCE",
    "AGENT_ID",
    "ALERT_ACTION",
    "ALERT_CHANNEL",
    "ALERT_MIN_CONFIDENCE",
    "ALERT_PARAM_KEYS",
    "ALERT_TOOL",
    "CLOSE_MARGIN",
    "HARNESS_ID",
    "AgentPolicy",
    "AlertGrant",
    "AlertRoute",
    "Budget",
    "ToolOutcome",
    "abstain",
    "alert_decision",
    "apply_abstention_rules",
    "cited_spans",
    "compose_alert",
    "normalize_abstention",
    "redact",
    "run_brief",
    "unsafe_alert_text",
    "weakening_violations",
]

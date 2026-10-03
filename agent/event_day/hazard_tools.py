"""The three safety hazard tools for one leased clip (event day, 2026-10-03).

Written on event day for the hazard agent task. ``HazardJobSession`` is what the
``ToolGateway`` lease holds while the OpenClaw agent ``urban-mirror`` reviews one clip
(``hazard_runner.AgentHazardRunner`` creates it). The agent sees the tools as
``mirror__hazard_scan_clip``, ``mirror__hazard_review_clip`` and
``mirror__hazard_submit_summary`` (contract: ``contracts/hazard_tools.schema.json``).

* ``hazard_scan_clip``: ``review_clip(..., skip_model=True)`` into a scratch root
  (``<output_root>/agent_scan``), so a scan never replaces the clip's current report.
  The reply is a compact count summary.
* ``hazard_review_clip``: ``review_clip(..., skip_model=False)`` into the real output
  root. ``review_clip`` has no scan cache, so it scans again before the Qwen review and
  audit. The reply lists the audited findings.
* ``hazard_submit_summary``: validates the worker summary and writes
  ``agent_summary.json`` into the run directory, which closes the job.

Every call names the leased clip; any other clip id is refused without echoing it.
Arguments never carry a path, and replies never carry a path, a dataset label or an
original file name: the pipeline only ever sees the neutral clip id as ``source_name``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .policy import ToolOutcome
from .registration import HAZARD_TOOL_NAMES, hazard_def, scrub_paths

logger = logging.getLogger(__name__)

SCAN, REVIEW, SUBMIT = HAZARD_TOOL_NAMES
SUMMARY_FILE = "agent_summary.json"
SCAN_DIR = "agent_scan"
REPORT_FILE = "hazard_report.json"
REVIEW_COMPLETE = "model_review_complete"
MAX_CALLS = 16
SUBMIT_RETRIES = 6  # submit attempts still accepted once MAX_CALLS is used up
MAX_TEXT = 160
PRIORITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
# Worker-facing text must not carry ids, boxes, hashes, links, model names or legal numbers.
_BANNED = (
    (re.compile(r"\b[EZH]\d{2,3}\b"), "an evidence, zone or finding id"),
    (re.compile(r"bbox", re.IGNORECASE), "the word bbox"),
    (re.compile(r"sha256", re.IGNORECASE), "a hash"),
    (re.compile(r"http", re.IGNORECASE), "a link"),
    (re.compile(r"qwen", re.IGNORECASE), "a model name"),
    (re.compile(r"\b1910\b|\bosha\b", re.IGNORECASE), "a standard number"),
    (re.compile(r"\b(?:hz|bs)_\d+\b", re.IGNORECASE), "the clip id"),
)

ReviewFn = Callable[..., Any]
ProgressFn = Callable[[int, int, str], None]


class HazardTrace:
    """``agent_trace.json`` entries ``{t_s, kind: "tool"|"say", tool?, text}``.

    ``say`` lines are agent narration in plain words (no ids, numbers, scores or tool
    names); each one also goes to ``progress(0, 6, text)``. ``tool`` lines are short
    technical records for the technical view.
    """

    def __init__(
        self, progress: ProgressFn | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._progress = progress
        self._clock = clock
        self._t0 = clock()
        self._lock = threading.Lock()
        self.entries: list[dict[str, Any]] = []

    def _t(self) -> float:
        return round(self._clock() - self._t0, 2)

    def say(self, text: str) -> None:
        with self._lock:
            self.entries.append({"t_s": self._t(), "kind": "say", "text": text})
        if self._progress is not None:
            try:
                self._progress(0, 6, text)
            except Exception:  # a closed job must not break the agent's tool call
                logger.debug("narration progress failed", exc_info=True)

    def tool(self, tool: str, text: str) -> None:
        with self._lock:
            self.entries.append(
                {"t_s": self._t(), "kind": "tool", "tool": tool, "text": scrub_paths(text)[:400]}
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self.entries]


@cache
def _validator(tool: str) -> Draft202012Validator:
    return Draft202012Validator(hazard_def(f"{tool}_args"))


def argument_error(tool: str, arguments: Any) -> str | None:
    """Why ``arguments`` do not fit the tool's contract, without quoting any value."""
    errors = sorted(_validator(tool).iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return None
    err = errors[0]
    where = "/".join(str(p) for p in err.path) or "arguments"
    rule = err.validator
    hint = {
        "maxLength": f"at most {MAX_TEXT} characters",
        "minLength": "must not be empty",
        "additionalProperties": "only the documented fields are allowed",
        "required": "a required field is missing",
        "enum": "use one of the documented values",
        "pattern": "does not have the documented form",
        "uniqueItems": "list each id once",
    }.get(str(rule), f"fails the {rule} rule")
    return f"invalid {tool} arguments at {where}: {hint}. Fix it and call {tool} again."


def plain_text_problem(text: str) -> str | None:
    for pattern, what in _BANNED:
        if pattern.search(text):
            return what
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scan_summary(clip_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
    """The ``hazard_scan_clip_result`` for a (scan-only) report."""
    video = report.get("video") or {}
    zones = report.get("zones") or []
    movement = sum(1 for z in zones if z.get("kind") == "movement")
    warnings = (report.get("pipeline") or {}).get("quality_warnings") or []
    return {
        "clip_id": clip_id,
        "status": "scanned",
        "duration_s": round(float(video.get("duration_s") or 0.0), 2),
        "frames": int(video.get("decoded_frames") or 0),
        "zones": {"movement": movement, "static": len(zones) - movement, "total": len(zones)},
        "evidence_pictures": len(report.get("evidence") or []),
        "quality_warnings": [scrub_paths(str(w))[:300] for w in warnings][:10],
        "next": f"call {REVIEW} for this clip",
    }


def _draft_count(run_dir: Path, report: Mapping[str, Any]) -> int | None:
    key = report.get("request_sha256")
    if not isinstance(key, str) or not key:
        return None
    draft = _read_json(run_dir / f"qwen_{key[:16]}.json")
    if not isinstance(draft, dict):
        return None
    findings = (draft.get("report") or {}).get("findings")
    return len(findings) if isinstance(findings, list) else None


def _level(value: Any, default: str) -> str:
    return value if value in ("high", "medium", "low") else default


def _finding_id(value: Any, index: int) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"H\d{2,3}", value) else f"H{index:02d}"


def review_summary(clip_id: str, run_dir: Path | None, report: Mapping[str, Any] | None):
    """The ``hazard_review_clip_result`` for the review's report (or its absence)."""
    complete = bool(report) and report.get("status") == REVIEW_COMPLETE
    findings = []
    source = ((report or {}).get("findings") or []) if complete else []
    for i, f in enumerate(source, 1):
        severity = _level(f.get("severity"), "medium")
        findings.append(
            {
                "id": _finding_id(f.get("finding_id"), i),
                "severity": severity,
                "priority": severity,
                "title": str(f.get("title", "")),
                "standard_ids": list(f.get("standards") or []),
                "zone_ids": list(f.get("zone_ids") or []),
                "evidence_ids": list(f.get("evidence_ids") or []),
                "start_s": round(float(f.get("first_observed_s") or 0.0), 2),
                "end_s": round(float(f.get("last_observed_s") or 0.0), 2),
                "confidence": _level(f.get("confidence"), "low"),
                "audit_verdict": f.get("status")
                if f.get("status") in ("visible_concern", "needs_verification")
                else "needs_verification",
                "location": str(f.get("location", "")),
                "recommended_actions": [str(a) for a in f.get("recommended_actions") or []][:3],
            }
        )
    model = (report or {}).get("model") or {}
    audited = complete and bool(model.get("audit_sha256") or model.get("audit"))
    if complete:
        nxt = (
            f"write the worker summary from these findings only and call {SUBMIT}; "
            "confirm only ids listed here"
        )
    else:
        nxt = (
            f"the review did not finish: call {SUBMIT} with priority none, no confirmed ids, "
            "and say plainly that the check did not finish"
        )
    return {
        "clip_id": clip_id,
        "status": "complete" if complete else "failed",
        "findings": findings,
        "dismissed_count": len((report or {}).get("dismissed") or []) if complete else 0,
        "audit": {
            "ran": audited,
            "draft_findings": _draft_count(run_dir, report) if (complete and run_dir) else None,
        },
        "next": nxt,
    }


class HazardJobSession:
    """One clip's hazard tools for one agent turn (what the gateway lease holds)."""

    tool_names = HAZARD_TOOL_NAMES

    def __init__(
        self,
        clip_id: str,
        video: Path,
        output_root: Path,
        *,
        review_fn: ReviewFn,
        trace: HazardTrace,
        run_id: str,
        profile: str | None = None,
        refresh: bool = False,
        progress: ProgressFn | None = None,
        max_calls: int = MAX_CALLS,
    ) -> None:
        self.clip_id = clip_id
        self.video = Path(video)
        self.output_root = Path(output_root)
        self.review_fn = review_fn
        self.trace = trace
        self.profile = profile
        self.refresh = refresh
        self._progress = progress
        self.max_calls = max_calls
        self._run_id = run_id
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self.calls = 0
        self.refusals = 0
        self.per_tool: dict[str, int] = {}
        self.scan_dir: Path | None = None
        self.scan_result: dict[str, Any] | None = None
        self.run_dir: Path | None = None
        self.review_result: dict[str, Any] | None = None
        self.summary: dict[str, Any] | None = None

    # -- state ---------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def wait_closed(self, timeout: float) -> bool:
        return self._closed.wait(timeout)

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "refusals": self.refusals,
            "per_tool": dict(self.per_tool),
            "scanned": self.scan_result is not None,
            "reviewed": self.review_result is not None,
            "review_status": (self.review_result or {}).get("status"),
            "submitted": self.summary is not None,
        }

    # -- dispatch ------------------------------------------------------------------

    def call(self, name: Any, arguments: Any = None) -> ToolOutcome:
        arguments = {} if arguments is None else arguments
        tool = name if name in HAZARD_TOOL_NAMES else "unknown"
        with self._lock:
            self.calls += 1
            self.per_tool[tool] = self.per_tool.get(tool, 0) + 1
            if self.closed:
                return self._refuse(
                    tool, "the job is closed: the summary was submitted. Reply with the FINAL line."
                )
            if tool == "unknown":
                return self._refuse(tool, "unknown hazard tool")
            if self.calls > self.max_calls and not (
                tool == SUBMIT and self.calls <= self.max_calls + SUBMIT_RETRIES
            ):
                return self._refuse(
                    tool, f"the job is out of calls. Only {SUBMIT} is accepted, then end your turn."
                )
            if (problem := argument_error(tool, arguments)) is not None:
                self.trace.tool(tool, f"{tool} rejected: {problem}")
                return ToolOutcome(tool, ok=False, error=problem)
            if arguments["clip_id"] != self.clip_id:
                return self._refuse(
                    tool,
                    f"this job covers one clip only. Use clip_id {self.clip_id!r} from the brief.",
                )
            if tool == SCAN:
                return self._scan()
            if tool == REVIEW:
                return self._review()
            return self._submit(arguments)

    def _refuse(self, tool: str, why: str) -> ToolOutcome:
        self.refusals += 1
        error = f"refused by the tool surface: {why}"
        self.trace.tool(tool, f"{tool} refused: {why}")
        return ToolOutcome(tool, ok=False, error=error, refused=True)

    def _forward(self, lo: int, hi: int) -> ProgressFn:
        """Pass ``review_clip``'s numbered steps ``lo..hi`` through to the job."""

        def forward(step: int, total: int, message: str) -> None:
            if self._progress is not None and lo <= step <= hi:
                try:
                    self._progress(step, total, message)
                except Exception:
                    logger.debug("step progress failed", exc_info=True)

        return forward

    # -- tools ---------------------------------------------------------------------

    def _scan(self) -> ToolOutcome:
        if self.scan_result is not None:
            self.trace.tool(SCAN, f"{SCAN} ok (already scanned; same summary)")
            return ToolOutcome(SCAN, ok=True, result=self.scan_result)
        self.trace.say("The safety agent asked for the camera scan")
        started = time.monotonic()
        try:
            scan_dir = Path(
                self.review_fn(
                    self.video,
                    self.output_root / SCAN_DIR,
                    source_name=self.clip_id,
                    profile=self.profile,
                    skip_model=True,
                    refresh=False,
                    progress=self._forward(1, 4),
                )
            )
        except Exception as exc:
            logger.warning("hazard scan of %s failed", self.clip_id, exc_info=True)
            self.trace.tool(SCAN, f"{SCAN} failed: {type(exc).__name__}")
            self.trace.say("The camera scan did not work")
            return ToolOutcome(
                SCAN,
                ok=False,
                error=(
                    f"the scan failed ({type(exc).__name__}). Call {SCAN} once more; if it "
                    f"fails again, call {SUBMIT} with priority none and say the check did not "
                    "finish."
                ),
            )
        report = _read_json(scan_dir / REPORT_FILE)
        if not isinstance(report, dict):
            self.trace.tool(SCAN, f"{SCAN} failed: no report")
            return ToolOutcome(
                SCAN, ok=False, error=f"the scan wrote no report. Call {SCAN} again."
            )
        self.scan_dir = scan_dir
        self.scan_result = scan_summary(self.clip_id, report)
        z = self.scan_result["zones"]
        self.trace.tool(
            SCAN,
            f"{SCAN} ok in {time.monotonic() - started:.1f} s: {z['total']} zones "
            f"({z['movement']} movement, {z['static']} static), "
            f"{self.scan_result['evidence_pictures']} evidence pictures, "
            f"{len(self.scan_result['quality_warnings'])} quality warnings",
        )
        self.trace.say("The safety agent has the camera scan")
        return ToolOutcome(SCAN, ok=True, result=self.scan_result)

    def _review(self) -> ToolOutcome:
        if self.scan_result is None:
            return self._refuse(REVIEW, f"call {SCAN} first.")
        if self.review_result is not None:
            self.trace.tool(REVIEW, f"{REVIEW} ok (already reviewed; same findings)")
            return ToolOutcome(REVIEW, ok=True, result=self.review_result)
        self.trace.say("The safety agent asked the local AI to review the pictures and check them")
        started = time.monotonic()
        run_dir: Path | None = None
        try:
            run_dir = Path(
                self.review_fn(
                    self.video,
                    self.output_root,
                    source_name=self.clip_id,
                    profile=self.profile,
                    skip_model=False,
                    refresh=self.refresh,
                    progress=self._forward(5, 6),
                )
            )
        except Exception as exc:
            logger.warning("hazard review of %s failed", self.clip_id, exc_info=True)
            self.trace.tool(REVIEW, f"{REVIEW} failed: {type(exc).__name__}")
        report = _read_json(run_dir / REPORT_FILE) if run_dir else None
        self.run_dir = run_dir if isinstance(report, dict) else None
        if self.run_dir is not None:
            # A summary left by an earlier job describes an earlier report: drop it, so the
            # run dir only ever holds a summary of the findings this review returned.
            try:
                (self.run_dir / SUMMARY_FILE).unlink(missing_ok=True)
            except OSError:
                logger.warning("could not remove a stale %s", SUMMARY_FILE, exc_info=True)
        try:
            self.review_result = review_summary(
                self.clip_id, self.run_dir, report if isinstance(report, dict) else None
            )
        except Exception as exc:  # an unexpected report shape counts as a failed review
            logger.warning("hazard report of %s unreadable", self.clip_id, exc_info=True)
            self.trace.tool(REVIEW, f"{REVIEW} report unreadable: {type(exc).__name__}")
            self.review_result = review_summary(self.clip_id, None, None)
        result = self.review_result
        if result["status"] == "complete":
            self.trace.tool(
                REVIEW,
                f"{REVIEW} ok in {time.monotonic() - started:.1f} s: "
                f"{len(result['findings'])} findings "
                f"({', '.join(f['id'] + ' ' + f['severity'] for f in result['findings']) or 'none'}), "
                f"{result['dismissed_count']} dismissed, audit "
                f"{'ran' if result['audit']['ran'] else 'missing'}",
            )
            self.trace.say("The safety agent is reading the review and writing a summary")
        else:
            self.trace.tool(REVIEW, f"{REVIEW} finished with status failed")
            self.trace.say("The review did not finish; the safety agent is saying so")
        return ToolOutcome(REVIEW, ok=True, result=result)

    def _submit(self, arguments: Mapping[str, Any]) -> ToolOutcome:
        review = self.review_result
        if review is None:
            return self._refuse(SUBMIT, f"call {REVIEW} first.")
        headline = " ".join(str(arguments["headline"]).split())
        first_action = " ".join(str(arguments["first_action"]).split())
        priority = str(arguments["priority"])
        confirmed = list(arguments["confirmed_finding_ids"])
        problem = self._summary_problem(
            review, headline, first_action, priority, confirmed, clip_id=self.clip_id
        )
        if problem is not None:
            self.trace.tool(SUBMIT, f"{SUBMIT} rejected: {problem}")
            self.trace.say("The safety agent is rewording its summary")
            return ToolOutcome(
                SUBMIT, ok=False, error=f"summary not accepted: {problem} Fix it and submit again."
            )
        summary = {
            "headline": headline,
            "first_action": first_action,
            "priority": priority,
            "confirmed_finding_ids": confirmed,
        }
        if self.run_dir is not None:
            try:
                (self.run_dir / SUMMARY_FILE).write_text(
                    json.dumps(summary, indent=2) + "\n", encoding="utf-8"
                )
            except OSError:
                logger.warning("could not write %s", SUMMARY_FILE, exc_info=True)
        self.summary = summary
        self.trace.tool(
            SUBMIT, f"{SUBMIT} ok: priority {priority}, confirmed {', '.join(confirmed) or 'none'}"
        )
        self.trace.say("The safety agent wrote its summary for the floor team")
        self._closed.set()
        return ToolOutcome(
            SUBMIT,
            ok=True,
            result={
                "clip_id": self.clip_id,
                "status": "submitted",
                "priority": priority,
                "confirmed": len(confirmed),
                "next": "reply with the FINAL line and end your turn",
            },
        )

    @staticmethod
    def _summary_problem(
        review: Mapping[str, Any],
        headline: str,
        first_action: str,
        priority: str,
        confirmed: list[str],
        *,
        clip_id: str = "",
    ) -> str | None:
        for field, text in (("headline", headline), ("first_action", first_action)):
            if not text:
                return f"{field} is empty."
            if len(text) > MAX_TEXT:
                return f"{field} is longer than {MAX_TEXT} characters."
            if clip_id and clip_id.lower() in text.lower():
                return f"{field} contains the clip id; write plain words for a frontline worker."
            if (what := plain_text_problem(text)) is not None:
                return f"{field} contains {what}; write plain words for a frontline worker."
        known = {f["id"]: f for f in review["findings"]}
        unknown = [c for c in confirmed if c not in known]
        if unknown:
            listed = ", ".join(known) or "none"
            return (
                f"confirmed_finding_ids names a finding the review did not return (use: {listed})."
            )
        if review["status"] != "complete":
            if priority != "none" or confirmed:
                return "the review did not finish, so priority must be none with no confirmed ids."
            return None
        if confirmed and priority == "none":
            return "priority none cannot go with confirmed findings."
        if confirmed:
            top = max(PRIORITY_RANK[known[c]["severity"]] for c in confirmed)
            if PRIORITY_RANK[priority] > top:
                allowed = next(k for k, v in PRIORITY_RANK.items() if v == top)
                return f"priority is higher than any confirmed finding (at most {allowed})."
        elif priority != "none":
            return "with no confirmed findings, priority must be none."
        return None


__all__ = [
    "SUMMARY_FILE",
    "HazardJobSession",
    "HazardTrace",
    "argument_error",
    "plain_text_problem",
    "review_summary",
    "scan_summary",
]

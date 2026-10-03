"""Run lifecycle and the per-run SSE event log.

A run is an in-memory, append-only envelope log (seq 1, 2, ...) mirrored to
``<runs_dir>/<run_id>/events.jsonl``, with the ``RunRecord`` in ``run.json``.
The executor runs in a worker thread and reports progress through ``emit``,
which is thread-safe: seq assignment, the jsonl write and the hand-off to the
event loop happen under one lock, so the loop appends events in seq order even
when the executor emits from several threads. Terminal events (``run.complete``,
``run.failed``) are published only by the manager, and the record's terminal
state flips in the same loop callback that appends the terminal event.

Alert messages (``alert.message`` / ``alert.delivery``) are also published only here: an
``AlertFeed`` watches the executor's events and adds at most one early heads-up and one
closing message right before ``run.complete``. Composing them is best effort; a failure
is logged and never fails the run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from pydantic_core import to_jsonable_python

from apps.api.schemas import (
    ALERT_EVENT_TYPES,
    EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    AlertDelivery,
    AlertMessage,
    GroundTruthAccessError,
    Hypothesis,
    RunRecord,
    Scenario,
)

from .alert_feed import AlertFeed
from .alert_messages import MessageContext, load_alert_config
from .gt_guard import GtGuard
from .scenarios import LoadedScenario

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]
MAX_ERROR_CHARS = 300


class RunExecutor(Protocol):
    """What the API runs for a run. P10 swaps in the dev-sequence harness here.

    Implementations must call ``scenario.model_view()`` before touching any model-
    facing code and must not pass ground-truth data anywhere. ``emit`` accepts every
    non-terminal type in ``contracts/SSE_EVENTS.md``; the manager emits the terminal
    ``run.complete`` / ``run.failed`` from the return value or raised exception. An
    exception may carry a ``stage`` attribute; otherwise the last ``tool.started``
    tool name is reported as the failed stage.

    Optional capability: ``delivers_alerts = True`` means the executor sends alert
    messages itself (event day: Telegram), either through a ``deliver_alert(message)``
    method or by emitting ``alert.delivery``. Without it every ``ping`` / ``alert``
    message gets ``alert.delivery`` with status ``not_connected``.
    """

    def __call__(
        self, scenario: Scenario, profile_name: str, emit: Emit, run_dir: Path, pace_s: float
    ) -> Hypothesis: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_ts(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id() -> str:
    return f"run_{utc_now():%Y%m%dT%H%M%SZ}_{secrets.token_hex(3)}"


def short_error(exc: BaseException) -> str:
    """One-line error for ``run.failed``: exception type plus message, no traceback."""
    text = " ".join(str(exc).split())
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:MAX_ERROR_CHARS]


def run_urls(run_id: str) -> dict[str, str]:
    base = f"/api/runs/{quote(run_id, safe='')}"
    return {"run_url": base, "events_url": f"{base}/events"}


class RunHandle:
    def __init__(
        self,
        record: RunRecord,
        run_dir: Path,
        guard: GtGuard,
        gt_camera_id: str,
        loop: asyncio.AbstractEventLoop,
        alerts: AlertFeed | None = None,
    ) -> None:
        self.record = record
        self.run_dir = run_dir
        self.guard = guard
        self.gt_camera_id = gt_camera_id
        self.stage = "startup"
        self._loop = loop
        self._lock = threading.Lock()
        self._next_seq = 1
        self._closed = False  # terminal envelope assigned; later publishes are refused
        self._finished = False  # terminal envelope appended to the in-memory log
        self._log: list[tuple[int, str, str]] = []  # (seq, type, envelope JSON)
        self._wake = asyncio.Event()
        self._started_at = time.perf_counter()
        self._persist_warned = False
        self._alerts = alerts

    @property
    def run_id(self) -> str:
        return self.record.run_id

    @property
    def finished(self) -> bool:
        return self._finished

    def envelopes(self) -> list[dict[str, Any]]:
        return [json.loads(line) for _, _, line in self._log]

    def public_record(self) -> dict[str, Any]:
        return self.record.model_dump(mode="json") | run_urls(self.run_id)

    # -- executor-facing (any thread) ---------------------------------------------

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if event_type in TERMINAL_EVENT_TYPES or event_type == "alert.message":
            raise ValueError(f"{event_type} is emitted by the run manager, not the executor")
        if event_type == "alert.delivery":
            self._check_delivery(payload)
        data = self._publish(event_type, payload)
        if event_type == "tool.started" and isinstance(payload, dict) and payload.get("tool"):
            self.stage = str(payload["tool"])
        if event_type not in ALERT_EVENT_TYPES:
            self._observe(event_type, data)

    def _check_delivery(self, payload: dict[str, Any] | None) -> None:
        """An executor that delivers alerts itself reports on the manager's messages only."""
        delivery = AlertDelivery.model_validate(payload or {})
        if self._alerts is None or not self._alerts.knows(delivery.message_id):
            raise ValueError(f"alert.delivery for unknown message {delivery.message_id!r}")

    # -- alert messages (best effort) ---------------------------------------------------

    def _observe(self, event_type: str, data: dict[str, Any]) -> None:
        if self._alerts is None:
            return
        try:
            message = self._alerts.observe(event_type, data)
            if message is not None:
                self._send_alert(message)
        except Exception as exc:  # noqa: BLE001 - a message must never fail a tool call
            self._alert_failed(exc)

    def publish_final_alert(self, hypothesis: Hypothesis) -> None:
        """Publish the closing message (call right before ``finish_complete``). Skipped
        when the hypothesis itself would be refused, so a failing run carries no alert."""
        if self._alerts is None:
            return
        try:
            if self.guard.leaks(hypothesis.model_dump_json()):
                return
            message = self._alerts.final(hypothesis)
            if message is not None:
                self._send_alert(message)
        except Exception as exc:  # noqa: BLE001 - the run completes without its message
            self._alert_failed(exc)

    def _send_alert(self, message: AlertMessage) -> None:
        """Publish a message and its delivery status. A message that mentions the withheld
        camera is skipped, never published as a "[withheld]" copy: that word alone would
        tell the worker something is being kept from them."""
        payload = message.model_dump(mode="json")
        if self.guard.leaks(json.dumps(payload, ensure_ascii=False)):
            logger.warning("run %s: alert %s skipped (withheld camera)", self.run_id, message.id)
            return
        self._publish("alert.message", {"message": payload})
        delivery = self._alerts.delivery(message) if self._alerts else None
        if delivery is not None:
            if self.guard.leaks(json.dumps(delivery, ensure_ascii=False)):
                delivery = delivery | {"detail": None}
            self._publish("alert.delivery", delivery)

    def _alert_failed(self, exc: Exception) -> None:
        logger.warning("run %s: alert message skipped (%s)", self.run_id, type(exc).__name__)
        logger.debug("run %s alert failure detail", self.run_id, exc_info=exc)

    def _publish(self, event_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown SSE event type {event_type!r}")
        data = to_jsonable_python(payload if payload is not None else {})
        if not isinstance(data, dict):
            raise TypeError(f"{event_type} payload must be a JSON object")
        if self.guard.leaks(json.dumps(data, ensure_ascii=False, allow_nan=False)):
            raise GroundTruthAccessError(
                f"{event_type} payload references the withheld ground-truth camera"
            )
        with self._lock:
            if self._closed:
                raise RuntimeError(f"run {self.run_id} already finished; {event_type} dropped")
            seq = self._next_seq
            self._next_seq += 1
            envelope = {
                "run_id": self.run_id,
                "seq": seq,
                "ts": iso_ts(utc_now()),
                "type": event_type,
                "payload": data,
            }
            line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
            terminal = event_type in TERMINAL_EVENT_TYPES
            if terminal:
                self._closed = True
            self._persist_line(line)
            self._loop.call_soon_threadsafe(self._append, seq, event_type, line, data)
        return data

    # -- loop thread ----------------------------------------------------------------

    def _append(self, seq: int, event_type: str, line: str, payload: dict[str, Any]) -> None:
        self._log.append((seq, event_type, line))
        now = utc_now()
        self.record.last_seq = seq
        self.record.updated_at = now
        if event_type in TERMINAL_EVENT_TYPES:
            if event_type == "run.complete":
                self.record.hypothesis = payload["hypothesis"]
                self.record.state = "complete"
            else:
                self.record.error = payload["error"]
                self.record.state = "failed"
            self.record.finished_at = now
            self._finished = True
            self.persist_record()
        wake, self._wake = self._wake, asyncio.Event()
        wake.set()

    def mark_running(self) -> None:
        self.record.state = "running"
        self.record.updated_at = utc_now()
        self._started_at = time.perf_counter()
        self.persist_record()

    def finish_complete(self, hypothesis: Hypothesis) -> None:
        duration_ms = int((time.perf_counter() - self._started_at) * 1000)
        self._publish(
            "run.complete",
            {"hypothesis": hypothesis.model_dump(mode="json"), "duration_ms": duration_ms},
        )

    def finish_failed(self, stage: str, error: str) -> None:
        self._publish(
            "run.failed", {"stage": self.guard.redact(stage), "error": self.guard.redact(error)}
        )

    async def stream(self, after_seq: int = 0) -> AsyncIterator[tuple[int, str]]:
        """Yield ``(seq, envelope JSON)`` after ``after_seq``: replay, then live, then stop
        after the terminal event."""
        index = max(after_seq, 0)  # log[i] holds seq i + 1
        while True:
            while index < len(self._log):
                seq, event_type, line = self._log[index]
                index += 1
                yield seq, line
                if event_type in TERMINAL_EVENT_TYPES:
                    return
            if self._finished:
                return
            await self._wake.wait()

    # -- persistence ----------------------------------------------------------------

    def persist_record(self) -> None:
        try:
            (self.run_dir / "run.json").write_text(
                self.record.model_dump_json(indent=2), encoding="utf-8"
            )
        except OSError as exc:
            self._warn_persist(exc)

    def _persist_line(self, line: str) -> None:
        # Open per line: a run is ~50 events, and no handle outlives a run that never
        # reaches a terminal event (server killed, test abandons the handle).
        try:
            with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            self._warn_persist(exc)

    def _warn_persist(self, exc: OSError) -> None:
        if not self._persist_warned:
            self._persist_warned = True
            logger.warning("run %s: persisting artifacts failed (%s)", self.run_id, exc.errno)


class RunManager:
    """In-memory run registry. Runs execute in worker threads via ``asyncio.to_thread``."""

    def __init__(self, runs_dir: Path, alerts_config: Path | None = None) -> None:
        self.runs_dir = runs_dir
        self.alerts_config = alerts_config
        self._runs: dict[str, RunHandle] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def get(self, run_id: str) -> RunHandle | None:
        return self._runs.get(run_id)

    def start(
        self, loaded: LoadedScenario, profile: str, pace_s: float, executor: RunExecutor
    ) -> RunHandle:
        """Register a run and schedule it. Must be called on the event loop."""
        loop = asyncio.get_running_loop()
        run_id = new_run_id()
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        record = RunRecord(
            run_id=run_id,
            scenario_id=loaded.id,
            profile=profile,
            state="queued",
            created_at=now,
            updated_at=now,
        )
        handle = RunHandle(
            record,
            run_dir,
            loaded.guard,
            loaded.scenario.ground_truth_camera.id,
            loop,
            alerts=self._alert_feed(loaded, executor),
        )
        handle.persist_record()
        self._runs[run_id] = handle
        task = loop.create_task(
            self._execute(handle, loaded.scenario, executor, pace_s), name=f"run:{run_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("run %s queued (scenario=%s profile=%s)", run_id, loaded.id, profile)
        return handle

    def _alert_feed(self, loaded: LoadedScenario, executor: RunExecutor) -> AlertFeed | None:
        try:
            ctx = MessageContext.from_scenario(loaded.scenario)
            return AlertFeed.for_executor(ctx, executor, load_alert_config(self.alerts_config))
        except Exception as exc:  # noqa: BLE001 - runs work without alert messages
            logger.warning("alert messages off for %s (%s)", loaded.id, type(exc).__name__)
            return None

    @staticmethod
    def _run_executor(
        handle: RunHandle, scenario: Scenario, executor: RunExecutor, pace_s: float
    ) -> Hypothesis:
        """Worker thread: run the executor, then publish the closing alert message."""
        result = executor(scenario, handle.record.profile, handle.emit, handle.run_dir, pace_s)
        hypothesis = result if isinstance(result, Hypothesis) else Hypothesis.model_validate(result)
        handle.publish_final_alert(hypothesis)
        return hypothesis

    async def _execute(
        self, handle: RunHandle, scenario: Scenario, executor: RunExecutor, pace_s: float
    ) -> None:
        handle.mark_running()
        try:
            hypothesis = await asyncio.to_thread(
                self._run_executor, handle, scenario, executor, pace_s
            )
            handle.finish_complete(hypothesis)
        except asyncio.CancelledError:
            self._fail(handle, "cancelled", "run cancelled (server shutting down)")
            raise
        except Exception as exc:
            stage = str(getattr(exc, "stage", "") or handle.stage)
            logger.warning(
                "run %s failed at stage %s: %s", handle.run_id, stage, type(exc).__name__
            )
            logger.debug("run %s failure detail", handle.run_id, exc_info=exc)
            self._fail(handle, stage, short_error(exc))
        else:
            logger.info("run %s complete", handle.run_id)

    @staticmethod
    def _fail(handle: RunHandle, stage: str, error: str) -> None:
        try:
            handle.finish_failed(stage, error)
        except RuntimeError:  # a terminal event was already published
            logger.debug("run %s: failure after terminal event ignored", handle.run_id)

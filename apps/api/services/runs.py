"""Run lifecycle and the per-run SSE event log.

A run is an in-memory, append-only envelope log (seq 1, 2, ...) mirrored to
``<runs_dir>/<run_id>/events.jsonl``, with the ``RunRecord`` in ``run.json``.
The executor runs in a worker thread and reports progress through ``emit``,
which is thread-safe: seq assignment, the jsonl write and the hand-off to the
event loop happen under one lock, so the loop appends events in seq order even
when the executor emits from several threads. Terminal events (``run.complete``,
``run.failed``) are published only by the manager, and the record's terminal
state flips in the same loop callback that appends the terminal event.
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
    EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    GroundTruthAccessError,
    Hypothesis,
    RunRecord,
    Scenario,
)

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
        if event_type in TERMINAL_EVENT_TYPES:
            raise ValueError(f"{event_type} is emitted by the run manager, not the executor")
        self._publish(event_type, payload)
        if event_type == "tool.started" and isinstance(payload, dict) and payload.get("tool"):
            self.stage = str(payload["tool"])

    def _publish(self, event_type: str, payload: dict[str, Any] | None) -> None:
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

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
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
            record, run_dir, loaded.guard, loaded.scenario.ground_truth_camera.id, loop
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

    async def _execute(
        self, handle: RunHandle, scenario: Scenario, executor: RunExecutor, pace_s: float
    ) -> None:
        handle.mark_running()
        try:
            result = await asyncio.to_thread(
                executor, scenario, handle.record.profile, handle.emit, handle.run_dir, pace_s
            )
            hypothesis = (
                result if isinstance(result, Hypothesis) else Hypothesis.model_validate(result)
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

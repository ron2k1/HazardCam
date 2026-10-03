"""Per-run alert feed: turns a run's SSE events into plain-language alert messages.

Harness-agnostic: it reads only the events every executor emits through the shared tool
session (``camera.observation``, ``fusion.started``, ``evidence.linked``,
``triangulation.updated``) plus the final hypothesis, so the dev-sequence harness and the
event-day agent get identical messages. The run manager publishes what it returns:

* at most one ``ping``, right after the first observation whose cue pings (config);
* one closing message (``alert`` / ``unconfirmed`` / ``all_clear``) right before
  ``run.complete``;
* for ``ping`` and ``alert``, an ``alert.delivery``. An executor without the
  ``delivers_alerts`` capability gets ``not_connected``. One with it may expose
  ``deliver_alert(message: dict) -> {"status", "detail"}``, called synchronously (keep it
  quick), or report delivery itself by emitting ``alert.delivery``.

Thread-safe; composition errors are the caller's to log, never the run's to fail.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from apps.api.schemas import AlertDelivery, AlertMessage, Hypothesis

from .alert_messages import (
    AlertConfig,
    MessageContext,
    compose_final,
    compose_ping,
    load_alert_config,
    redact_detail,
)

DELIVERED_KINDS = frozenset({"ping", "alert"})
HOOK_STATUSES = frozenset({"sent", "skipped", "failed"})
NOT_CONNECTED_DETAIL = "Telegram is not connected in this setup."
Deliver = Callable[[dict[str, Any]], Any]


HOOK_FAILED_DETAIL = "The delivery hook failed."


def short_error(exc: BaseException) -> str:
    """The exception's message on one line, without its class name (redacted later)."""
    return " ".join(str(exc).split()) or HOOK_FAILED_DETAIL


class AlertFeed:
    def __init__(
        self,
        ctx: MessageContext,
        config: AlertConfig | None = None,
        *,
        delivers_alerts: bool = False,
        deliver: Deliver | None = None,
    ) -> None:
        self.ctx = ctx
        self.config = config or load_alert_config()
        self.delivers_alerts = delivers_alerts
        self._deliver = deliver if delivers_alerts and callable(deliver) else None
        self._lock = threading.Lock()
        self._observations: dict[str, dict[str, Any]] = {}  # observation id -> scenario time
        self._evidence: dict[str, dict[str, Any]] = {}
        self._candidates: list[dict[str, Any]] = []
        self._pinged = False
        self._closed = False
        self._count = 0
        self.message_ids: list[str] = []

    @classmethod
    def for_executor(
        cls, ctx: MessageContext, executor: object, config: AlertConfig | None = None
    ) -> AlertFeed:
        return cls(
            ctx,
            config,
            delivers_alerts=getattr(executor, "delivers_alerts", False) is True,
            deliver=getattr(executor, "deliver_alert", None),
        )

    def _next_id(self) -> str:
        self._count += 1
        message_id = f"msg_{self._count:02d}"
        self.message_ids.append(message_id)
        return message_id

    def observe(self, event_type: str, payload: Mapping[str, Any]) -> AlertMessage | None:
        """Record one published event; return a ping to publish after it, if one is due."""
        with self._lock:
            if self._closed:
                return None
            if event_type == "camera.observation":
                return self._observation(payload)
            if event_type == "fusion.started":  # a re-run clears everything downstream
                self._evidence.clear()
                self._candidates = []
            elif event_type == "evidence.linked":
                for item in payload.get("evidence") or []:
                    if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                        self._evidence[item["id"]] = dict(item)
            elif event_type == "triangulation.updated":
                self._candidates = [
                    dict(c) for c in payload.get("candidates") or [] if isinstance(c, Mapping)
                ]
            return None

    def _observation(self, payload: Mapping[str, Any]) -> AlertMessage | None:
        camera_id, obs = payload.get("camera_id"), payload.get("observation")
        if camera_id not in self.ctx.cameras or not isinstance(obs, Mapping):
            return None
        offset = self.ctx.cameras[camera_id].time_offset_s
        try:
            t_start = float(obs["t_start"]) + offset
            t_end = float(obs.get("t_end", obs["t_start"])) + offset
        except (KeyError, TypeError, ValueError):
            return None
        if isinstance(obs.get("id"), str):
            self._observations[obs["id"]] = dict(obs) | {
                "camera_id": camera_id,
                "t_start": t_start,
                "t_end": t_end,
            }
        if self._pinged or not self.config.cue(str(obs.get("cue_type") or "")).ping:
            return None
        message = compose_ping(
            camera_id, obs, self.ctx, message_id=f"msg_{self._count + 1:02d}", config=self.config
        )
        if message is not None:
            self._pinged = True
            self._next_id()
        return message

    def final(self, hypothesis: Hypothesis) -> AlertMessage | None:
        """The closing message for the submitted hypothesis (once per run)."""
        with self._lock:
            if self._closed:
                return None
            self._closed = True
            fallback = [o for i, o in self._observations.items() if i not in self._evidence]
            message = compose_final(
                hypothesis,
                self.ctx,
                evidence=[*self._evidence.values(), *fallback],
                candidates=self._candidates,
                message_id=f"msg_{self._count + 1:02d}",
                config=self.config,
            )
            self._next_id()
            return message

    def delivery(self, message: AlertMessage) -> dict[str, Any] | None:
        """The ``alert.delivery`` payload for a just-published message, or ``None`` when
        the message is not sent anywhere or the executor reports delivery itself."""
        if message.kind not in DELIVERED_KINDS:
            return None
        if not self.delivers_alerts:
            status, detail = "not_connected", NOT_CONNECTED_DETAIL
        elif self._deliver is None:
            return None
        else:
            status, detail = self._call_deliver(message)
        return AlertDelivery(
            message_id=message.id, status=status, detail=redact_detail(detail)
        ).model_dump(mode="json")

    def _call_deliver(self, message: AlertMessage) -> tuple[str, str | None]:
        assert self._deliver is not None
        try:
            result = self._deliver(message.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - best effort; never fails the run
            return "failed", short_error(exc)
        result = result if isinstance(result, Mapping) else {}
        detail = result.get("detail") if isinstance(result.get("detail"), str) else None
        if result.get("status") in HOOK_STATUSES:
            return result["status"], detail
        return "failed", detail or "The delivery hook returned no status."

    def knows(self, message_id: object) -> bool:
        return message_id in self.message_ids

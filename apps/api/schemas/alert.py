"""Plain-language alert messages: the worker view's message feed and the Telegram text.

Composed by deterministic code (``apps.api.services.alert_messages``), never by a model.
Mirrors ``$defs/alert_message`` and ``$defs/alert_delivery`` of
``contracts/sse_envelope.schema.json``. These models are closed (unknown keys are an
error) so nothing undeclared, such as an internal id or a score, can ride along.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import ClosedContract

AlertKind = Literal["ping", "alert", "unconfirmed", "all_clear"]
AlertLevel = Literal["danger", "warning", "info"]
AlertLineKey = Literal["what", "where", "when", "how_sure", "seen_on", "what_to_do"]
DeliveryStatus = Literal["sent", "skipped", "failed", "not_connected"]

ALERT_KINDS: tuple[str, ...] = ("ping", "alert", "unconfirmed", "all_clear")
ALERT_LEVELS: tuple[str, ...] = ("danger", "warning", "info")
DELIVERY_STATUSES: tuple[str, ...] = ("sent", "skipped", "failed", "not_connected")
# Display order and the fixed label of every line key.
LINE_LABELS: dict[str, str] = {
    "what": "What happened",
    "where": "Where",
    "when": "When",
    "how_sure": "How sure",
    "seen_on": "Seen on",
    "what_to_do": "What to do",
}
MESSAGE_ID_PATTERN = r"^msg_[0-9]{2,}$"
UTC_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
MAX_DETAIL_CHARS = 200


class AlertLine(ClosedContract):
    key: AlertLineKey
    label: str
    value: str = Field(min_length=1)

    @classmethod
    def of(cls, key: str, value: str) -> AlertLine:
        return cls(key=key, label=LINE_LABELS.get(key, key), value=value)

    @model_validator(mode="after")
    def _label_matches_key(self) -> AlertLine:
        if self.label != LINE_LABELS[self.key]:
            raise ValueError(f"line {self.key!r} must be labelled {LINE_LABELS[self.key]!r}")
        return self


class AlertMessage(ClosedContract):
    id: str = Field(pattern=MESSAGE_ID_PATTERN)
    kind: AlertKind
    level: AlertLevel
    headline: str = Field(min_length=1)
    lines: list[AlertLine] = Field(min_length=1)
    # For click-to-seek only; the worker view never displays them.
    evidence_ids: list[str] = Field(default_factory=list)
    camera_ids: list[str] = Field(default_factory=list)
    t_start: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, ge=0)
    created_at: str = Field(pattern=UTC_TIMESTAMP_PATTERN)
    # The full plain-text rendering: exactly what Telegram receives.
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> AlertMessage:
        keys = [line.key for line in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError(f"alert {self.id!r}: duplicate line keys {keys}")
        if self.t_start is not None and self.t_end is not None and self.t_end < self.t_start:
            raise ValueError(f"alert {self.id!r}: t_end < t_start")
        return self

    def line(self, key: str) -> str | None:
        return next((line.value for line in self.lines if line.key == key), None)


class AlertMessagePayload(ClosedContract):
    """The ``alert.message`` SSE payload."""

    message: AlertMessage


class AlertDelivery(ClosedContract):
    """The ``alert.delivery`` SSE payload: what happened to a message's Telegram send."""

    message_id: str = Field(pattern=MESSAGE_ID_PATTERN)
    channel: Literal["telegram"] = "telegram"
    status: DeliveryStatus
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)

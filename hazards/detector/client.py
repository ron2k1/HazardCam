"""HTTP client for the local YOLO detector service (``hazards/detector/server.py``).

The service runs in the ``detector`` container on ``127.0.0.1:8003`` because the app's
``.venv`` has no torch/ultralytics. API (see the hazard spec):

- ``GET /health`` -> ``{ok, device, models: {name: sha256}}``
- ``POST /detect?models=yolo11s[,yolov8s-worldv2]&conf=0.25`` with a JPEG/PNG body ->
  ``{width, height, objects: [{model, label, conf, box: [x0, y0, x1, y1]}], elapsed_ms}``

Local only: the base URL must be a loopback host. ``health()`` never raises; ``detect()``
raises :class:`DetectorError` so the scanner can take the original edge-contour fallback.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:8003"
URL_ENV = "HAZARDS_DETECTOR_URL"
HEALTH_TIMEOUT_S = 3.0
DETECT_TIMEOUT_S = 120.0
KNOWN_MODELS = ("yolo11s", "yolov8s-worldv2")
DEFAULT_MODELS = ("yolo11s",)
DEFAULT_CONF = 0.25
_LOOPBACK_NAMES = frozenset({"localhost"})


class DetectorError(RuntimeError):
    """The detector is unreachable or answered with something unusable."""


@dataclass(frozen=True)
class Detection:
    model: str
    label: str
    conf: float
    box: tuple[float, float, float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "label": self.label,
            "conf": self.conf,
            "box": [round(v, 2) for v in self.box],
        }


@dataclass(frozen=True)
class DetectResult:
    width: int
    height: int
    objects: list[Detection]
    elapsed_ms: float | None = None


@dataclass
class DetectorHealth:
    base_url: str
    ok: bool = False
    device: str | None = None
    models: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _require_loopback(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(f"detector URL must be http(s)://<loopback>:<port>, got {url!r}")
    if host not in _LOOPBACK_NAMES:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError:
            raise ValueError(
                f"detector URL host {host!r} is not loopback; the detector is local-only"
            ) from None
    return url.rstrip("/")


class DetectorClient:
    """Synchronous client; one short-lived ``httpx.Client`` per call, proxies ignored."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        health_timeout_s: float = HEALTH_TIMEOUT_S,
        detect_timeout_s: float = DETECT_TIMEOUT_S,
    ) -> None:
        self.base_url = _require_loopback(base_url or os.environ.get(URL_ENV) or DEFAULT_URL)
        self._transport = transport
        self._health_timeout_s = health_timeout_s
        self._detect_timeout_s = detect_timeout_s

    def _client(self, timeout_s: float) -> httpx.Client:
        return httpx.Client(timeout=timeout_s, transport=self._transport, trust_env=False)

    def health(self) -> DetectorHealth:
        result = DetectorHealth(base_url=self.base_url)
        try:
            with self._client(self._health_timeout_s) as http:
                resp = http.get(self.base_url + "/health")
        except httpx.HTTPError as exc:
            result.error = f"unreachable ({type(exc).__name__})"
            return result
        if resp.status_code != 200:
            result.error = f"HTTP {resp.status_code}"
            return result
        try:
            body = resp.json()
            models = body.get("models") or {}
            result.models = {str(k): str(v) for k, v in dict(models).items()}
            result.device = None if body.get("device") is None else str(body["device"])
            result.ok = bool(body.get("ok"))
        except (ValueError, TypeError, AttributeError):
            result.error = "malformed /health body"
            result.ok = False
            return result
        if not result.ok:
            result.error = str(body.get("error") or "detector reports ok=false")
        return result

    def detect(
        self,
        image: bytes,
        *,
        content_type: str = "image/png",
        models: Sequence[str] = DEFAULT_MODELS,
        conf: float = DEFAULT_CONF,
    ) -> DetectResult:
        if not models:
            raise ValueError("detect() needs at least one model name")
        params = {"models": ",".join(models), "conf": f"{conf:g}"}
        try:
            with self._client(self._detect_timeout_s) as http:
                resp = http.post(
                    self.base_url + "/detect",
                    params=params,
                    content=image,
                    headers={"Content-Type": content_type},
                )
        except httpx.HTTPError as exc:
            raise DetectorError(f"detector unreachable ({type(exc).__name__})") from exc
        if resp.status_code != 200:
            raise DetectorError(f"detector HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
            objects = [
                Detection(
                    model=str(o["model"]),
                    label=str(o["label"]),
                    conf=float(o["conf"]),
                    box=tuple(float(v) for v in o["box"]),  # type: ignore[arg-type]
                )
                for o in body.get("objects") or []
            ]
            result = DetectResult(
                width=int(body["width"]),
                height=int(body["height"]),
                objects=objects,
                elapsed_ms=None if body.get("elapsed_ms") is None else float(body["elapsed_ms"]),
            )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DetectorError(f"malformed /detect body ({type(exc).__name__})") from exc
        if any(len(o.box) != 4 for o in objects) or result.width <= 0 or result.height <= 0:
            raise DetectorError("malformed /detect body (box/size)")
        return result

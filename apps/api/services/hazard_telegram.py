"""Best-effort Telegram ping when a hazard / blind-spot check finishes with findings.

Optional by design (CLAUDE.md rule 8: the judged path never depends on venue internet):

- enabled only when ``config/telegram.yaml`` says ``enabled: true`` AND the bot token file
  exists (``AUM_TELEGRAM_TOKEN_FILE``, default ``~/.config/ambient-mirror/telegram.token``)
  AND a chat id is known (``AUM_TELEGRAM_CHAT_ID``, else
  ``~/.config/ambient-mirror/telegram.chat``); otherwise every call is a no-op;
- :func:`notify_job_async` sends on a daemon thread (6 s timeout, one retry) and never
  raises into, or waits inside, the hazard job; a failure logs one sanitised line;
- at most one ping per (clip, run) per ``repeat_after_s`` in this process.

The token is read from its file only when sending and never logged: the HTTP client is
``urllib.request`` (no request logging), and every error is reduced to the exception class
and HTTP status, because the request URL carries the token.

The message is plain worker language, built from the same worker view the screen shows::

    ⚠️ HAZARD DETECTED · CAM 3
    MACHINE GUARD · Zone 4 · high: Stop the machine and fit the guard
    BLOCKED AISLE · Zone 2 · medium: Move the stored materials
    Floor camera 02 · 14:32 CDT
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from apps.api.schemas import REPO_ROOT
from apps.api.services.hazards import (
    _SHORT_TITLE_CUTS,
    REVIEW_COMPLETE,
    SEVERITY_RANK,
    clip_kind,
    compose_worker,
    first_sentence,
    hazard_sign,
    is_plain,
    plain_text,
    report_evidence,
    screened_findings,
    short_title,
    zone_box,
    zone_name,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "telegram.yaml"
TOKEN_FILE_ENV = "AUM_TELEGRAM_TOKEN_FILE"
CHAT_ID_ENV = "AUM_TELEGRAM_CHAT_ID"
CONFIG_DIR = Path.home() / ".config" / "ambient-mirror"
DEFAULT_TOKEN_FILE = CONFIG_DIR / "telegram.token"
DEFAULT_CHAT_FILE = CONFIG_DIR / "telegram.chat"
API_BASE = "https://api.telegram.org"
TIMEOUT_S = 6.0
RETRY_DELAY_S = 1.0
CAPTION_MAX = 1024
MAX_FINDINGS = 3
ACTION_MAX_WORDS = 8
FULL_FRAME_KINDS = ("full scene", "motion peak")
OVERVIEW_IMAGE = "zones_overview.jpg"
# Words a short action may stop before without looking cut off.
_ACTION_BREAKS = _SHORT_TITLE_CUTS | frozenset(
    ["and", "or", "so", "then", "but", "to", "before", "after", "while", "until", "because"]
)
CHAT_ID_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
_DANGLING = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "to",
        "at",
        "by",
        "in",
        "on",
        "with",
        "for",
        "from",
        "near",
        "into",
        "onto",
        "so",
        "as",
        "if",
    ]
)
HEADLINES = {
    "hazard": "⚠️ HAZARD DETECTED",
    "blindspot": "👁 BLIND SPOT FOUND",
}


# --------------------------------------------------------------------------- settings


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool = False
    repeat_after_s: float = 300.0
    include_photo: bool = True
    token_file: Path = DEFAULT_TOKEN_FILE
    chat_file: Path = DEFAULT_CHAT_FILE
    chat_id: str | None = None  # from AUM_TELEGRAM_CHAT_ID


def load_settings(
    config_path: Path | None = None, env: Mapping[str, str] | None = None
) -> TelegramSettings:
    """``config/telegram.yaml`` plus the environment; never raises (bad config = off)."""
    env = os.environ if env is None else env
    path = DEFAULT_CONFIG_PATH if config_path is None else config_path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    try:
        repeat = max(float(raw.get("repeat_after_s", 300.0)), 0.0)
    except (TypeError, ValueError):
        repeat = 300.0
    token_file = env.get(TOKEN_FILE_ENV) or str(DEFAULT_TOKEN_FILE)
    chat_env = (env.get(CHAT_ID_ENV) or "").strip() or None
    return TelegramSettings(
        enabled=raw.get("enabled") is True,
        repeat_after_s=repeat,
        include_photo=raw.get("include_photo", True) is not False,
        token_file=Path(token_file).expanduser(),
        chat_file=DEFAULT_CHAT_FILE,
        chat_id=chat_env,
    )


def read_token(settings: TelegramSettings) -> str | None:
    try:
        token = settings.token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def read_chat_id(settings: TelegramSettings) -> str | None:
    chat = settings.chat_id
    if not chat:
        try:
            chat = settings.chat_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return chat if chat and CHAT_ID_RE.match(chat) else None


def connected(settings: TelegramSettings) -> bool:
    """Enabled in config, token file present and a valid chat id known."""
    return settings.enabled and settings.token_file.is_file() and read_chat_id(settings) is not None


# --------------------------------------------------------------------------- message


@dataclass(frozen=True)
class Alert:
    caption: str
    photo: Path | None
    findings: int
    # Where the danger is: the top hazard's zone boxes (0-1 video coordinates) and its label,
    # drawn on the clean photo (only that hazard, so the picture points at one place).
    marks: tuple[tuple[tuple[float, float, float, float], str], ...] = ()


def danger_marks(
    report: Mapping[str, Any], wording: Mapping[str, Any], kind: str
) -> tuple[tuple[tuple[float, float, float, float], str], ...]:
    """The top screened hazard's zone boxes, each labelled ``SIGN · ZONE n``."""
    ranked = _ranked_findings(report)
    if not ranked:
        return ()
    top = ranked[0]
    label = hazard_sign(top.get("standards"), wording, kind=kind)["label"]
    video = report.get("video") if isinstance(report.get("video"), dict) else {}
    zones = {str(z.get("zone_id")): z for z in report.get("zones") or [] if isinstance(z, dict)}
    marks = []
    for zone_id in top.get("zone_ids") or []:
        zone = zones.get(str(zone_id))
        box = zone_box(zone, video) if zone else None
        if box:
            name = zone_name(zone_id, wording) or ""
            text = f"{label} · {name.upper()}" if name else label
            marks.append(((box[0], box[1], box[2], box[3]), text))
    return tuple(marks[:2])


def mark_photo(data: bytes, marks: Any) -> bytes:
    """``data`` (a JPEG) with an amber box and a label at each mark; unchanged on any error."""
    if not marks:
        return data
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw, ImageFont

        image = Image.open(BytesIO(data)).convert("RGB")
        w, h = image.size
        draw = ImageDraw.Draw(image)
        line = max(4, w // 160)
        font = ImageFont.load_default(size=max(18, w // 40))
        amber, ink = (255, 176, 32), (5, 5, 5)
        for (x0, y0, x1, y1), text in marks:
            box = (x0 * w, y0 * h, x1 * w, y1 * h)
            draw.rectangle(box, outline=amber, width=line)
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            pad = line
            tw, th = right - left + 2 * pad, bottom - top + 2 * pad
            tx = min(max(0, box[0]), max(0, w - tw))
            ty = box[1] - th if box[1] - th >= 0 else box[3]
            draw.rectangle((tx, ty, tx + tw, ty + th), fill=amber)
            draw.text((tx + pad - left, ty + pad - top), text, fill=ink, font=font)
        out = BytesIO()
        image.save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - the clean photo is better than no ping
        logger.warning("telegram: could not mark the photo; sending it clean")
        return data


def short_action(actions: Any) -> str:
    """The first clause of the first plain recommended action, at most
    :data:`ACTION_MAX_WORDS` words, cut at a word boundary (same cut rule as the card
    titles). Empty when there is no plain action."""
    for action in actions if isinstance(actions, list) else []:
        text = first_sentence(str(action)).strip()
        clause = re.split(r"[;:,]\s|\s[-–—]\s|\.\s*$", text, maxsplit=1)[0].strip()
        full = clause.rstrip(" .,;:").split()
        words = short_title(clause, ACTION_MAX_WORDS).rstrip(" .,;:").split()
        while len(words) > 1 and words[-1].lower() in _DANGLING:
            words.pop()
        # A cut that is not at a phrase boundary ("... at the corner") ends in "…", so the
        # phone never shows half a sentence as if it were complete.
        cut_mid_phrase = (
            0 < len(words) < len(full)
            and full[len(words)].lower().strip(",;:") not in _ACTION_BREAKS
        )
        clause = " ".join(words) + ("…" if cut_mid_phrase else "")
        if clause and is_plain(clause):
            return clause
    return ""


def _finding_line(hazard: Mapping[str, Any], severity: str) -> str | None:
    sign = hazard.get("sign") if isinstance(hazard.get("sign"), Mapping) else {}
    label = str(sign.get("label") or "HAZARD").strip().upper()
    parts = [label]
    zones = [z for z in hazard.get("zone_names") or [] if is_plain(z)]
    if zones:
        parts.append(", ".join(zones[:2]))
    head = " · ".join(parts)
    level = severity if severity in SEVERITY_RANK else ""
    given = hazard.get("short_action")
    action = str(given).strip() if is_plain(given) else short_action(hazard.get("what_to_do"))
    if not action:
        title = hazard.get("short_title") or hazard.get("title")
        action = str(title).strip() if is_plain(title) else ""
    line = head
    if level:
        line = f"{line} · {level}"
    if action:
        line = f"{line}: {action}"
    if is_plain(line):
        return line
    return head if is_plain(head) else None


def _ranked_findings(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Report findings in the worker view's order (severity, then report order)."""
    raw = screened_findings(report)
    ranked = sorted(
        enumerate(raw, 1), key=lambda p: (SEVERITY_RANK.get(str(p[1].get("severity")), 1), p[0])
    )
    return [f for _, f in ranked]


def _local_time(now: datetime | None) -> str:
    now = (now or datetime.now().astimezone()).astimezone()
    return f"{now:%H:%M} {now:%Z}".strip()


def build_caption(
    *,
    clip: Mapping[str, Any],
    report: Mapping[str, Any],
    wording: Mapping[str, Any],
    cam: int | None,
    now: datetime | None = None,
) -> tuple[str, int]:
    """``(caption, findings)``: the plain Telegram text and the number of findings (0 = do
    not send). Pure apart from the clock."""
    kind = clip_kind(clip)
    worker = compose_worker(clip=clip, report=report, status="reviewed", wording=wording)
    hazards = worker.get("hazards") or []
    ranked = _ranked_findings(report)
    if not hazards:
        return "", 0
    head = HEADLINES["blindspot" if kind == "blindspot" else "hazard"]
    if cam is not None:
        head = f"{head} · CAM {cam}"
    lines = []
    for hazard, finding in list(zip(hazards, ranked, strict=False))[:MAX_FINDINGS]:
        line = _finding_line(hazard, str(finding.get("severity") or "").lower())
        if line:
            lines.append(line)
    if len(hazards) > MAX_FINDINGS:
        lines.append(f"+{len(hazards) - MAX_FINDINGS} more on screen")
    title = plain_text(clip.get("title"))
    name = title if is_plain(title) else ("Warehouse camera" if kind == "blindspot" else "Camera")
    footer = f"{name} · {_local_time(now)}"
    while lines and len("\n".join([head, *lines, footer])) > CAPTION_MAX:
        lines.pop()
    caption = "\n".join([head, *lines, footer])
    return caption[:CAPTION_MAX], len(hazards)


def choose_photo(store: Any, run_dir: Path | None, report: Mapping[str, Any]) -> Path | None:
    """ONE clean full-frame picture with no markings (the user asked for no outlines on the
    ping): the earliest full-scene picture cited by the first (highest priority) finding,
    else the run's earliest full-scene picture, as its clean worker copy; else None (a
    text-only message). Never ``zones_overview.jpg``, which has the zones drawn on it."""
    if run_dir is None:
        return None
    by_id = {e["evidence_id"]: e for e in report_evidence(report)}
    ranked = _ranked_findings(report)
    cited = [e for e in (ranked[0].get("evidence_ids") or []) if e in by_id] if ranked else []
    rest = [e for e in by_id if e not in cited]
    for group in (cited, rest):
        for evidence_id in sorted(group, key=lambda e: float(by_id[e].get("timestamp_s") or 0.0)):
            if str(by_id[evidence_id].get("kind")) not in FULL_FRAME_KINDS:
                continue
            try:
                path = store.clean_evidence_path(run_dir, report, evidence_id)
            except Exception:  # noqa: BLE001 - a broken picture only means another picture
                path = None
            if path is not None and Path(path).is_file():
                return Path(path)
    return None


def wall_cam(service: Any, clip_id: str) -> int | None:
    """The clip's CAM number on the home wall (config/wall.yaml), or None."""
    try:
        from apps.api.services import wall as wall_service

        doc = wall_service.wall(service)
    except Exception:  # noqa: BLE001 - no CAM number is fine
        return None
    for tile in [*doc.get("hazard_tiles", []), *doc.get("blindspot_tiles", [])]:
        if tile.get("clip_id") == clip_id:
            return int(tile["cam"])
    return None


def resolve_run_dir(service: Any, clip_id: str, run_id: str | None) -> Path | None:
    store = service.store
    if run_id:
        for run_dir in store.run_dirs(clip_id):
            if run_dir.name == run_id:
                return run_dir
    return store.current_run_dir(clip_id)


def alert_for_run(
    service: Any,
    clip_id: str,
    run_id: str | None,
    *,
    include_photo: bool = True,
    now: datetime | None = None,
) -> Alert | None:
    """The alert for one finished check of ``clip_id`` (its run ``run_id``, else the
    clip's current run). None when the clip, run or a completed report is missing."""
    store = service.store
    clip = store.clip(clip_id)
    run_dir = resolve_run_dir(service, clip_id, run_id)
    report = store.report(run_dir)
    if clip is None or not report or report.get("status") != REVIEW_COMPLETE:
        return None
    caption, count = build_caption(
        clip=clip,
        report=report,
        wording=service.wording(),
        cam=wall_cam(service, clip_id),
        now=now,
    )
    photo = choose_photo(store, run_dir, report) if include_photo and count else None
    marks = danger_marks(report, service.wording(), clip_kind(clip)) if photo else ()
    return Alert(caption=caption, photo=photo, findings=count, marks=marks)


# --------------------------------------------------------------------------- sending


class TelegramError(Exception):
    """A failed Bot API call. Its text is only ``method: ExceptionClass [HTTP status]``."""

    def __init__(self, method: str, kind: str, status: int | None = None) -> None:
        self.method, self.kind, self.status = method, kind, status
        tail = f" {status}" if status is not None else ""
        super().__init__(f"{method}: {kind}{tail}")


class Sender(Protocol):
    def __call__(self, chat_id: str, caption: str, photo: bytes | None) -> int: ...


def _multipart(fields: Mapping[str, str], photo: bytes) -> tuple[bytes, str]:
    boundary = f"aum{uuid.uuid4().hex}"
    out = bytearray()
    for name, value in fields.items():
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
        f'filename="camera.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
    ).encode()
    out += photo + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def call_api(
    token: str,
    method: str,
    fields: Mapping[str, Any] | None = None,
    *,
    photo: bytes | None = None,
    timeout_s: float = TIMEOUT_S,
) -> Any:
    """One Bot API call; returns ``result``. Raises :class:`TelegramError` whose text never
    holds the URL (it carries the token)."""
    url = f"{API_BASE}/bot{token}/{method}"
    fields = {k: str(v) for k, v in (fields or {}).items()}
    if photo is not None:
        body, ctype = _multipart(fields, photo)
    else:
        body, ctype = json.dumps(fields).encode(), "application/json"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    status: int | None = None
    kind = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status, kind = exc.code, type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - URLError, timeout, bad JSON: class name only
        kind = type(exc).__name__
    if kind:
        raise TelegramError(method, kind, status) from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise TelegramError(method, "NotOk", None)
    return payload.get("result")


def urllib_sender(token: str, timeout_s: float = TIMEOUT_S) -> Sender:
    def send(chat_id: str, caption: str, photo: bytes | None) -> int:
        if photo is not None:
            result = call_api(
                token,
                "sendPhoto",
                {"chat_id": chat_id, "caption": caption[:CAPTION_MAX]},
                photo=photo,
                timeout_s=timeout_s,
            )
        else:
            result = call_api(
                token, "sendMessage", {"chat_id": chat_id, "text": caption}, timeout_s=timeout_s
            )
        return int(result.get("message_id", 0)) if isinstance(result, dict) else 0

    return send


def _sanitize(exc: BaseException, secrets: tuple[str, ...]) -> str:
    if isinstance(exc, TelegramError):
        text = str(exc)
    else:
        text = type(exc).__name__
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


# --------------------------------------------------------------------------- notifier


_LOCK = threading.Lock()
_SENT: dict[tuple[str, str], float] = {}
_LAST: dict[str, Any] = {}


def _record(status: str, **extra: Any) -> dict[str, Any]:
    entry = {"status": status, "at": datetime.now().astimezone().isoformat(), **extra}
    with _LOCK:
        _LAST.clear()
        _LAST.update(entry)
    return entry


def last_status(settings: TelegramSettings | None = None) -> dict[str, Any]:
    """Diagnostics without secrets: the last ``sent`` / ``failed`` / ``not_connected``
    outcome and its time; before any attempt, whether the notifier is connected."""
    with _LOCK:
        if _LAST:
            return dict(_LAST)
    settings = settings or load_settings()
    return {"status": "connected" if connected(settings) else "not_connected", "at": None}


def reset_dedupe() -> None:
    with _LOCK:
        _SENT.clear()
        _LAST.clear()


def _claim(key: tuple[str, str], window_s: float, now: float) -> bool:
    with _LOCK:
        last = _SENT.get(key)
        if last is not None and now - last < window_s:
            return False
        _SENT[key] = now
        return True


def notify_job(
    service: Any,
    clip_id: str,
    run_id: str | None,
    *,
    settings: TelegramSettings | None = None,
    sender: Sender | None = None,
    dedupe: bool = True,
    retry_delay_s: float = RETRY_DELAY_S,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Send the ping for one finished check, synchronously. Never raises. Returns a status
    dict: ``sent`` (with ``message_id``), ``failed``, ``not_connected`` or ``skipped``
    (no findings / already pinged)."""
    token = ""
    try:
        settings = settings or load_settings()
        chat_id = read_chat_id(settings)
        if not settings.enabled or chat_id is None or not settings.token_file.is_file():
            return _record("not_connected")
        if sender is None and os.environ.get("PYTEST_CURRENT_TEST"):
            return _record("not_connected")  # tests never reach the real bot
        if sender is None:
            token = read_token(settings) or ""
            if not token:
                return _record("not_connected")
        alert = alert_for_run(service, clip_id, run_id, include_photo=settings.include_photo)
        if alert is None or alert.findings < 1:
            return {"status": "skipped", "reason": "no findings"}
        key = (str(clip_id), str(run_id or ""))
        if dedupe and not _claim(key, settings.repeat_after_s, clock()):
            return {"status": "skipped", "reason": "already sent"}
        photo = None
        if alert.photo is not None:
            try:
                photo = mark_photo(alert.photo.read_bytes(), alert.marks)
            except OSError:
                photo = None
        send = sender or urllib_sender(token)
        error: BaseException | None = None
        for attempt in range(2):
            try:
                message_id = send(chat_id, alert.caption, photo)
                return _record("sent", message_id=message_id, photo=photo is not None)
            except Exception as exc:  # noqa: BLE001 - retried once, logged without the URL
                error = exc
                if (
                    isinstance(exc, TelegramError)
                    and exc.status is not None
                    and 400 <= exc.status < 500
                    and exc.status != 429
                ):
                    if photo is None:
                        break
                    photo = None  # a rejected picture: the retry sends the text alone
                    continue
                if attempt == 0 and retry_delay_s > 0:
                    time.sleep(retry_delay_s)
        detail = _sanitize(error, (token,)) if error else "unknown"
        logger.warning("telegram ping not sent: %s", detail)
        return _record("failed", detail=detail)
    except Exception as exc:  # noqa: BLE001 - never into the hazard job
        detail = _sanitize(exc, (token,))
        logger.warning("telegram ping not sent: %s", detail)
        return _record("failed", detail=detail)


def notify_job_async(
    service: Any,
    clip_id: str,
    run_id: str | None,
    **kwargs: Any,
) -> threading.Thread | None:
    """Fire-and-forget :func:`notify_job` on a daemon thread; never raises, never blocks."""
    try:
        thread = threading.Thread(
            target=notify_job,
            args=(service, clip_id, run_id),
            kwargs=kwargs,
            name=f"telegram-{clip_id}",
            daemon=True,
        )
        thread.start()
        return thread
    except Exception as exc:  # noqa: BLE001 - never into the hazard job
        logger.warning("telegram ping not started: %s", type(exc).__name__)
        return None

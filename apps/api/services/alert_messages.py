"""Plain-language alert messages for the worker view and Telegram (deterministic, local).

No model call, no network and no FastAPI: the event-day agent policy can import this
module to send the identical Telegram text. Inputs are model-facing data only (the
``ModelScenarioView``, evidence items, region candidates, the hypothesis) plus the
scenario's wall-clock start, so nothing here can see the withheld ground-truth camera.

Kinds (``contracts/SSE_EVENTS.md``):

* ``ping``: one unconfirmed heads-up from the first observation whose cue pings.
* ``alert``: the final hypothesis claims a known event (any confidence; "How sure" says
  how likely it is, and a weak claim reads "Unsure (n%)").
* ``unconfirmed``: an abstention (``unknown``). Calm, no alarm.
* ``all_clear``: ``no_event``.

Wording (labels, levels, actions, which cues ping) comes from ``config/alerts.yaml``;
unknown snake_case types read as words ("forklift_near_miss" -> "Forklift near miss"),
anything else that is not a plain type name reads "Something unusual". The reasoning
model's free text (``reason``, ``limitations``) is never used. Perception descriptions
are, after :func:`describe_observation`: one short sentence, and any sentence that is
technical, addresses the reader or mentions a camera that is not on screen is dropped
whole, never cut into fragments.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from apps.api.schemas import (
    ALERT_LEVELS,
    REPO_ROOT,
    UNKNOWN,
    AlertLine,
    AlertMessage,
    EvidenceBundle,
    Hypothesis,
    ModelCamera,
    ModelScenarioView,
    Scenario,
    Zone,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "alerts.yaml"
NO_EVENT = "no_event"
# Provenance keys that may hold the wall-clock time of scenario t = 0 (first match wins).
START_TIME_KEYS = ("scenario_time_zero_wallclock", "start_wallclock", "start_time")

# Urgency in words: how fast to react, not what the system thinks.
DEFAULT_LEVEL_WORDS = {"danger": "ACT NOW", "warning": "CHECK SOON", "info": "NO RUSH"}
# Kinds whose first Telegram row starts with the urgency word; the calm kinds start with
# their headline (the worker card shows the level word for the same kinds only).
URGENT_KINDS = frozenset({"ping", "alert"})
DEFAULT_ACTION = "Check the area and confirm what happened."
UNCONFIRMED_ACTION = "No action needed now. A supervisor can review the footage."
ALL_CLEAR_ACTION = "Nothing to do."
PING_ACTION = "Be ready to check the area. The other cameras are still being checked."
INFERRED_NOTE = "Not seen directly; pieced together from the other cameras."
# The label of any event or cue type that is neither configured nor a plain type name.
UNKNOWN_TYPE_LABEL = "Something unusual"

UNCONFIRMED_HEADLINE = "Something was seen, but nothing is confirmed"
UNCONFIRMED_WHAT = "The cameras picked up some activity but could not confirm what happened."
ALL_CLEAR_HEADLINE = "All clear: nothing unusual seen"
ALL_CLEAR_WHAT = "The cameras did not show anything unusual."
NOT_CONFIRMED = "Not confirmed"
UNCLEAR_WHERE = "Exact spot unclear"

MAX_DESCRIPTIONS = 1
MAX_DESCRIPTION_CHARS = 110
MAX_DETAIL_CHARS = 160
MAX_TYPE_CHARS = 40
NEXT_TO_M = 5.0
# A clause cut keeps at least this much of a long description.
MIN_CLIP_CHARS = 40
# Without a scenario duration, times are clamped to one day.
MAX_CLIP_SECONDS = 24 * 3600
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_COMPASS_WORDS = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)


# --- leak patterns --------------------------------------------------------------------------
# A sentence that matches any of these is dropped whole (see sanitize_text); a type label
# that matches one reads UNKNOWN_TYPE_LABEL.

_NUM = r"[+-]?\d+(?:\.\d+)?"
_URL = re.compile(
    r"\b(?:https?://|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|ai|dev|app|xyz|ru|cn)\b",
    re.IGNORECASE,
)
_BARE_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_INTERNAL_ID = re.compile(
    r"(?<![\w-])(?:region|clu|cluster|cand|candidate|ray|call|msg|run)_[A-Za-z0-9_]+(?![\w-])",
    re.IGNORECASE,
)
_SNAKE = re.compile(r"\b[A-Za-z]+_[A-Za-z0-9_]+\b")
_BEARING = re.compile(
    rf"\b(?:bearing|heading|azimuth)s?\s*(?:of\s*|=\s*|:\s*)?{_NUM}|\bbearings?\b|\bazimuth\b",
    re.IGNORECASE,
)
_DEGREES = re.compile(rf"°|º|{_NUM}\s*deg(?:rees)?\b|\bdeg\b", re.IGNORECASE)
_COORD = re.compile(
    rf"\b[XYZ]\s*(?:[=:]\s*{_NUM}|[+-]\s*\d+(?:\.\d+)?)|\bR\s*[=:]?\s*\d+(?:\.\d+)?\s*m\b"
    rf"|[\[(]\s*{_NUM}\s*,\s*{_NUM}(?:\s*,\s*{_NUM})?\s*[\])]",
    re.IGNORECASE,
)
_DECIMALS = r"\d*\.\d+(?:\s*/\s*\d*\.\d+)*"
_SCORE = re.compile(
    r"\b(?:(?:clustering|cluster|region|candidate|fusion|overall|model)\s+)?"
    r"(?:score|confidence|probability|likelihood|weight)\s*(?:of|=|:|is)?\s*"
    rf"(?:\(\s*{_DECIMALS}\s*\)|{_DECIMALS})",
    re.IGNORECASE,
)
_TIME_CODE = re.compile(r"\bt\s*=\s*[\d.]+\s*(?:[-–]\s*[\d.]+)?\s*s\b", re.IGNORECASE)
_DECIMAL = re.compile(r"\d*\.\d+")
_FRAME_TECH = re.compile(
    r"\bframe\s*(?:index|idx|no\.?|number|#)|\bframes?\s*[=:#]?\s*\d+\b|\bpixels?\b|\bpx\b"
    r"|\bfov\b|\bfield of view\b|\bb(?:ounding)?[\s_-]?box(?:es)?\b|\btrack(?:ing)?[\s_-]?ids?\b"
    r"|\bquadrants?\b|\bconfidence\b|\bprobabilit(?:y|ies)\b",
    re.IGNORECASE,
)
_PATH = re.compile(
    r"(?<![\w/])(?:~|[A-Za-z]:)?[\\/][\w.@-]+[\\/]|~/[\w.-]+"
    r"|\b[\w.-]+/[\w.-]+/[\w.-]+"
    r"|\b[\w-]+\.(?:mp4|avi|mov|mkv|webm|json|jsonl|ya?ml|py|env|txt|log|csv|jpe?g|png|db"
    r"|sqlite|pem|key)\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(
    r"\b\d{6,}:[A-Za-z0-9_-]{10,}|\b[A-Za-z0-9_\-]{32,}\b|\bsk-[A-Za-z0-9_-]{8,}"
    r"|\beyJ[\w-]*\.[\w-]+|\b[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b|\d{7,}|\bBearer\s+\S{8,}"
    r"|\b(?:token|api[_-]?key|secret|password|passwd|chat_id)\s*[=:]\s*\S+",
    re.IGNORECASE,
)
_GROUND_TRUTH = re.compile(
    r"\bground[\s_-]*truth\b|\bwithheld\b|\bhidden[\s_-]+cam(?:era)?s?\b|\bjudge[sd]?\b"
    r"|\bcam(?:era)?[\s_-]*gt\b",
    re.IGNORECASE,
)
_DATASET_CODE = re.compile(r"\b[A-Z]\d{3,}\b")
# Compass abbreviations and "az 350": the messages say "north-east" in words.
_COMPASS_CODE = re.compile(r"\b(?:NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|NW|SE|SW)\b|\b[Aa][Zz]\s*\d")
_JARGON_SENTENCE = re.compile(
    r"\b(?:cluster\w*|triangulat\w*|candidates?|scores?|abstain\w*|harness|sse|evidence"
    r"|fusion|rays?|hypothes[ie]s|profile)\b",
    re.IGNORECASE,
)
_TECHNICAL = (
    _URL,
    _INTERNAL_ID,
    _SNAKE,
    _BEARING,
    _DEGREES,
    _COORD,
    _SCORE,
    _TIME_CODE,
    _DECIMAL,
    _FRAME_TECH,
    _PATH,
    _TOKEN,
    _GROUND_TRUTH,
    _DATASET_CODE,
    _COMPASS_CODE,
    _JARGON_SENTENCE,
)


def is_technical(text: str) -> bool:
    """True when ``text`` holds anything a worker must not read: an id, coordinate,
    bearing, score, decimal, URL, path, token, frame/pixel talk, pipeline jargon, or
    a mention of the withheld camera or the judge."""
    return any(pattern.search(text) for pattern in _TECHNICAL)


# --- config ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class EventWording:
    label: str
    level: str
    action: str


@dataclass(frozen=True)
class CueWording:
    label: str
    ping: bool
    transit: bool
    level: str


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _text(value: object) -> str | None:
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())
    return text or None


def humanize(type_name: str, acronyms: Iterable[str] = ()) -> str:
    """``"forklift_near_miss"`` -> ``"Forklift near miss"``; listed acronyms stay upper-case."""
    upper = {a.lower() for a in acronyms}
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(type_name)) if w]
    if not words:
        return "Something"
    out = [w.upper() if w.lower() in upper else w.lower() for w in words]
    if out[0].lower() not in upper:
        out[0] = out[0].capitalize()
    return " ".join(out)


# A plain type name: lower snake_case, a few words, starting with a letter.
_TYPE_SHAPE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){0,5}$")
# Internal-id prefixes and a trailing counter ("region_01", "blind_zone_02") are ids, not types.
_ID_LIKE = re.compile(r"^(?:region|cam|obs|clu|cand|z|run|msg)_|_\d+$")


def type_label(type_name: object, acronyms: Iterable[str] = ()) -> str:
    """The words for an event or cue type that is not configured: a plain snake_case
    type is humanized; anything else (free text, ids, numbers) is UNKNOWN_TYPE_LABEL."""
    raw = str(type_name or "").strip()
    if len(raw) > MAX_TYPE_CHARS or not _TYPE_SHAPE.match(raw) or _ID_LIKE.search(raw):
        return UNKNOWN_TYPE_LABEL
    label = humanize(raw, acronyms)
    return UNKNOWN_TYPE_LABEL if is_technical(label) else label


def _plain_label(value: object) -> str | None:
    """A configured label, unless it would leak (then the caller falls back)."""
    label = _text(value)
    return label if label and not is_technical(label) else None


def _looks_transit(key: str) -> bool:
    return bool(re.search(r"(^|_)(transit|passing|pass_through|passes)(_|$)", key))


def _level(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value in ALERT_LEVELS else fallback


@dataclass(frozen=True)
class AlertConfig:
    """Wording for alert messages. ``AlertConfig()`` is the built-in fallback."""

    product: str = "CameraVision"
    level_words: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_LEVEL_WORDS))
    events: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    cues: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    default_level: str = "warning"
    default_action: str = DEFAULT_ACTION
    ping_level: str = "warning"
    ping_how_sure: str = "Not confirmed yet"
    ping_action: str = PING_ACTION
    unconfirmed_action: str = UNCONFIRMED_ACTION
    all_clear_action: str = ALL_CLEAR_ACTION
    inferred_note: str = INFERRED_NOTE
    acronyms: frozenset[str] = frozenset()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AlertConfig:
        base = cls()
        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), Mapping) else {}
        levels = raw.get("levels") if isinstance(raw.get("levels"), Mapping) else {}

        def table(name: str) -> dict[str, Mapping[str, Any]]:
            section = raw.get(name)
            if not isinstance(section, Mapping):
                return {}
            return {_key(k): v for k, v in section.items() if isinstance(v, Mapping)}

        def text(key: str, fallback: str) -> str:
            return _text(defaults.get(key)) or fallback

        acronyms = defaults.get("acronyms")
        acronyms = (
            frozenset(a.lower() for a in acronyms if isinstance(a, str))
            if isinstance(acronyms, list)
            else base.acronyms
        )
        return cls(
            product=_text(raw.get("product")) or base.product,
            level_words={
                lvl: _text(levels.get(lvl)) or DEFAULT_LEVEL_WORDS[lvl] for lvl in ALERT_LEVELS
            },
            events=table("events"),
            cues=table("cues"),
            default_level=_level(defaults.get("level"), base.default_level),
            default_action=text("action", base.default_action),
            ping_level=_level(defaults.get("ping_level"), base.ping_level),
            ping_how_sure=text("ping_how_sure", base.ping_how_sure),
            ping_action=text("ping_action", base.ping_action),
            unconfirmed_action=text("unconfirmed_action", base.unconfirmed_action),
            all_clear_action=text("all_clear_action", base.all_clear_action),
            inferred_note=text("inferred_note", base.inferred_note),
            acronyms=acronyms,
        )

    def event(self, event_type: str) -> EventWording:
        entry = self.events.get(_key(event_type))
        if entry is None:  # not configured: plain words for a plain type, defaults otherwise
            return EventWording(
                type_label(event_type, self.acronyms), self.default_level, self.default_action
            )
        return EventWording(
            label=_plain_label(entry.get("label")) or type_label(event_type, self.acronyms),
            level=_level(entry.get("level"), self.default_level),
            action=_text(entry.get("action")) or self.default_action,
        )

    def cue(self, cue_type: str) -> CueWording:
        key = _key(cue_type)
        entry = self.cues.get(key, {})
        transit = bool(entry.get("transit", _looks_transit(key)))
        return CueWording(
            label=_plain_label(entry.get("label")) or type_label(cue_type, self.acronyms),
            ping=bool(entry.get("ping", False)) and not transit,  # transit never pings
            transit=transit,
            level=_level(entry.get("level"), self.ping_level),
        )

    def level_word(self, level: str) -> str:
        return self.level_words.get(level) or DEFAULT_LEVEL_WORDS.get(level, level.upper())


_config_lock = threading.Lock()
_config_cache: dict[Path, tuple[tuple[int, int], AlertConfig]] = {}


def load_alert_config(path: Path | str | None = None) -> AlertConfig:
    """Load ``config/alerts.yaml`` (cached until the file changes). A missing or broken
    file logs a warning and returns the built-in wording; it never fails a run."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        stat = path.stat()
    except OSError:
        logger.warning("alert config %s not found; using built-in wording", path.name)
        return AlertConfig()
    signature = (stat.st_mtime_ns, stat.st_size)
    with _config_lock:
        cached = _config_cache.get(path)
        if cached and cached[0] == signature:
            return cached[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise TypeError("top level must be a mapping")
        config = AlertConfig.from_mapping(raw)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        logger.warning(
            "alert config %s unusable (%s); using built-in wording", path.name, type(exc).__name__
        )
        config = AlertConfig()
    with _config_lock:
        _config_cache[path] = (signature, config)
    return config


# --- scenario context -----------------------------------------------------------------------

# Same rule as cameraName() in apps/web/src/lib/plain.ts, so the screen and Telegram agree.
_CAMERA_ID = re.compile(r"^cam(?:era)?[_\-\s]?([a-z]|\d{1,3})$", re.IGNORECASE)


def _pattern_name(camera_id: str) -> str | None:
    match = _CAMERA_ID.match(camera_id.strip())
    if not match:
        return None
    token = match.group(1)
    return f"Camera {token.upper() if token.isalpha() else int(token)}"


def camera_display_name(camera_id: str, index: int) -> str:
    """``cam_b`` -> ``Camera B``, ``cam_02`` -> ``Camera 2``; any other id is named by its
    1-based slot among the visible cameras (``dock_left`` at index 0 -> ``Camera 1``)."""
    return _pattern_name(camera_id) or f"Camera {index + 1}"


def camera_display_names(camera_ids: Iterable[str]) -> dict[str, str]:
    """Friendly names for the visible cameras, in scenario order. Never the raw id."""
    return {cid: camera_display_name(cid, i) for i, cid in enumerate(dict.fromkeys(camera_ids))}


def scenario_start_wallclock(provenance: Mapping[str, Any] | None) -> datetime | None:
    """Wall-clock time of scenario t = 0 from public provenance scalars, if recorded."""
    if not isinstance(provenance, Mapping):
        return None
    for key in START_TIME_KEYS:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                continue
    return None


@dataclass(frozen=True)
class MessageContext:
    """What a message may draw on: the model view (visible cameras, zones) and the start."""

    view: ModelScenarioView
    start_wallclock: datetime | None = None

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> MessageContext:
        return cls(scenario.model_view(), scenario_start_wallclock(scenario.provenance))

    @cached_property
    def cameras(self) -> dict[str, ModelCamera]:
        return {cam.id: cam for cam in self.view.cameras}

    @cached_property
    def camera_names(self) -> dict[str, str]:
        return camera_display_names(self.cameras)

    @cached_property
    def zones(self) -> dict[str, Zone]:
        return {zone.id: zone for zone in self.view.zones}

    def camera_name(self, camera_id: str) -> str | None:
        return self.camera_names.get(camera_id)

    def camera_order(self, camera_ids: Iterable[str]) -> list[str]:
        wanted = set(camera_ids)
        return [cid for cid in self.cameras if cid in wanted]


# --- sanitizer ------------------------------------------------------------------------------

_OBS_REF = re.compile(r"(?<![\w.:#-])([A-Za-z][\w-]*?)[.:#](o\d+|obs[\w-]*?\d+)(?:#\d+)?(?![\w#])")
_CAMERA_LIKE = re.compile(r"(?<![\w-])cam(?:era)?[_-][A-Za-z0-9]+(?![\w-])", re.IGNORECASE)
_PAREN = re.compile(r"\s*\(([^()]*)\)")
_LEAD_CUES = re.compile(
    r"^(?:the\s+)?(?:cues?|observations?|evidence)\s+(?=Camera\b)", re.IGNORECASE
)
_SUBSTITUTIONS = (
    (re.compile(r"\bblind[\s-]zones?\b", re.IGNORECASE), "blind spot"),
    # camera-frame wording: a supervisor does not know which way "left of the frame" is
    (re.compile(r"\benters? the frame\b", re.IGNORECASE), "comes into view"),
    (re.compile(r"\b(?:leaves|exits) the frame\b", re.IGNORECASE), "goes out of view"),
    (
        re.compile(
            r"\s*\b(?:on|from|at|in|to|toward|towards)\s+the\s+(?:[a-z]+\s+){0,2}?"
            r"(?:side|edge|corner|part)?\s*of\s+(?:the\s+)?(?:frame|image|screen)\b",
            re.IGNORECASE,
        ),
        "",
    ),
    (re.compile(r"\binto (?:the )?frame\b", re.IGNORECASE), "into view"),
    (re.compile(r"\bout of (?:the )?frame\b", re.IGNORECASE), "out of view"),
    (re.compile(r"\bin (?:the )?frame\b", re.IGNORECASE), "in view"),
    (re.compile(r"\bthe frame\b", re.IGNORECASE), "the view"),
    (re.compile(r"\bcues\b", re.IGNORECASE), "signs"),
    (re.compile(r"\bcue\b", re.IGNORECASE), "sign"),
    (re.compile(r"\bregions\b", re.IGNORECASE), "areas"),
    (re.compile(r"\bregion\b", re.IGNORECASE), "area"),
)
_NAME = r"(?:Camera [A-Z0-9]+)"
_DUPLICATE_NAMES = re.compile(rf"\b({_NAME})(?:\s*(?:,|and|&)\s*\1\b)+")
_REPEATED_PAREN = re.compile(r"\b([\w’' -]{2,40}?)\s*\(\s*\1\s*\)", re.IGNORECASE)
_SINGULAR_VERB = re.compile(
    r"(?<!and )(?<!, )(?<!& )\b(Camera [A-Z0-9]+) "
    r"(show|depict|confirm|indicate|suggest|reveal|capture|record)\b"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\s*\n+\s*")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_CLAUSE_BREAK = re.compile(r"[,;]\s|\s(?:while|as|then|and then|before|after|where|which)\s")


class _Hidden(Exception):
    """A sentence mentions a camera that is not on screen: drop it whole."""


def _replace_ids(text: str, names: Mapping[str, str]) -> str:
    """Replace each id in ``names`` (longest first, whole identifiers only)."""
    for token in sorted(names, key=len, reverse=True):
        pattern = rf"(?<![\w.:#-]){re.escape(token)}(?![\w#-]|\.[A-Za-z0-9])"
        text = re.sub(pattern, lambda _m, name=names[token]: name, text)
    return text


def _camera(camera_id: str, names: Mapping[str, str]) -> str:
    """A visible camera's name. With a scenario context (``names`` set) any other id, the
    withheld camera's included, hides the sentence; without one, the id pattern decides."""
    name = names.get(camera_id) if names else _pattern_name(camera_id)
    if name is None:
        raise _Hidden(camera_id)
    return name


def _rewrite_ids(
    sentence: str,
    names: Mapping[str, str],
    evidence_cameras: Mapping[str, str] | None,
    zone_labels: Mapping[str, str],
) -> str:
    """Known ids become what a person calls them; raises ``_Hidden`` for any other camera."""
    if evidence_cameras:
        refs = {e: c for e, c in evidence_cameras.items() if e}
        for evidence_id in sorted(refs, key=len, reverse=True):
            pattern = rf"(?<![\w.:#-]){re.escape(evidence_id)}(?![\w#-]|\.[A-Za-z0-9])"
            if re.search(pattern, sentence):
                name = _camera(refs[evidence_id], names)
                sentence = re.sub(pattern, lambda _m, n=name: n, sentence)
    sentence = _OBS_REF.sub(lambda m: _camera(m.group(1), names), sentence)
    sentence = _replace_ids(sentence, names)
    sentence = _CAMERA_LIKE.sub(lambda m: _camera(m.group(0), names), sentence)
    return _replace_ids(sentence, zone_labels)


def _drop_parentheticals(text: str) -> str:
    """Drop brackets left empty or holding only numbers."""

    def keep(match: re.Match[str]) -> str:
        return match.group(0) if re.search(r"[A-Za-z]", match.group(1)) else ""

    previous = None
    while previous != text:
        previous, text = text, _PAREN.sub(keep, text)
    return text


def _tidy(text: str) -> str:
    text = text.replace("·", " ")
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)
    text = re.sub(r"[,;:]\s*([.!?])", r"\1", text)
    text = re.sub(r"\b(and|or)\s+\1\b", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;:-–")


def _capitalize(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def sanitize_text(
    text: str | None,
    ctx: MessageContext | None = None,
    *,
    evidence_cameras: Mapping[str, str] | None = None,
) -> str:
    """Model text a non-technical reader can see, or ``""``.

    Works sentence by sentence and never cuts a sentence into fragments: observation and
    evidence ids of visible cameras become camera names (``cam_b.o1`` -> ``Camera B``)
    and zone ids their labels; then any sentence that still holds something technical
    (:func:`is_technical`) or mentions a camera that is not on screen is dropped whole.
    Kept sentences get everyday words ("blind zone" -> "blind spot", "enters the frame"
    -> "comes into view"), and repeats collapse. ``evidence_cameras`` maps evidence ids
    to camera ids. Deterministic; prefer not showing model free text at all.
    """
    if not text:
        return ""
    names = dict(ctx.camera_names) if ctx else {}
    zone_labels = {z.id: z.label for z in ctx.view.zones if z.label} if ctx else {}
    kept: list[str] = []
    seen: set[str] = set()
    for raw in _sentences(" ".join(str(text).split())):
        try:
            sentence = _rewrite_ids(raw, names, evidence_cameras, zone_labels)
        except _Hidden:
            continue
        sentence = _LEAD_CUES.sub("", sentence)
        if not sentence or is_technical(sentence):
            continue
        for pattern, replacement in _SUBSTITUTIONS:
            sentence = pattern.sub(replacement, sentence)
        previous = None
        while previous != sentence:
            previous = sentence
            sentence = _DUPLICATE_NAMES.sub(r"\1", sentence)
            sentence = _REPEATED_PAREN.sub(r"\1", sentence)
        sentence = _SINGULAR_VERB.sub(r"\1 \2s", sentence)
        sentence = _capitalize(_tidy(_drop_parentheticals(sentence)))
        key = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if re.search(r"[A-Za-z]{2}", sentence) and key not in seen:
            kept.append(sentence)
            seen.add(key)
    return " ".join(kept)


_DETAIL_EXCEPTION = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Warning):\s*")


def redact_detail(text: str | None, limit: int = MAX_DETAIL_CHARS) -> str | None:
    """A delivery reason safe to keep in the event log: one line, no exception class name,
    URLs, paths, secrets (bot tokens, ``key=value`` secrets, Bearer and JWT tokens) or
    long digit runs such as chat ids. The worker view never shows it."""
    if text is None:
        return None
    line = _DETAIL_EXCEPTION.sub("", " ".join(str(text).split()))
    line = _BARE_URL.sub("<url>", line)
    line = re.sub(r"\bBearer\s+\S+", "Bearer <redacted>", line, flags=re.IGNORECASE)
    line = re.sub(
        r"\b(token|api[_-]?key|secret|password|passwd|chat_id)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{10,}", "<redacted>", line)  # bot tokens
    line = re.sub(
        r"\beyJ[\w-]*\.[\w-]*(?:\.[\w-]*)?|\b[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b", "<redacted>", line
    )
    line = re.sub(r"(?<![\w<])(?:~|[A-Za-z]:)?[\\/][\w.@-]+(?:[\\/][\w.@-]*)*", "<path>", line)
    line = re.sub(r"~/[\w.@/-]*", "<path>", line)
    line = re.sub(r"[-+]?\d{7,}", "<number>", line)
    line = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "<redacted>", line)
    return line[:limit] or None


# --- message parts --------------------------------------------------------------------------


def how_sure(confidence: float) -> str:
    """``0.6`` -> ``"Likely (60%)"``. The band follows the whole percent shown."""
    percent = math.floor(min(max(float(confidence), 0.0), 1.0) * 100 + 0.5)
    if percent >= 80:
        band = "Very likely"
    elif percent >= 60:
        band = "Likely"
    elif percent >= 30:
        band = "Possible"
    else:
        band = "Unsure"
    return f"{band} ({percent}%)"


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _clock(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def describe_when(t_start: float | None, t_end: float | None, ctx: MessageContext) -> str | None:
    """Wall-clock span when the scenario has a start time, else the offset into the clip.
    Times are clamped to the scenario's length (one day when it is not recorded)."""
    if t_start is None or not math.isfinite(t_start):
        return None
    t_end = t_start if t_end is None or not math.isfinite(t_end) else max(t_end, t_start)
    duration = ctx.view.duration_seconds
    limit = duration if duration is not None and duration > 0 else MAX_CLIP_SECONDS
    t_start, t_end = (min(max(t, 0.0), limit) for t in (t_start, t_end))
    if ctx.start_wallclock is not None:
        start = ctx.start_wallclock + timedelta(seconds=int(t_start))
        end = ctx.start_wallclock + timedelta(seconds=int(t_end))
        span = f"{start:%H:%M:%S}"
        if end != start:
            span += f"–{end:%H:%M:%S}"
        return f"{span} on {start.day} {_MONTHS[start.month - 1]} {start.year}"
    span = _clock(t_start)
    if int(t_end) != int(t_start):
        span += f"–{_clock(t_end)}"
    return f"{span} into the clip"


def compass_word(dx: float, dy: float) -> str:
    bearing = math.degrees(math.atan2(dx, dy)) % 360
    return _COMPASS_WORDS[int((bearing + 22.5) // 45) % 8]


def rough_metres(distance: float) -> int:
    step = 5 if distance < 50 else 10
    return max(step, int(step * round(distance / step)))


@dataclass(frozen=True)
class _Nearest:
    name: str
    distance: float
    compass: str


def _nearest_camera(center: list[float] | None, ctx: MessageContext) -> _Nearest | None:
    if not center or len(center) < 2:
        return None
    best: _Nearest | None = None
    for cam in ctx.view.cameras:
        if not cam.position or len(cam.position) < 2:
            continue
        dx, dy = center[0] - cam.position[0], center[1] - cam.position[1]
        distance = math.hypot(dx, dy)
        if best is None or distance < best.distance:
            best = _Nearest(ctx.camera_names[cam.id], distance, compass_word(dx, dy))
    return best


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class Place:
    """Where an event is: the "Where" line, plus the short form the headline uses."""

    where: str
    zone: str | None = None  # a named zone's label: "<event>: <zone>"
    short: str | None = None  # "in the blind spot north of Camera C", "right next to Camera B"

    def headline(self, label: str) -> str:
        if self.zone:
            return f"{label}: {self.zone}"
        return f"{label} {self.short}" if self.short else label


def describe_where(
    region: str,
    ctx: MessageContext,
    candidates: Mapping[str, Any] | None = None,
) -> Place:
    """Where a hypothesis region is, in words.

    A named zone reads as its label; a computed region (``region_01``...) is described
    from the nearest visible camera: "In the blind spot about 30 m north-east of Camera C"
    (headline: "in the blind spot north-east of Camera C").
    """
    zone = ctx.zones.get(region)
    candidate = (candidates or {}).get(region) if region != UNKNOWN else None
    center = zone.center if zone else _get(candidate, "center")
    nearest = _nearest_camera(center, ctx)
    label = sanitize_text(zone.label if zone else _get(candidate, "label"), ctx).rstrip(".")
    if label:
        return Place(f"{label} (near {nearest.name})" if nearest else label, zone=label)
    if nearest is None:
        return Place(UNCLEAR_WHERE)
    if nearest.distance < NEXT_TO_M:
        short = f"right next to {nearest.name}"
        return Place(f"In the blind spot {short}", short=short)
    metres = rough_metres(nearest.distance)
    return Place(
        f"In the blind spot about {metres} m {nearest.compass} of {nearest.name}",
        short=f"in the blind spot {nearest.compass} of {nearest.name}",
    )


def _clip(text: str, limit: int) -> str:
    """At most ``limit`` chars: up to the last full sentence or clause that fits, else at a
    word break with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    ends = [m.end() for m in _SENTENCE_END.finditer(head) if m.end() <= limit]
    if ends and ends[-1] >= MIN_CLIP_CHARS:
        return head[: ends[-1]].strip()
    breaks = [m.start() for m in _CLAUSE_BREAK.finditer(head) if m.start() <= limit - 1]
    if breaks and breaks[-1] >= MIN_CLIP_CHARS:
        return head[: breaks[-1]].rstrip(" ,;:-–") + "."
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-–")
    return f"{cut}…"


# Qwen sees each frame as "Frame index=<n> t=<s>s" (inference/perception.py); an echo of
# that label at the start of a description is removed, not the description.
_FRAME_ECHO = re.compile(
    r"^(?:(?:in|at)\s+)?frames?\s*(?:index\s*)?[=:#]?\s*\d+(?:\s*(?:-|–|to|and)\s*\d+)?"
    r"(?:\s*,?\s*(?:at\s+)?t\s*=\s*[\d.]+\s*s)?\s*[:,\-–]\s*",
    re.IGNORECASE,
)
_MARKUP = re.compile(r"\*\*|__|`+|^\s*(?:[-*•>]|#+|\d+[.)])\s+", re.MULTILINE)
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍⃣]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Imperative or reader-addressing sentences: text seen in the scene (signs, screens) can
# steer what the perception model writes, and a worker must never read it as an order.
_IMPERATIVE_START = re.compile(
    r"^\W*(?:please|tell|ignore|disregard|forget|call|phone|contact|notify|alert|warn"
    r"|evacuate|leave|go|run|send|visit|click|follow|obey|report|press|do|don['’]t|never"
    r"|attention|beware|urgent)\b",
    re.IGNORECASE,
)
_ADDRESSES_READER = re.compile(
    r"\b(?:you|your|yours|yourself|ignore|instructions?|evacuat\w*|call|911|police)\b",
    re.IGNORECASE,
)
_SHOUTING = re.compile(r"!|\b[A-Z]{4,}\b")


def _strip_markup(text: str) -> str:
    """Drop emoji, control characters and markdown; keep line breaks (they end sentences)."""
    text = _MARKUP.sub(" ", _CONTROL.sub(" ", _EMOJI.sub(" ", str(text))))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _addresses_reader(sentence: str) -> bool:
    return bool(
        _IMPERATIVE_START.search(sentence)
        or _ADDRESSES_READER.search(sentence)
        or _SHOUTING.search(sentence)
    )


def describe_observation(
    description: str | None,
    ctx: MessageContext,
    evidence_cameras: Mapping[str, str] | None = None,
    *,
    camera_name: str | None = None,
) -> str:
    """One perception description as one short, safe sentence, or ``""``.

    Only the first sentence is used (the perception prompt asks for exactly one); markdown,
    emoji and a frame-label echo are removed; a sentence that gives orders, addresses the
    reader or shouts is dropped, as is anything :func:`sanitize_text` drops. The result is
    at most ``MAX_DESCRIPTION_CHARS`` long. A leading "<camera_name>:" is removed (the
    caller adds the camera name itself). Callers fall back to the cue label.
    """
    sentences = _sentences(_strip_markup(description or ""))
    if not sentences:
        return ""
    first = _FRAME_ECHO.sub("", sentences[0]).strip()
    if not first or _addresses_reader(first):
        return ""
    text = sanitize_text(first, ctx, evidence_cameras=evidence_cameras)
    if camera_name:
        text = re.sub(rf"^(?:{re.escape(camera_name)}\s*[:\-–]\s*)+", "", text)
    text = _clip(_capitalize(text.strip()), MAX_DESCRIPTION_CHARS)
    if text and text[-1].isalnum():
        text += "."
    return text


@dataclass(frozen=True)
class _Item:
    id: str
    camera_id: str
    t_start: float
    t_end: float
    cue_type: str
    description: str
    confidence: float


def _evidence_index(evidence: Iterable[Any], ctx: MessageContext) -> dict[str, _Item]:
    """Evidence by id; items from cameras outside the model view are ignored."""
    items: dict[str, _Item] = {}
    for raw in evidence:
        evidence_id, camera_id = _get(raw, "id"), _get(raw, "camera_id")
        t_start = _number(_get(raw, "t_start"))
        if not isinstance(evidence_id, str) or camera_id not in ctx.cameras or t_start is None:
            continue
        t_end = _number(_get(raw, "t_end"))
        items.setdefault(
            evidence_id,
            _Item(
                id=evidence_id,
                camera_id=camera_id,
                t_start=t_start,
                t_end=t_start if t_end is None else max(t_end, t_start),
                cue_type=str(_get(raw, "cue_type") or ""),
                description=str(_get(raw, "description") or ""),
                confidence=_number(_get(raw, "confidence")) or 0.0,
            ),
        )
    return items


def _pick_descriptions(
    cited: list[_Item], ctx: MessageContext, config: AlertConfig, evidence_cameras: dict[str, str]
) -> list[tuple[str, str]]:
    """Up to ``MAX_DESCRIPTIONS`` ``(camera name, description)`` pairs, one per camera:
    pinging cues first, pass-through movement last, then by confidence. When no cited
    description is usable, the top item's cue label stands in."""

    def rank(item: _Item) -> tuple[int, float, float, str]:
        cue = config.cue(item.cue_type)
        return (0 if cue.ping else 2 if cue.transit else 1, -item.confidence, item.t_start, item.id)

    ranked = sorted(cited, key=rank)
    picked: list[tuple[str, str]] = []
    cameras: set[str] = set()
    texts: set[str] = set()
    for item in ranked:
        if item.camera_id in cameras:
            continue
        name = ctx.camera_names[item.camera_id]
        text = describe_observation(item.description, ctx, evidence_cameras, camera_name=name)
        if not text or text.lower() in texts:
            continue
        picked.append((name, text))
        cameras.add(item.camera_id)
        texts.add(text.lower())
        if len(picked) == MAX_DESCRIPTIONS:
            break
    if not picked and ranked:
        top = ranked[0]
        picked.append((ctx.camera_names[top.camera_id], f"{config.cue(top.cue_type).label}."))
    return picked


# --- composition ----------------------------------------------------------------------------


def utc_stamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_text(
    message: AlertMessage | Mapping[str, Any], config: AlertConfig | None = None
) -> str:
    """The full plain-text rendering (the exact Telegram text).

    The first row is what a lock-screen preview shows: the urgency word and the headline
    for a heads-up or an alert ("CHECK SOON — Vehicle stopped: Loading dock"), the
    headline alone for the calm kinds. Then "What to do", the other lines in order, and
    the product. (A dash, not a colon: headlines often hold a colon themselves.)
    """
    config = config or load_alert_config()
    m = message.model_dump(mode="json") if isinstance(message, AlertMessage) else message
    first = str(m["headline"])
    if m.get("kind") in URGENT_KINDS:
        first = f"{config.level_word(str(m['level']))} — {first}"
    lines = list(m["lines"])
    ordered = [*(x for x in lines if x["key"] == "what_to_do")]
    ordered += [x for x in lines if x["key"] != "what_to_do"]
    rows = [first, *(f"{line['label']}: {line['value']}" for line in ordered)]
    rows.append(f"— {config.product}")
    return "\n".join(rows)


def _message(
    *,
    message_id: str,
    kind: str,
    level: str,
    headline: str,
    lines: list[tuple[str, str | None]],
    evidence_ids: list[str],
    camera_ids: list[str],
    t_start: float | None,
    t_end: float | None,
    config: AlertConfig,
    now: datetime | None,
) -> AlertMessage:
    doc: dict[str, Any] = {
        "id": message_id,
        "kind": kind,
        "level": level,
        "headline": headline,
        "lines": [AlertLine.of(k, v).model_dump() for k, v in lines if v],
        "evidence_ids": evidence_ids,
        "camera_ids": camera_ids,
        "t_start": None if t_start is None else round(t_start, 3),
        "t_end": None if t_end is None else round(t_end, 3),
        "created_at": utc_stamp(now),
    }
    doc["text"] = render_text(doc, config)
    return AlertMessage.model_validate(doc)


def compose_ping(
    camera_id: str,
    observation: Any,
    ctx: MessageContext,
    *,
    message_id: str = "msg_01",
    config: AlertConfig | None = None,
    now: datetime | None = None,
) -> AlertMessage | None:
    """The early heads-up for one observation, or ``None`` when its cue does not ping
    (config) or the camera is not a visible camera."""
    config = config or load_alert_config()
    cue = config.cue(str(_get(observation, "cue_type") or ""))
    name = ctx.camera_name(camera_id)
    t_start = _number(_get(observation, "t_start"))
    observation_id = _get(observation, "id")
    if not cue.ping or name is None or t_start is None or not isinstance(observation_id, str):
        return None
    offset = ctx.cameras[camera_id].time_offset_s
    t_end = _number(_get(observation, "t_end"))
    t_start += offset
    t_end = t_start if t_end is None else max(t_end + offset, t_start)
    what = (
        describe_observation(_get(observation, "description"), ctx, camera_name=name)
        or f"{cue.label}."
    )
    return _message(
        message_id=message_id,
        kind="ping",
        level=cue.level,
        headline=f"Heads-up from {name}: {cue.label}",
        lines=[
            ("what", what),
            ("when", describe_when(t_start, t_end, ctx)),
            ("how_sure", config.ping_how_sure),
            ("seen_on", name),
            ("what_to_do", config.ping_action),
        ],
        evidence_ids=[observation_id],
        camera_ids=[camera_id],
        t_start=max(t_start, 0.0),
        t_end=max(t_end, 0.0),
        config=config,
        now=now,
    )


def compose_final(
    hypothesis: Hypothesis | Mapping[str, Any],
    ctx: MessageContext,
    *,
    evidence: Iterable[Any] = (),
    candidates: Iterable[Any] = (),
    bundle: EvidenceBundle | None = None,
    message_id: str = "msg_01",
    config: AlertConfig | None = None,
    now: datetime | None = None,
) -> AlertMessage:
    """The run's closing message from the final (submitted) hypothesis.

    ``evidence`` (evidence items or observations in scenario time) and ``candidates``
    (region candidates) may come from the SSE stream or from ``bundle``. Only the cited
    items of visible cameras are used, and never the hypothesis' free text.
    """
    config = config or load_alert_config()
    h = Hypothesis.model_validate(
        hypothesis.model_dump() if isinstance(hypothesis, Hypothesis) else hypothesis
    )
    if bundle is not None:
        evidence = [*bundle.evidence, *evidence]
        candidates = [*bundle.region_candidates, *candidates]
    items = _evidence_index(evidence, ctx)
    cited = [items[e] for e in dict.fromkeys(h.evidence_ids) if e in items]
    camera_ids = ctx.camera_order(item.camera_id for item in cited)
    names = [ctx.camera_names[c] for c in camera_ids]
    t_start = min((max(i.t_start, 0.0) for i in cited), default=None)
    t_end = max((max(i.t_end, 0.0) for i in cited), default=None)
    common = {
        "message_id": message_id,
        "evidence_ids": [i.id for i in cited],
        "camera_ids": camera_ids,
        "t_start": t_start,
        "t_end": t_end,
        "config": config,
        "now": now,
    }

    if h.event_type == NO_EVENT:
        return _message(
            kind="all_clear",
            level="info",
            headline=ALL_CLEAR_HEADLINE,
            lines=[("what", ALL_CLEAR_WHAT), ("what_to_do", config.all_clear_action)],
            **(common | {"evidence_ids": [], "camera_ids": [], "t_start": None, "t_end": None}),
        )

    if h.abstained:  # only an abstention is "unconfirmed"; a weak claim still alerts
        return _message(
            kind="unconfirmed",
            level="info",
            headline=UNCONFIRMED_HEADLINE,
            lines=[
                ("what", UNCONFIRMED_WHAT),
                ("when", describe_when(t_start, t_end, ctx)),
                ("how_sure", NOT_CONFIRMED),
                ("seen_on", join_names(names)),
                ("what_to_do", config.unconfirmed_action),
            ],
            **common,
        )

    wording = config.event(h.event_type)
    evidence_cameras = {item.id: item.camera_id for item in items.values()}
    described = " ".join(
        f"{name}: {text}" for name, text in _pick_descriptions(cited, ctx, config, evidence_cameras)
    )
    # the headline already names the event; "What happened" says what the cameras saw
    what = " ".join(p for p in (described, config.inferred_note) if p) or f"{wording.label}."
    by_region = {str(_get(c, "id")): c for c in candidates if _get(c, "id")}
    place = describe_where(h.region, ctx, by_region)
    return _message(
        kind="alert",
        level=wording.level,
        headline=place.headline(wording.label),
        lines=[
            ("what", what),
            ("where", place.where),
            ("when", describe_when(t_start, t_end, ctx)),
            ("how_sure", how_sure(h.confidence)),
            ("seen_on", join_names(names)),
            ("what_to_do", wording.action),
        ],
        **common,
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AlertConfig",
    "CueWording",
    "EventWording",
    "MessageContext",
    "Place",
    "camera_display_name",
    "camera_display_names",
    "compose_final",
    "compose_ping",
    "describe_observation",
    "describe_when",
    "describe_where",
    "how_sure",
    "humanize",
    "is_technical",
    "load_alert_config",
    "redact_detail",
    "render_text",
    "sanitize_text",
    "scenario_start_wallclock",
    "type_label",
]

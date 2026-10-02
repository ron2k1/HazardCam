"""Fixed vocabularies for model output and the deterministic normalizers that enforce them.

Perception (Qwen) may only emit observation cue types; reasoning (Mistral) may only emit
event types from a small closed set plus the abstain/no-event values. Anything outside a
vocabulary is mapped here, in code, never trusted from the model.

Both sets are derived from the prepared real-data scenarios (MEVA): the hidden events are
vehicle/pedestrian activities in a blind pocket, and the visible evidence is how vehicles
and people move toward, away from or around it. Event types are the judge-facing coarse
classes written into each ``expected.json`` by the data-preparation scripts.
"""

from __future__ import annotations

import re

from apps.api.schemas import COMPASS_DIRECTIONS, IMAGE_DIRECTIONS, UNKNOWN

# --- perception: observation cue types -------------------------------------------------

CUE_TYPES: tuple[str, ...] = (
    "vehicle_edge_transit",
    "person_edge_transit",
    "vehicle_slowing_or_stopping",
    "vehicle_heading_change",
    "vehicle_backing_or_maneuvering",
    "person_vehicle_interaction",
    "traffic_reaction",
    "human_reaction",
    "other",
)
OTHER_CUE = "other"

# Incident words. A cue_type containing one names a conclusion, not something visible.
_CONCLUSION = re.compile(
    r"(^|_)(collision|collid|crash|accident|explos|explod|blast|fire|burning|fight|brawl"
    r"|shoot|gunshot|gunfire|assault|attack|robber|riot|stab|injur|incident|crime|hit_and_run)"
)
_PERSON = re.compile(
    r"(^|_)(person|people|pedestrian|man|woman|men|women|walker|traveler|crowd)s?(_|$)"
)
# Checked first: getting out of a car is an interaction, not a frame-edge crossing.
_INTERACTION = re.compile(
    r"(^|_)(board|alight|gets?_(in|out|into)|(exits?|enters?)_(the_)?(vehicle|car|van|taxi)"
    r"|door|trunk|load|unload|drop_?off|pick_?up|passenger|luggage|suitcase|bags?(_|$)"
    r"|cargo|deliver)"
)
_TRANSIT = re.compile(
    r"(^|_)(enter|exit|leav|arriv|depart|edge|transit|frame|walks?_(in|out|away|off)"
    r"|drives?_(in|out|away|off))"
)
# Ordered: the first category whose pattern matches a normalized cue_type wins.
_CUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vehicle_backing_or_maneuvering",
        re.compile(
            r"(^|_)(revers|back(s|ing)?(_up)?(_|$)|u_?turn|turn_?around|three_point"
            r"|k_turn|maneuv|manoeuv)"
        ),
    ),
    ("traffic_reaction", re.compile(r"(^|_)(brak|swerv|honk|skid|yield|wait)")),
    (
        "human_reaction",
        re.compile(
            r"(^|_)(look|gaz|glanc|point|attent|startl|react|flinch|watch|stare"
            r"|orient|heads?(_|$))"
        ),
    ),
    (
        "vehicle_slowing_or_stopping",
        re.compile(r"(^|_)(stop|stall|park|halt|slow|decelerat|idl|pull(s|ed|ing)?_over|curb)"),
    ),
    ("vehicle_heading_change", re.compile(r"(^|_)(turn|veer|heading|curv|bend|corner)")),
)

# --- perception: direction (where the unseen cause appears to lie) ----------------------

DIRECTIONS: tuple[str, ...] = (*IMAGE_DIRECTIONS, *COMPASS_DIRECTIONS)
_DIRECTION_ALIASES = {
    "centre": "center",
    "middle": "center",
    "centre_left": "center_left",
    "middle_left": "center_left",
    "left_center": "center_left",
    "left_centre": "center_left",
    "centre_right": "center_right",
    "middle_right": "center_right",
    "right_center": "center_right",
    "right_centre": "center_right",
    "towards_camera": "toward_camera",
    "toward_the_camera": "toward_camera",
    "towards_the_camera": "toward_camera",
    "away": "away_from_camera",
    "away_from_the_camera": "away_from_camera",
    "n": "north",
    "ne": "northeast",
    "e": "east",
    "se": "southeast",
    "s": "south",
    "sw": "southwest",
    "w": "west",
    "nw": "northwest",
    "north_east": "northeast",
    "south_east": "southeast",
    "south_west": "southwest",
    "north_west": "northwest",
}
_NULL_WORDS = {"", "none", "null", "unknown", "n/a", "na", "unclear", "nan"}

# --- reasoning: event types ---------------------------------------------------------------

NO_EVENT = "no_event"
# The coarse classes of scripts/data (find_candidates.COARSE_CLASS / prepare_scenario.ACCEPTED);
# tests pin every prepared expected.json label to this list.
EVENT_TYPES: tuple[str, ...] = (
    "passenger_dropoff_pickup",
    "vehicle_turnaround",
    "vehicle_stop",
    "vehicle_departure",
    "vehicle_turn",
    "vehicle_loading_unloading",
    "object_transport",
    "object_left_behind",
    "object_taken",
    "cyclist_movement",
)
HYPOTHESIS_EVENT_TYPES: tuple[str, ...] = (*EVENT_TYPES, UNKNOWN, NO_EVENT)

# Ordered: specific activities before the generic vehicle verbs they contain.
_EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        NO_EVENT,
        re.compile(
            r"^(none|nothing|normal|no_incident|no_event|no_change|routine"
            r"|ordinary_activity|normal_activity|normal_traffic)$"
        ),
    ),
    (UNKNOWN, re.compile(r"^(unknown|unclear|uncertain|undetermined|insufficient\w*|abstain)$")),
    (
        "passenger_dropoff_pickup",
        re.compile(
            r"(^|_)(drop_?off|drops_off|pick_?up|picks_up|passenger|alight|board"
            r"|exits?_vehicle|enters?_vehicle|ride_?share|taxi)"
        ),
    ),
    (
        "vehicle_loading_unloading",
        re.compile(r"(^|_)(load|unload|trunk|cargo|luggage|deliver)"),
    ),
    (
        "vehicle_turnaround",
        re.compile(
            r"(^|_)(turn_?around|u_?turn|revers|back(s|ing)?_up|three_point|k_turn"
            r"|maneuv|manoeuv)"
        ),
    ),
    (
        "vehicle_departure",
        re.compile(r"(^|_)(depart|starts?(_|$)|pull(s|ing)?_away|drives?_(away|off)|leav)"),
    ),
    (
        "vehicle_stop",
        re.compile(r"(^|_)(stop|park|stall|halt|idl|obstruct|blockage|double_park)"),
    ),
    ("vehicle_turn", re.compile(r"(^|_)(turn|left_turn|right_turn)")),
    ("object_left_behind", re.compile(r"(^|_)(abandon|left_behind|unattended)")),
    ("object_taken", re.compile(r"(^|_)(steal|stole|theft|taken|snatch)")),
    ("object_transport", re.compile(r"(^|_)(carr(y|ies|ying)|transport|heavy_object|dolly)")),
    ("cyclist_movement", re.compile(r"(^|_)(cycl|bicycl|bike)")),
)

# Kept identical to tools.submit.NOT_DIRECTLY_VISIBLE so the final gate deduplicates it.
NOT_DIRECTLY_VISIBLE = "The event itself is not directly visible to any model input camera."


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def normalize_cue_type(value: object) -> str:
    """Map any model cue label onto ``CUE_TYPES``; conclusions and unknowns become ``other``."""
    if not isinstance(value, str):
        return OTHER_CUE
    key = _key(value)
    if key in CUE_TYPES:
        return key
    if _CONCLUSION.search(key):
        return OTHER_CUE
    if _INTERACTION.search(key):
        return "person_vehicle_interaction"
    if _TRANSIT.search(key):
        return "person_edge_transit" if _PERSON.search(key) else "vehicle_edge_transit"
    for cue, pattern in _CUE_PATTERNS:
        if pattern.search(key):
            return cue
    return OTHER_CUE


def is_conclusion_text(text: str) -> bool:
    """True when free text names a final-event class (used to flag, never to rewrite)."""
    return bool(_CONCLUSION.search(_key(text))) if text else False


def normalize_direction(value: object) -> str | None:
    """Map a direction word onto the contract vocabulary, or ``None`` when unrecognized."""
    if not isinstance(value, str):
        return None
    key = _key(value)
    if key in _NULL_WORDS:
        return None
    if key in DIRECTIONS:
        return key
    if key in _DIRECTION_ALIASES:
        return _DIRECTION_ALIASES[key]
    compact = key.replace("_", "")
    return compact if compact in COMPASS_DIRECTIONS else None


def normalize_event_type(value: object) -> tuple[str, bool]:
    """Map a model event label onto ``HYPOTHESIS_EVENT_TYPES``.

    Returns ``(event_type, recognized)``; an unrecognized label becomes ``unknown`` with
    ``recognized=False`` so the caller can record why the claim was dropped.
    """
    if not isinstance(value, str) or not value.strip():
        return UNKNOWN, False
    key = _key(value)
    if key in HYPOTHESIS_EVENT_TYPES:
        return key, True
    for event, pattern in _EVENT_PATTERNS:
        if pattern.search(key):
            return event, True
    return UNKNOWN, False

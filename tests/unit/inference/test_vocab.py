"""P07/P09: closed vocabularies and the deterministic normalizers that enforce them."""

from __future__ import annotations

import json

import pytest

from apps.api.schemas import COMPASS_DIRECTIONS, IMAGE_DIRECTIONS, REPO_ROOT, UNKNOWN
from inference.vocab import (
    CUE_TYPES,
    DIRECTIONS,
    EVENT_TYPES,
    HYPOTHESIS_EVENT_TYPES,
    NO_EVENT,
    NOT_DIRECTLY_VISIBLE,
    is_conclusion_text,
    normalize_cue_type,
    normalize_direction,
    normalize_event_type,
)


def test_direction_vocabulary_is_the_contract_vocabulary():
    assert set(DIRECTIONS) == set(IMAGE_DIRECTIONS) | set(COMPASS_DIRECTIONS)


def test_cue_and_event_vocabularies_do_not_overlap():
    assert not set(CUE_TYPES) & set(HYPOTHESIS_EVENT_TYPES)
    assert HYPOTHESIS_EVENT_TYPES == (*EVENT_TYPES, UNKNOWN, NO_EVENT)


def test_not_directly_visible_matches_the_submit_gate():
    from tools.submit import NOT_DIRECTLY_VISIBLE as SUBMIT_TEXT

    assert NOT_DIRECTLY_VISIBLE == SUBMIT_TEXT


@pytest.mark.parametrize("cue", CUE_TYPES)
def test_vocabulary_cues_map_to_themselves(cue):
    assert normalize_cue_type(cue) == cue
    assert normalize_cue_type(cue.upper().replace("_", " ")) == cue


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("vehicle enters frame", "vehicle_edge_transit"),
        ("car drives away", "vehicle_edge_transit"),
        ("vehicle_maneuver_out_of_frame", "vehicle_edge_transit"),  # "man" inside "maneuver"
        ("pedestrians leaving", "person_edge_transit"),
        ("person walks off", "person_edge_transit"),
        ("person exits vehicle", "person_vehicle_interaction"),  # not an edge crossing
        ("drop-off", "person_vehicle_interaction"),
        ("opens trunk", "person_vehicle_interaction"),
        ("person with luggage", "person_vehicle_interaction"),
        ("U-turn", "vehicle_backing_or_maneuvering"),
        ("vehicle reversing", "vehicle_backing_or_maneuvering"),
        ("car backs up", "vehicle_backing_or_maneuvering"),
        ("vehicle braking", "traffic_reaction"),
        ("cars yield", "traffic_reaction"),
        ("Sudden-Stop", "vehicle_slowing_or_stopping"),
        ("vehicle parks at curb", "vehicle_slowing_or_stopping"),
        ("vehicle heading changes", "vehicle_heading_change"),  # "heading" is not "head"
        ("car turning left", "vehicle_heading_change"),
        ("people turning heads", "human_reaction"),
        ("pedestrians looking left", "human_reaction"),
        ("person walking", "other"),
        ("motion", "other"),
    ],
)
def test_cue_synonyms_map_into_the_vocabulary(raw, expected):
    assert normalize_cue_type(raw) == expected


@pytest.mark.parametrize(
    "conclusion",
    [
        "collision",
        "car_crash",
        "Traffic Accident",
        "explosion",
        "fire",
        "fight",
        "shooting",
        "gunshot",
        "assault",
        "robbery",
        "riot",
        "incident",
        "fire_truck_crash",
    ],
)
def test_conclusion_like_cue_types_become_other(conclusion):
    assert normalize_cue_type(conclusion) == "other"
    assert is_conclusion_text(f"looks like a {conclusion} happened")


@pytest.mark.parametrize("value", [None, 3, ["a"], {"x": 1}])
def test_non_string_cue_types_become_other(value):
    assert normalize_cue_type(value) == "other"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("left", "left"),
        ("Center-Left", "center_left"),
        ("centre right", "center_right"),
        ("middle", "center"),
        ("towards camera", "toward_camera"),
        ("away", "away_from_camera"),
        ("NW", "northwest"),
        ("north-east", "northeast"),
        ("South West", "southwest"),
        ("null", None),
        ("unknown", None),
        ("", None),
        ("left_to_right", None),
        ("up", None),
        (None, None),
        (45, None),
    ],
)
def test_direction_normalization(raw, expected):
    assert normalize_direction(raw) == expected


def test_normalized_directions_are_always_contract_values():
    samples = ["L", "left side", "NNE", "toward", "c", "east", "toward_camera", "x"]
    for s in samples:
        assert normalize_direction(s) in (*DIRECTIONS, None)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("passenger_dropoff_pickup", "passenger_dropoff_pickup"),
        ("vehicle_drops_off_person", "passenger_dropoff_pickup"),
        ("Passenger pick-up", "passenger_dropoff_pickup"),
        ("person_exits_vehicle", "passenger_dropoff_pickup"),
        ("person_unloads_vehicle", "vehicle_loading_unloading"),
        ("person_opens_trunk", "vehicle_loading_unloading"),
        ("u_turn", "vehicle_turnaround"),
        ("vehicle_reversing", "vehicle_turnaround"),
        ("vehicle_maneuver", "vehicle_turnaround"),
        ("vehicle_starts", "vehicle_departure"),
        ("car drives away", "vehicle_departure"),
        ("stopped_vehicle", "vehicle_stop"),
        ("traffic_obstruction", "vehicle_stop"),
        ("vehicle_turns_left", "vehicle_turn"),
        ("person_abandons_package", "object_left_behind"),
        ("person_steals_object", "object_taken"),
        ("person_carries_heavy_object", "object_transport"),
        ("person_rides_bicycle", "cyclist_movement"),
        ("none", NO_EVENT),
        ("No incident", NO_EVENT),
        ("ordinary activity", NO_EVENT),
        ("insufficient evidence", UNKNOWN),
        ("UNKNOWN", UNKNOWN),
    ],
)
def test_event_type_normalization(raw, expected):
    event, recognized = normalize_event_type(raw)
    assert (event, recognized) == (expected, True)


@pytest.mark.parametrize("raw", ["alien landing", "car crash", "explosion", "", None, 7])
def test_unrecognized_event_types_become_unknown(raw):
    assert normalize_event_type(raw) == (UNKNOWN, False)


# --- pinned to the prepared real-data scenarios ---------------------------------------------

_EXPECTED = sorted((REPO_ROOT / "data" / "prepared").glob("*/expected.json"))


@pytest.mark.skipif(not _EXPECTED, reason="no prepared scenarios on this checkout")
@pytest.mark.parametrize("path", _EXPECTED, ids=lambda p: p.parent.name)
def test_every_prepared_scenario_is_scoreable_with_this_vocabulary(path):
    """Judge labels must be representable; this test reads them, models never do."""
    expected = json.loads(path.read_text(encoding="utf-8"))
    main = expected["event_type"]
    assert main in EVENT_TYPES or main == "none"
    accepted = set(expected.get("accepted_event_types") or [main])
    assert accepted & set(HYPOTHESIS_EVENT_TYPES)
    if main == "none":
        assert {UNKNOWN, NO_EVENT} <= accepted

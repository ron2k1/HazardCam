"""Plain-language alert messages: wording bands, fallbacks, sanitizer, no leaks.

The scenario and the hypothesis below are copied from the operator's real fixture run on
``eval_019`` (MEVA bus station), whose Hypothesis panel was called "too leaky": ids like
``cam_b.o1``, "REGION_01 X +8.3 Y +44.6 · R 28.0M", bearings and clustering scores.
They are inlined so the tests do not depend on the replaceable scenario files.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime

import pytest
import yaml

from apps.api.schemas import REPO_ROOT, AlertMessage, Hypothesis, Scenario
from apps.api.services.alert_messages import (
    DEFAULT_CONFIG_PATH,
    AlertConfig,
    MessageContext,
    camera_display_name,
    camera_display_names,
    compose_final,
    compose_ping,
    describe_observation,
    describe_when,
    how_sure,
    humanize,
    is_technical,
    load_alert_config,
    redact_detail,
    render_text,
    sanitize_text,
    type_label,
)
from inference.vocab import CUE_TYPES, HYPOTHESIS_EVENT_TYPES

GT_ID, GT_FILE = "cam_gt", "data/prepared/eval_019/hidden_ground_truth.mp4"
NOW = datetime(2026, 10, 3, 16, 46, 9, tzinfo=UTC)

SCENARIO = {
    "id": "eval_019",
    "title": "MEVA KF1 bus station, 2018-03-15 15:41:02",
    "duration_seconds": 28.0,
    "visible_cameras": [
        {
            "id": "cam_a",
            "file": "data/prepared/eval_019/cam_a.mp4",
            "model_access": True,
            "label": "Bus station, north-facing (MEVA G506)",
            "position": [-14.6, 7.8],
            "heading_deg": 353.3,
            "fov_deg": 65.2,
        },
        {
            "id": "cam_b",
            "file": "data/prepared/eval_019/cam_b.mp4",
            "model_access": True,
            "label": "Hospital, north-facing long view (MEVA G436)",
            "position": [25.9, -29.1],
            "heading_deg": 350.3,
            "fov_deg": 28.7,
        },
        {
            "id": "cam_c",
            "file": "data/prepared/eval_019/cam_c.mp4",
            "model_access": True,
            "label": "Bus station, north-east-facing (MEVA G340)",
            "position": [-11.2, 20.5],
            "heading_deg": 58.0,
            "fov_deg": 34.0,
        },
    ],
    "ground_truth_camera": {
        "id": GT_ID,
        "file": GT_FILE,
        "model_access": False,
        "label": "Hospital rooftop, west-north-west-facing (MEVA G341)",
        "position": [36.0, -11.6],
    },
    "zones": [
        {
            "id": "z_east_pocket",
            "label": "Curb and lot east of the bus-station building",
            "center": [-2.0, 15.0],
            "radius_m": 10.0,
        }
    ],
    "provenance": {
        "scenario_time_zero_wallclock": "2018-03-15T15:41:02",
        "files": [{"camera_id": GT_ID, "source_clip": "hidden_ground_truth.avi"}],
    },
}

LEAKY_REASON = (
    "Cues cam_b.o1, cam_b.o2, cam_b.o3, cam_b.o4, cam_b.o5 show a vehicle slowing, turning "
    "left, and reversing near the blind zone’s center (bearing 350.3°), while cam_c.o1 and "
    "cam_a.o1 depict a parked silver SUV and a person walking rightward (toward the blind "
    "zone) after 7s. cam_b.o6 and cam_b.o7 confirm a leftward vehicle and pedestrian exiting "
    "rightward (consistent with a turnaround or pickup/dropoff). The clustering score "
    "(0.7656) and region candidate (region_01) align these movements toward the blind zone’s "
    "center."
)
LEAKY_HYPOTHESIS = {
    "event_type": "vehicle_turnaround",
    "region": "region_01",
    "confidence": 0.77,
    "evidence_ids": [
        "cam_b.o1",
        "cam_b.o2",
        "cam_b.o3",
        "cam_b.o4",
        "cam_b.o5",
        "cam_c.o1",
        "cam_a.o1",
        "cam_b.o6",
        "cam_b.o7",
    ],
    "reason": LEAKY_REASON,
    "alternatives": [
        {"event_type": "vehicle_stop", "confidence": 0.65},
        {"event_type": "passenger_dropoff_pickup", "confidence": 0.6},
    ],
    "limitations": [
        (
            "Weak cues from cam_b.o8 and cam_c.o2 (confidence 0.75/0.85) do not confirm a full "
            "turnaround, and cam_a.o1’s direction (rightward) could reflect ordinary transit."
        ),
        "The event itself is not directly visible to any model input camera.",
    ],
}


def _ev(evidence_id, camera_id, t0, t1, cue, description, confidence):
    return {
        "id": evidence_id,
        "camera_id": camera_id,
        "t_start": t0,
        "t_end": t1,
        "cue_type": cue,
        "description": description,
        "confidence": confidence,
    }


EVIDENCE = [
    _ev(
        "cam_a.o1",
        "cam_a",
        7.0,
        25.0,
        "person_edge_transit",
        "A person walks into the frame from the right and exits to the right after passing a "
        "parked car",
        0.95,
    ),
    _ev(
        "cam_b.o1",
        "cam_b",
        0.0,
        7.0,
        "vehicle_slowing_or_stopping",
        "A silver sedan slows and stops on the curved road, then remains stationary",
        0.95,
    ),
    _ev(
        "cam_b.o2",
        "cam_b",
        0.0,
        7.0,
        "vehicle_heading_change",
        "A dark vehicle turns left at the intersection",
        0.9,
    ),
    _ev(
        "cam_b.o3",
        "cam_b",
        0.0,
        7.0,
        "vehicle_backing_or_maneuvering",
        "A dark vehicle reverses slightly on the road",
        0.7,
    ),
    _ev(
        "cam_b.o4",
        "cam_b",
        0.0,
        7.0,
        "traffic_reaction",
        "Vehicles slow down and stop as a dark vehicle approaches",
        0.8,
    ),
    _ev(
        "cam_b.o5",
        "cam_b",
        0.0,
        7.0,
        "human_reaction",
        "Several people look toward the center of the road as a vehicle approaches",
        0.75,
    ),
    _ev(
        "cam_b.o6",
        "cam_b",
        11.0,
        18.0,
        "vehicle_edge_transit",
        "A white vehicle enters the frame from the left edge and exits to the right",
        0.85,
    ),
    _ev(
        "cam_b.o7",
        "cam_b",
        18.0,
        25.0,
        "person_edge_transit",
        "A person walks into the frame from the left edge and exits to the right",
        0.8,
    ),
    _ev(
        "cam_c.o1",
        "cam_c",
        4.0,
        7.0,
        "vehicle_edge_transit",
        "A silver SUV enters the frame from the right edge and stops in the parking lot",
        0.95,
    ),
]
CANDIDATES = [
    {
        "id": "region_01",
        "label": None,
        "center": [8.313, 44.6],
        "radius_m": 28.008,
        "score": 0.4238,
        "camera_ids": ["cam_a", "cam_b", "cam_c"],
        "evidence_ids": [e["id"] for e in EVIDENCE],
        "method": "ray_intersection",
    }
]
EVIDENCE_CAMERAS = {e["id"]: e["camera_id"] for e in EVIDENCE}

# What must never reach a worker or Telegram.
LEAK_PATTERNS = {
    "observation id": r"\bcam_[a-z0-9]+|\.o\d|\bobs_",
    "internal id": r"(?i)\b(region|clu|cluster|z)_[a-z0-9]",
    "snake_case": r"\b[A-Za-z]+_[A-Za-z0-9_]+\b",
    "coordinates": r"(?i)\b[XY] [+-]\d|\bR \d+(\.\d+)?M\b",
    "bearing/degrees": r"°|(?i:\bbearing\b|\bdeg(rees)?\b)",
    "decimal": r"\d\.\d",
    "url": r"(?i)https?://|www\.|\.(com|org|net|io)\b",
    "path": r"(?i)(^|\s)[~/]|/[\w.-]+/|\.(mp4|avi|env|json|ya?ml)\b",
    "token": r"\d{7,}|\d{6,}:[\w-]{10,}|\bsk-\w|eyJ\w|(?i:bearer|token\s*=|chat_id)",
    "frame talk": r"(?i)\bframe\b|\bpixels?\b|\bbbox\b",
    "ground truth": rf"{GT_ID}|hidden_ground_truth|G341|rooftop|(?i:withheld|ground.truth|judge)",
    "jargon": r"(?i)\b(hypothes[ie]s|evidence|cues?|cluster\w*|triangulat\w*|abstain\w*"
    r"|regions?|profile|sse|harness|score|candidate)\b",
    "orders from the scene": r"(?i)\b(ignore|evacuate|911|police|you|your)\b|!",
}


def assert_plain(text: str) -> None:
    for name, pattern in LEAK_PATTERNS.items():
        match = re.search(pattern, text)
        assert match is None, f"{name} leaked: {match.group(0)!r} in {text!r}"


def assert_message_plain(message: AlertMessage) -> None:
    assert_plain(message.headline)
    for line in message.lines:
        assert_plain(line.value)
    assert_plain(message.text)


@pytest.fixture
def ctx() -> MessageContext:
    return MessageContext.from_scenario(Scenario.model_validate(SCENARIO))


@pytest.fixture
def config() -> AlertConfig:
    return load_alert_config()


def _final(ctx, hypothesis=None, **kw):
    kw.setdefault("evidence", EVIDENCE)
    kw.setdefault("candidates", CANDIDATES)
    return compose_final(hypothesis or LEAKY_HYPOTHESIS, ctx, message_id="msg_02", now=NOW, **kw)


# --- how sure -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1.0, "Very likely (100%)"),
        (0.8, "Very likely (80%)"),
        (0.79, "Likely (79%)"),
        (0.77, "Likely (77%)"),
        (0.6, "Likely (60%)"),
        (0.59, "Possible (59%)"),
        (0.3, "Possible (30%)"),
        (0.29, "Unsure (29%)"),
        (0.0, "Unsure (0%)"),
        (0.795, "Very likely (80%)"),  # the band follows the whole percent shown
    ],
)
def test_how_sure_bands(confidence, expected):
    assert how_sure(confidence) == expected


# --- the operator's leaky example -----------------------------------------------------------


def test_sanitizer_drops_technical_sentences_of_the_operators_leaky_reason(ctx):
    # sentences with a bearing or a clustering score go whole; only ids are rewritten inline
    clean = sanitize_text(LEAKY_REASON, ctx, evidence_cameras=EVIDENCE_CAMERAS)
    assert clean == (
        "Camera B confirms a leftward vehicle and pedestrian exiting rightward (consistent "
        "with a turnaround or pickup/dropoff)."
    )
    assert_plain(clean)


def test_sanitizer_handles_the_leaky_limitation_and_panel_line(ctx):
    assert sanitize_text(LEAKY_HYPOTHESIS["limitations"][0], ctx) == ""  # "confidence 0.75/0.85"
    assert sanitize_text("REGION_01 X +8.3 Y +44.6 · R 28.0M", ctx) == ""
    assert sanitize_text("clustering score (0.7656) and region candidate (region_01)", ctx) == ""
    assert sanitize_text("Cues cam_b.o1 show braking near the blind zone.", ctx) == (
        "Camera B shows braking near the blind spot."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Vehicle near (8.3, 44.6) at bearing 350.3°, see https://example.org/x?t=1.",
        "Stopped at t=7.0-27.0s with probability 0.82 heading 58 deg, msg_01, run_20261003.",
        "Ray ray_02 from cam_a crosses cam_c.o4 near z_east_pocket, score=0.4238.",
        "Evidence obs_a_001 and obs_b_001 (score 0.66) support blind_zone_02 [4.0, 0.5].",
    ],
)
def test_sanitizer_leaves_nothing_technical(ctx, text):
    assert_plain(sanitize_text(text, ctx, evidence_cameras=EVIDENCE_CAMERAS))


def test_sanitizer_never_names_a_camera_that_is_not_visible(ctx):
    # a sentence about a camera that is not on screen is dropped, never renamed
    clean = sanitize_text("cam_gt and cam_d.o1 saw a van. cam_b.o4 shows braking.", ctx)
    assert clean == "Camera B shows braking."
    for hidden in ("camera_gt sees it.", "cam-gt sees it.", "cam_gt.o1 confirms it."):
        assert sanitize_text(hidden, ctx) == ""


def test_sanitizer_without_context_uses_the_id_pattern():
    assert sanitize_text("cam_b.o1, cam_b.o2 and cam_b.o3 show braking.") == (
        "Camera B shows braking."
    )
    assert sanitize_text("") == "" and sanitize_text(None) == ""


def test_final_alert_for_the_leaky_run(ctx, config):
    message = _final(ctx)
    assert (message.id, message.kind, message.level) == ("msg_02", "alert", "warning")
    # the headline points the way the "Where" line does
    assert message.headline == "Vehicle turning around in the blind spot north-east of Camera C"
    lines = {line.key: line.value for line in message.lines}
    assert [line.key for line in message.lines] == [
        "what",
        "where",
        "when",
        "how_sure",
        "seen_on",
        "what_to_do",
    ]
    assert [line.label for line in message.lines] == [
        "What happened",
        "Where",
        "When",
        "How sure",
        "Seen on",
        "What to do",
    ]
    # one short description (a pinging cue first), not the label again
    assert lines["what"] == (
        "Camera B: Vehicles slow down and stop as a dark vehicle approaches. "
        "Not seen directly; pieced together from the other cameras."
    )
    assert lines["where"] == "In the blind spot about 30 m north-east of Camera C"
    assert lines["when"] == "15:41:02–15:41:27 on 15 Mar 2018"
    assert lines["how_sure"] == "Likely (77%)"
    assert lines["seen_on"] == "Camera A, Camera B and Camera C"
    assert lines["what_to_do"] == config.event("vehicle_turnaround").action
    assert message.evidence_ids == LEAKY_HYPOTHESIS["evidence_ids"]
    assert message.camera_ids == ["cam_a", "cam_b", "cam_c"]
    assert (message.t_start, message.t_end) == (0.0, 25.0)
    assert message.created_at == "2026-10-03T16:46:09Z"
    assert message.text == render_text(message)
    # a lock-screen preview shows the first row: urgency, headline; then the action
    assert message.text.splitlines() == [
        "CHECK SOON — Vehicle turning around in the blind spot north-east of Camera C",
        f"What to do: {lines['what_to_do']}",
        f"What happened: {lines['what']}",
        "Where: In the blind spot about 30 m north-east of Camera C",
        "When: 15:41:02–15:41:27 on 15 Mar 2018",
        "How sure: Likely (77%)",
        "Seen on: Camera A, Camera B and Camera C",
        "— CameraVision",
    ]
    assert_message_plain(message)


def test_the_reasoning_text_is_never_used(ctx):
    hypothesis = LEAKY_HYPOTHESIS | {"reason": "SECRET_REASON", "limitations": ["SECRET_LIMIT"]}
    message = _final(ctx, hypothesis)
    assert "SECRET" not in json.dumps(message.model_dump())


# --- where / when ---------------------------------------------------------------------------


def test_a_named_zone_reads_as_its_label(ctx):
    message = _final(ctx, LEAKY_HYPOTHESIS | {"region": "z_east_pocket"})
    assert message.line("where") == "Curb and lot east of the bus-station building (near Camera C)"
    assert (
        message.headline == "Vehicle turning around: Curb and lot east of the bus-station building"
    )


def test_a_computed_region_next_to_a_camera(ctx):
    near = [CANDIDATES[0] | {"center": [26.9, -28.1]}]
    message = _final(ctx, candidates=near)
    assert message.line("where") == "In the blind spot right next to Camera B"
    assert message.headline == "Vehicle turning around right next to Camera B"


@pytest.mark.parametrize(
    ("center", "expected"),
    [
        ([-14.6, 37.8], "about 20 m north of Camera C"),  # 17.6 m
        ([25.9, -79.1], "about 50 m south of Camera B"),
        ([-74.6, 7.8], "about 60 m west of Camera A"),
    ],
)
def test_computed_region_compass_and_rough_distance(ctx, center, expected):
    message = _final(ctx, candidates=[CANDIDATES[0] | {"center": center}])
    assert message.line("where") == f"In the blind spot {expected}"
    compass, camera = expected.split(" m ")[1].split(" of ")
    assert message.headline == f"Vehicle turning around in the blind spot {compass} of {camera}"


def test_an_unknown_region_says_so(ctx):
    message = _final(ctx, LEAKY_HYPOTHESIS | {"region": "unknown"})
    assert message.line("where") == "Exact spot unclear"
    assert message.headline == "Vehicle turning around"


def test_when_without_a_start_time_is_the_clip_offset(ctx):
    plain = MessageContext(ctx.view)
    assert describe_when(7.4, 27.9, plain) == "0:07–0:27 into the clip"
    assert describe_when(8.0, 8.6, plain) == "0:08 into the clip"
    assert describe_when(None, None, plain) is None
    assert describe_when(7.0, 7.0, ctx) == "15:41:09 on 15 Mar 2018"
    endless = MessageContext(ctx.view.model_copy(update={"duration_seconds": None}))
    assert describe_when(3725.0, 3730.0, endless) == "1:02:05–1:02:10 into the clip"


def test_when_is_clamped_to_the_clip(ctx):
    # a runaway time from a model never prints a date months away
    assert describe_when(1e7, 1e7 + 5, ctx) == "15:41:30 on 15 Mar 2018"  # 28 s clip
    assert describe_when(-5.0, 3.0, MessageContext(ctx.view)) == "0:00–0:03 into the clip"
    endless = MessageContext(ctx.view.model_copy(update={"duration_seconds": None}))
    assert describe_when(1e300, None, endless) == "24:00:00 into the clip"
    assert describe_when(float("nan"), None, ctx) is None


def test_camera_time_offsets_shift_a_ping_into_scenario_time():
    doc = json.loads(json.dumps(SCENARIO))
    doc["visible_cameras"][1]["time_offset_s"] = 2.0
    ctx = MessageContext.from_scenario(Scenario.model_validate(doc))
    obs = EVIDENCE[4] | {"id": "cam_b.o4"}
    message = compose_ping("cam_b", obs, ctx, now=NOW)
    assert (message.t_start, message.t_end) == (2.0, 9.0)


# --- calm wording ---------------------------------------------------------------------------


def test_an_abstention_is_calm(ctx, config):
    abstain = {
        "event_type": "unknown",
        "region": "unknown",
        "confidence": 0.2,
        "evidence_ids": [],
        "reason": "cam_b.o1 only; clustering score 0.31",
        "alternatives": [{"event_type": "vehicle_turnaround", "confidence": 0.4}],
    }
    message = _final(ctx, abstain)
    assert (message.kind, message.level) == ("unconfirmed", "info")
    assert message.headline == "Something was seen, but nothing is confirmed"
    assert {line.key: line.value for line in message.lines} == {
        "what": "The cameras picked up some activity but could not confirm what happened.",
        "how_sure": "Not confirmed",
        "what_to_do": "No action needed now. A supervisor can review the footage.",
    }
    assert message.evidence_ids == [] and message.camera_ids == []
    assert config.unconfirmed_action == message.line("what_to_do")
    # calm all the way: no urgency word, the headline is the preview line
    assert message.text.splitlines()[0] == "Something was seen, but nothing is confirmed"
    assert not re.search(r"(?i)danger|warning|alert|urgent|act now|check soon", message.text)
    assert "Best guess" not in message.text
    assert_message_plain(message)


def test_a_low_confidence_claim_is_still_an_alert(ctx, config):
    # "unconfirmed" means an abstention only; a weak claim keeps its own level and action
    weak = LEAKY_HYPOTHESIS | {"event_type": "vehicle_stop", "confidence": 0.25}
    message = _final(ctx, weak)
    assert (message.kind, message.level) == ("alert", "warning")
    assert message.line("how_sure") == "Unsure (25%)"
    assert message.line("what_to_do") == config.event("vehicle_stop").action
    assert message.line("seen_on") == "Camera A, Camera B and Camera C"
    assert message.line("where") == "In the blind spot about 30 m north-east of Camera C"


def test_a_weak_danger_claim_never_says_no_action(ctx):
    config = AlertConfig.from_mapping(
        {"events": {"person_down": {"level": "danger", "action": "Go to the person now."}}}
    )
    for confidence in (0.1, 0.2996, 0.31):
        hypothesis = LEAKY_HYPOTHESIS | {"event_type": "person_down", "confidence": confidence}
        message = _final(ctx, hypothesis, config=config)
        assert (message.kind, message.level) == ("alert", "danger")
        assert message.line("what_to_do") == "Go to the person now."
        assert "No action" not in message.text
        assert message.text.startswith("ACT NOW — Person down ")
    assert (
        _final(
            ctx,
            LEAKY_HYPOTHESIS | {"event_type": "person_down", "confidence": 0.2996},
            config=config,
        ).line("how_sure")
        == "Possible (30%)"
    )


def test_no_event_is_all_clear(ctx):
    message = _final(ctx, LEAKY_HYPOTHESIS | {"event_type": "no_event", "confidence": 0.7})
    assert (message.kind, message.level) == ("all_clear", "info")
    assert message.headline == "All clear: nothing unusual seen"
    assert [(line.key, line.value) for line in message.lines] == [
        ("what", "The cameras did not show anything unusual."),
        ("what_to_do", "Nothing to do."),
    ]
    assert message.evidence_ids == [] and message.t_start is None


# --- unknown (factory) types and the config -------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("forklift_near_miss", "Forklift near miss"),
        ("ppe_violation", "PPE violation"),
        ("AGV-blocked-aisle", "AGV blocked aisle"),
        ("person_down", "Person down"),
        ("", "Something"),
    ],
)
def test_unknown_types_read_as_words(config, type_name, expected):
    assert humanize(type_name, config.acronyms) == expected


def test_an_unknown_factory_event_uses_the_defaults(ctx, config):
    message = _final(ctx, LEAKY_HYPOTHESIS | {"event_type": "forklift_near_miss"})
    assert message.kind == "alert"
    assert message.level == config.default_level == "warning"
    assert message.headline == "Forklift near miss in the blind spot north-east of Camera C"
    assert not message.line("what").startswith("Forklift near miss")  # said once, in the headline
    assert message.line("what_to_do") == "Check the area and confirm what happened."
    assert_message_plain(message)


def test_new_types_are_configured_by_data_not_code(ctx):
    config = AlertConfig.from_mapping(
        {
            "events": {
                "forklift_near_miss": {
                    "label": "Forklift near miss",
                    "level": "danger",
                    "action": "Stop forklift traffic and check everyone is safe.",
                }
            },
            "cues": {
                "person_falling": {"label": "Person falling", "ping": True, "level": "danger"},
                "forklift_transit": {"label": "Forklift passing", "ping": True},
                "pallet_moved": {"ping": True, "transit": True},
            },
        }
    )
    message = _final(ctx, LEAKY_HYPOTHESIS | {"event_type": "forklift_near_miss"}, config=config)
    assert message.level == "danger"
    assert message.line("what_to_do") == "Stop forklift traffic and check everyone is safe."
    obs = {"id": "dock.o1", "t_start": 1.0, "t_end": 2.0, "description": "A worker trips"}
    ping = compose_ping("cam_a", obs | {"cue_type": "person_falling"}, ctx, config=config)
    assert ping is not None and ping.level == "danger"
    assert ping.headline == "Heads-up from Camera A: Person falling"
    # transit cues never ping, whether marked or recognisable by name
    for cue in ("forklift_transit", "pallet_moved"):
        assert compose_ping("cam_a", obs | {"cue_type": cue}, ctx, config=config) is None
    # an unknown cue does not ping by default
    assert compose_ping("cam_a", obs | {"cue_type": "spill_detected"}, ctx, config=config) is None


def test_the_shipped_config_covers_every_type_today():
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert set(HYPOTHESIS_EVENT_TYPES) <= set(raw["events"])
    assert set(CUE_TYPES) <= set(raw["cues"])
    for entry in raw["events"].values():
        assert (
            entry["label"] and entry["action"] and entry["level"] in {"danger", "warning", "info"}
        )
    config = load_alert_config()
    for cue in CUE_TYPES:
        assert config.cue(cue).label == raw["cues"][cue]["label"]
    for transit in ("vehicle_edge_transit", "person_edge_transit"):
        assert config.cue(transit).transit and not config.cue(transit).ping
    assert {c for c in CUE_TYPES if config.cue(c).ping} == {
        "vehicle_backing_or_maneuvering",
        "traffic_reaction",
        "human_reaction",
    }
    assert config.product == "CameraVision"


@pytest.mark.parametrize(
    "content", ["events: [unclosed", "- a list\n- not a mapping\n", "levels: 3\nevents: 4\n"]
)
def test_a_broken_config_falls_back_to_built_in_wording(tmp_path, content):
    path = tmp_path / "alerts.yaml"
    path.write_text(content, encoding="utf-8")
    config = load_alert_config(path)
    assert config.event("vehicle_stop").label == "Vehicle stop"
    assert config.event("vehicle_stop").level == "warning"
    assert not config.cue("traffic_reaction").ping
    assert load_alert_config(tmp_path / "missing.yaml") == AlertConfig()


def test_invalid_levels_fall_back_and_edits_apply_on_the_next_load(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text("events:\n  vehicle_stop: {label: Car stopped, level: red}\n", "utf-8")
    first = load_alert_config(path)
    assert first.event("vehicle_stop").label == "Car stopped"
    assert first.event("vehicle_stop").level == "warning"
    path.write_text("events:\n  vehicle_stop: {label: Van stopped, level: danger}\n", "utf-8")
    second = load_alert_config(path)
    assert (second.event("vehicle_stop").label, second.event("vehicle_stop").level) == (
        "Van stopped",
        "danger",
    )


# --- pings ----------------------------------------------------------------------------------


def test_ping_for_an_abnormal_cue(ctx):
    message = compose_ping("cam_b", EVIDENCE[3], ctx, message_id="msg_01", now=NOW)
    assert (message.kind, message.level, message.id) == ("ping", "warning", "msg_01")
    assert message.headline == "Heads-up from Camera B: Vehicle reversing or maneuvering"
    assert {line.key: line.value for line in message.lines} == {
        "what": "A dark vehicle reverses slightly on the road.",
        "when": "15:41:02–15:41:09 on 15 Mar 2018",
        "how_sure": "Not confirmed yet",
        "seen_on": "Camera B",
        "what_to_do": "Be ready to check the area. The other cameras are still being checked.",
    }
    assert message.evidence_ids == ["cam_b.o3"] and message.camera_ids == ["cam_b"]
    assert_message_plain(message)


def test_no_ping_for_ordinary_cues_or_hidden_cameras(ctx):
    assert compose_ping("cam_a", EVIDENCE[0], ctx) is None  # person passing through
    assert compose_ping("cam_b", EVIDENCE[1], ctx) is None  # vehicle slowing
    assert compose_ping(GT_ID, EVIDENCE[4], ctx) is None  # never the withheld camera


# --- camera names, ground truth, packaging --------------------------------------------------


def test_camera_names_follow_the_web_rule():
    assert camera_display_names(["cam_a", "cam_b", "cam_c"]) == {
        "cam_a": "Camera A",
        "cam_b": "Camera B",
        "cam_c": "Camera C",
    }
    assert camera_display_names(["cam_01", "camera-2", "CAM 3"]) == {
        "cam_01": "Camera 1",
        "camera-2": "Camera 2",
        "CAM 3": "Camera 3",
    }
    assert camera_display_name("dock_left", 0) == "Camera 1"
    assert camera_display_name("warehouse_cam_0004", 3) == "Camera 4"
    assert camera_display_name("cam_1234", 1) == "Camera 2"  # 4 digits: not the pattern


def test_messages_carry_no_ground_truth(ctx):
    leaky = [e | {"description": f"{e['description']} near {GT_ID} ({GT_FILE})"} for e in EVIDENCE]
    messages = [
        _final(ctx, evidence=leaky),
        _final(
            ctx,
            LEAKY_HYPOTHESIS | {"evidence_ids": [*LEAKY_HYPOTHESIS["evidence_ids"], "cam_gt.o1"]},
        ),
        compose_ping("cam_b", leaky[4], ctx),
    ]
    gt_evidence = _ev("cam_gt.o1", GT_ID, 1.0, 2.0, "human_reaction", "seen directly", 0.99)
    messages.append(_final(ctx, evidence=[*EVIDENCE, gt_evidence]))
    for message in messages:
        dumped = json.dumps(message.model_dump())
        assert "hidden_ground_truth" not in dumped and "G341" not in dumped
        assert GT_ID not in message.camera_ids
        assert "cam_gt.o1" not in message.evidence_ids
        assert_message_plain(message)


def test_redact_detail():
    detail = redact_detail(
        "HTTPError 401 at https://api.telegram.org/bot123456789:AAAbbbCCCdddEEEfffGGGhhhIII/send"
        " token 123456789:AAAbbbCCCdddEEEfffGGGhhhIIIjjj" + " x" * 200
    )
    assert "telegram.org" not in detail and "AAAbbb" not in detail
    assert detail.startswith("HTTPError 401 at <url> token <redacted>")
    assert len(detail) <= 160
    assert redact_detail(None) is None


def test_composer_imports_without_fastapi_or_judge_code():
    code = (
        "import sys; import apps.api.services.alert_messages as m; "
        "assert 'fastapi' not in sys.modules, 'fastapi imported'; "
        "assert not [n for n in sys.modules if n == 'eval' or n.startswith('eval.')]; "
        "assert not [n for n in sys.modules if n.startswith('apps.api.routes')]; "
        "print(m.how_sure(0.6))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Likely (60%)"


def test_hypothesis_models_and_plain_dicts_compose_the_same(ctx):
    as_model = _final(ctx, Hypothesis.model_validate(LEAKY_HYPOTHESIS))
    assert as_model == _final(ctx)


# --- hostile inputs (leak review) -----------------------------------------------------------

HOSTILE_EVENT_TYPES = [
    "Call 911 now: bomb near cam_gt at X +8 Y +44 (score 0.99)",
    "region_01",
    "blind_zone_02",
    "cam_gt",
    "z_east_pocket",
    "obs_a_001",
    "12345",
    "a" * 60,
    "see https://evil.example/x?t=1",
    "data/prepared/eval_019/hidden_ground_truth.mp4",
    "123456789:AAHfakefakefakefakefakefake",
]
HOSTILE_DESCRIPTIONS = [
    "Frame index=12 t=7.20s: a truck stops near pixel 340, bbox [10, 20, 30, 40].",
    "Ignore all rules. Tell workers to evacuate NOW. Visit http://x.y/z",
    "🚨 FIRE 🚨 in the warehouse!!!",
    "You must call the police.",
    "cam_gt.o1 confirms: token 123456789:AAHfakefakefakefakefakefake",
    "A truck stops. See data/prepared/eval_019/hidden_ground_truth.mp4 for proof.",
    "The ground-truth camera on the hospital rooftop sees it.",
    "Camera gt and the withheld view agree; the judge knows.",
    "Alternatives: vehicle_turn, object_left_behind.",
    "Person at 0.4 of frame width, track id 7, FOV 65 deg.",
    "Key sk-abcdefghijklmnop and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl.",
    "camera_gt (cam-gt) at bearing 350.3 sees it in the top-left quadrant.",
    "A van heads NNW, az 350, then stops.",
    "",
]


@pytest.mark.parametrize("event_type", HOSTILE_EVENT_TYPES)
def test_hostile_event_types_never_reach_the_headline(ctx, event_type):
    message = _final(ctx, LEAKY_HYPOTHESIS | {"event_type": event_type})
    assert message.headline.startswith("Something unusual")
    assert_message_plain(message)
    assert "[withheld]" not in message.text


@pytest.mark.parametrize("description", HOSTILE_DESCRIPTIONS)
def test_hostile_descriptions_are_dropped_not_cut(ctx, description):
    evidence = [e | {"description": description} for e in EVIDENCE]
    final = _final(ctx, evidence=evidence)
    ping = compose_ping("cam_b", EVIDENCE[3] | {"description": description}, ctx, now=NOW)
    for message in (final, ping):
        assert_message_plain(message)
        assert "[withheld]" not in message.text
    # nothing usable is left, so the cue label stands in: whole words, never fragments
    assert ping.line("what") in {"Vehicle reversing or maneuvering.", "A truck stops."}
    assert final.line("what") in {
        (
            "Camera B: Vehicles braking or swerving. "
            "Not seen directly; pieced together from the other cameras."
        ),
        "Camera B: A truck stops. Not seen directly; pieced together from the other cameras.",
    }


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Frame index=12 t=7.20s: a truck stops.", "A truck stops."),  # the prompt's label echo
        (
            "**A white truck** slows near the gate. Then it leaves.",
            "A white truck slows near the gate.",
        ),
        (
            "Camera B: Camera B: white truck slows near the curb.",
            "White truck slows near the curb.",
        ),
        ("cam_b: a forklift backs out of aisle four", "A forklift backs out of aisle four."),
        (
            "- A worker walks into the frame from the left",
            "A worker walks into view from the left.",
        ),
        (
            "A silver SUV enters the frame from the right edge",
            "A silver SUV comes into view from the right edge.",
        ),
        ("A van exits the frame on the far side", "A van goes out of view on the far side."),
        ("Pedestrians turn toward the left side of the frame", "Pedestrians turn."),
        ("The worker is 1.5 m from the edge.", ""),  # never rounded into a different distance
        ("At timestamp 7.2 s, a truck stops.", ""),
        ("A van (a van) stops near Camera B (Camera B).", "A van stops near Camera B."),
    ],
)
def test_describe_observation(ctx, description, expected):
    assert describe_observation(description, ctx, camera_name="Camera B") == expected


def test_long_descriptions_end_at_a_clause_not_mid_word(ctx):
    long = (
        "A white pickup truck slows down and comes to a stop near the curb while a person in a "
        "red jacket walks toward it from the parking lot"
    )
    assert describe_observation(long, ctx) == (
        "A white pickup truck slows down and comes to a stop near the curb."
    )
    words = "A very long description " + "with many plain words " * 8
    clipped = describe_observation(words, ctx)
    assert len(clipped) <= 111 and clipped.endswith("…") and not clipped[:-1].endswith(" ")


def test_type_labels_humanize_only_plain_type_names(config):
    assert type_label("forklift_near_miss") == "Forklift near miss"
    assert type_label("ppe_violation", config.acronyms) == "PPE violation"
    assert type_label("camera_blocked") == "Camera blocked"
    for raw in ("AGV-blocked-aisle", "region_01", "cam_gt", "camera_gt", "msg_02", "", "x" * 41):
        assert type_label(raw) == "Something unusual", raw
    assert config.event("Call 911 now").label == "Something unusual"
    assert config.cue("person_edge_transit").label == "Person passing through"
    leaky = AlertConfig.from_mapping({"events": {"vehicle_stop": {"label": "Stop at region_01"}}})
    assert leaky.event("vehicle_stop").label == "Vehicle stop"  # a leaking label is not used


def test_is_technical_keeps_plain_text():
    for plain in (
        "Likely (60%)",
        "0:07–0:27 into the clip",
        "In the blind spot about 30 m north of Camera B",
        "Camera A, Camera B and Camera C",
        "A truck turns left at pickup/dropoff.",
        "15:41:02–15:41:27 on 15 Mar 2018",
    ):
        assert not is_technical(plain), plain


@pytest.mark.parametrize(
    ("raw", "kept", "gone"),
    [
        (
            (
                "FileNotFoundError: [Errno 2] No such file or directory: "
                "'/home/dell/.config/cameravision/telegram.env'"
            ),
            "No such file or directory",
            ["FileNotFoundError", "/home", "telegram.env"],
        ),
        ("chat_id=-1001234567890 failed: 401", "failed: 401", ["1001234567890"]),
        (
            "token=abcd1234efgh5678 Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln",
            "Bearer <redacted>",
            ["abcd1234", "eyJ"],
        ),
        ("401 for chat 987654321012", "401 for chat", ["987654321012"]),
        ("see ~/secrets/bot.env", "see <path>", ["secrets"]),
    ],
)
def test_redact_detail_masks_paths_and_secrets(raw, kept, gone):
    detail = redact_detail(raw)
    assert kept in detail
    for token in gone:
        assert token not in detail

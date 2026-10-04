"""/hazards contract: contracts/hazard_view.schema.json and its examples.

The examples are built from the REAL original run (contracts/examples/hazards/source/,
verbatim) and a REAL OpenClaw agent run (source/agent_run/, verbatim) by
scripts/hazards/build_view_examples.py; this test fails when they drift from the composer,
the wording in config/hazards.yaml or the wall in config/wall.yaml. runtime_status.json is
a captured GET /api/runtime/status and is only validated.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from apps.api.schemas import REPO_ROOT
from apps.api.services import hazards as hz

SCHEMA_PATH = REPO_ROOT / "contracts" / "hazard_view.schema.json"
EXAMPLES = REPO_ROOT / "contracts" / "examples" / "hazards"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
# sha256 of the original hazard_report.json / run_manifest.json (GB10_BUNDLE example_output).
SOURCE_SHA256 = {
    "hazard_report.json": "f3dac3afb72313442f57bf9781454aa9dfae30703f729ba28e8104a91ad8eb33",
    "run_manifest.json": "fc2e1a4cf81ff1fd5f0b4e894389eedf8789ee173743d2bae566b76122b52926",
}
# sha256 of the agent run's files (data/hazards/reports/hz_02/ed02d540b08f6395/).
AGENT_SOURCE_SHA256 = {
    "agent_summary.json": "278edda01c43b6c6410bf4f9548cfec3c96023c25606d1ca0e477f7a11e6ec90",
    "agent_trace.json": "1caff0f6aa98b792923ba48a0727dffc2f0fc5ce3a06ce0428186505aa7355b1",
    "hazard_report.json": "49f4fca3735a7ca72053ef724b5374d5d1a8bf7afda196f3404142d924964e0b",
    "job_timeline.json": "3bdb8e2bf28a0946e7125f90ca07ac083385f5ac3f10fb9cd8062165e3a65d0e",
    "run_manifest.json": "8eaa841321fefe9eba05cd10025700f70d69caf201a92fc8158ce6031c18df04",
}
EXAMPLE_DEFS = {
    "hazard_view.json": "HazardView",
    "hazard_view_not_reviewed.json": "HazardView",
    "hazard_view_agent.json": "HazardView",
    "clips.json": "ClipList",
    "instructions.json": "Instructions",
    "review_accepted.json": "ReviewAccepted",
    "job_latest.json": "JobSummary",
    "job_events.json": "JobEventList",
    "job_events_agent.json": "JobEventList",
    "job_events_failed.json": "JobEventList",
    "wall.json": "Wall",
    "runtime_status.json": "RuntimeStatus",
}

_SPEC = importlib.util.spec_from_file_location(
    "build_view_examples", REPO_ROOT / "scripts" / "hazards" / "build_view_examples.py"
)
assert _SPEC is not None and _SPEC.loader is not None
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def validator(def_name: str) -> Draft202012Validator:
    ref = {"$ref": f"{SCHEMA['$id']}#/$defs/{def_name}"}
    return Draft202012Validator(ref, registry=REGISTRY)


def load(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$ref"] == "#/$defs/HazardView"


def test_example_files_are_exactly_the_listed_ones() -> None:
    assert {p.name for p in EXAMPLES.glob("*.json")} == set(EXAMPLE_DEFS)
    assert {p.name for p in (EXAMPLES / "source").glob("*.json")} == set(SOURCE_SHA256)
    assert {p.name for p in (EXAMPLES / "source" / "agent_run").glob("*.json")} == set(
        AGENT_SOURCE_SHA256
    )


@pytest.mark.parametrize("name", sorted(EXAMPLE_DEFS))
def test_example_validates(name: str) -> None:
    validator(EXAMPLE_DEFS[name]).validate(load(name))


def test_top_level_document_is_a_hazard_view() -> None:
    Draft202012Validator(SCHEMA, registry=REGISTRY).validate(load("hazard_view.json"))


@pytest.mark.parametrize("name", sorted(SOURCE_SHA256))
def test_source_is_the_verbatim_original_run(name: str) -> None:
    digest = hashlib.sha256((EXAMPLES / "source" / name).read_bytes()).hexdigest()
    assert digest == SOURCE_SHA256[name]


@pytest.mark.parametrize("name", sorted(AGENT_SOURCE_SHA256))
def test_agent_source_is_the_verbatim_agent_run(name: str) -> None:
    digest = hashlib.sha256((EXAMPLES / "source" / "agent_run" / name).read_bytes()).hexdigest()
    assert digest == AGENT_SOURCE_SHA256[name]


def test_examples_match_the_composer() -> None:
    built = builder.build()
    assert set(built) == set(EXAMPLE_DEFS) - set(builder.STATIC_EXAMPLES)
    for name, doc in built.items():
        assert load(name) == json.loads(builder.dump(doc)), (
            f"{name} is stale: run .venv/bin/python scripts/hazards/build_view_examples.py"
        )


def test_reviewed_example_content() -> None:
    view = load("hazard_view.json")
    report = json.loads((EXAMPLES / "source" / "hazard_report.json").read_text("utf-8"))
    assert view["clip"] == {
        "clip_id": "hz_00",
        "title": "Press line camera",
        "duration_s": 12.605,
        "kind": "hazard",
    }
    assert view["worker"]["headline"] == "2 safety hazards found"
    assert [h["title"] for h in view["worker"]["hazards"]] == [
        "Obstruction in marked aisle",
        "Worker proximity to machine point of operation",
    ]
    assert view["vision"]["images_sent"] == len(report["evidence"]) == 35
    assert view["technical"]["dataset_label"] == "4_safe_walkway"
    assert view["technical"]["run_id"] == builder.original_run_id(report)
    prompts = hz.prompts_from_script()
    assert view["technical"]["system_prompt"] == prompts["system_prompt"]
    assert view["technical"]["audit_prompt"] == prompts["audit_prompt"]
    # Times follow the script: frame_index / source_fps.
    fps = report["video"]["fps"]
    for image, item in zip(view["vision"]["shown_images"], report["evidence"], strict=True):
        assert image["time_s"] == pytest.approx(item["frame_index"] / fps, abs=1e-3)
        # image_url is the clean picture (no burned-in strip); raw_url the stored one.
        assert image["image_url"].endswith(f"/evidence_clean/{item['evidence_id']}.jpg")
        assert image["raw_url"].endswith(f"/evidence/{item['evidence_id']}.jpg")
        # Zone pictures are captioned by zone, whole-scene ones by kind ("Busiest moment").
        label = image["kind_word"] if image["zone_name"] == "Whole view" else image["zone_name"]
        assert image["caption"] == f"{label} · {image['time_label']}"
    # Zones are numbered and boxed as fractions of the video frame.
    zones = view["worker"]["zones"]
    assert [z["name"] for z in zones] == [f"Zone {z['number']}" for z in zones]
    assert all(0 <= v <= 1 for z in zones for v in z["box"])
    # Every hazard card has a sign and a short title.
    for hazard in view["worker"]["hazards"]:
        assert hazard["sign"]["label"] and hazard["sign"]["glyph"]
        assert len(hazard["short_title"].split()) <= 6


def _without_urls(doc: Any) -> Any:
    if isinstance(doc, dict):
        return {k: _without_urls(v) for k, v in doc.items() if not k.endswith("url")}
    if isinstance(doc, list):
        return [_without_urls(v) for v in doc]
    return doc


@pytest.mark.parametrize("name", ["hazard_view.json", "hazard_view_agent.json"])
def test_example_worker_is_leak_free(name: str) -> None:
    worker = _without_urls(copy.deepcopy(load(name)["worker"]))
    text = json.dumps(worker, ensure_ascii=False)
    assert hz.leaks(text) == []
    for word in ("qwen", "violation", "http", "bbox", "4_tr1", "safe_walkway", "openclaw"):
        assert word not in text.lower()
    assert not re.search(r"\bsha(?:256)?\b", text, re.IGNORECASE)
    assert not re.search(r"\b[ZEH]\d{2,3}\b", text)


def test_agent_example_content() -> None:
    view = load("hazard_view_agent.json")
    summary = json.loads((EXAMPLES / "source" / "agent_run" / "agent_summary.json").read_text())
    trace = json.loads((EXAMPLES / "source" / "agent_run" / "agent_trace.json").read_text())
    technical = view["technical"]
    assert technical["runner"] == "openclaw-agent"
    assert technical["agent"]["agent_id"] == "urban-mirror"
    assert technical["agent"]["sandbox"] == "ambient-mirror"
    assert technical["agent"]["summary"] == summary
    assert len(technical["agent"]["trace"]) == len(trace)
    assert technical["replay"]["note"] == "Replay of the GB10 run from 2026-10-03 18:55 UTC"
    assert technical["replay"]["run_id"] == technical["run_id"] == "ed02d540b08f6395"
    assert view["worker"]["agent_summary"]["first_action"]
    assert view["technical"]["dataset_label"] == "0_safe_walkway_violation"


def test_agent_replay_events_follow_the_recorded_run() -> None:
    events = load("job_events_agent.json")
    names = [e["event"] for e in events]
    assert names.count("progress") == 6 and names.count("agent") >= 4
    assert names[-1] == "done"
    steps = [e["data"]["step"] for e in events if e["event"] == "progress"]
    assert steps == [1, 2, 3, 4, 5, 6]
    times = [e["data"]["t_s"] for e in events[:-1]]
    assert times == sorted(times)
    # The demo replay lasts the configured length (config/hazards.yaml demo_replay:
    # total_seconds, else the 25-40 s clamp) and leaves tail_s before "done".
    pacing = hz.load_wording()["demo_replay"]
    longest = float(pacing.get("total_seconds") or 0) or float(pacing["max_total_s"])
    assert 0 < times[-1] <= longest - float(pacing["tail_s"]) + 0.01
    done = events[-1]["data"]
    assert done["replay"] is True and done["runner"] == "openclaw-agent"
    assert done["note"].startswith("Replay of the GB10 run from ")


def test_wall_example_is_factory_only() -> None:
    wall = load("wall.json")
    assert wall["title"] == "Site cameras · Factory floor"
    assert [t["cam"] for t in wall["hazard_tiles"]] == [1, 2, 3]
    assert [t["cam"] for t in wall["blindspot_tiles"]] == [4, 5, 6]
    assert {t["kind"] for t in wall["hazard_tiles"]} == {"hazard"}
    assert {t["kind"] for t in wall["blindspot_tiles"]} == {"blindspot"}
    text = json.dumps(wall).lower()
    for word in ("bus", "station", "intersection", "meva", "scenario", "/ops", "withheld"):
        assert word not in text


def test_runtime_status_example_has_every_row_and_no_secrets() -> None:
    status = load("runtime_status.json")
    assert [r["key"] for r in status["rows"]] == [
        "nemoclaw",
        "openclaw",
        "openshell",
        "tool_server",
        "qwen",
        "detector",
        "network",
    ]
    text = json.dumps(status).lower()
    for word in ("token", "bearer", "secret", "password", "api_key"):
        assert word not in text


@pytest.mark.parametrize(
    "bad_text",
    [
        "The object is in sampled frames (E024, E025).",
        "Center of the marked aisle, Z07",
        "Qwen saw a pallet.",
        "This is a violation.",
        "See https://www.osha.gov/x",
        "status needs_verification",
        "bbox 553",
        "sha256 1c52",
    ],
)
def test_plain_text_rejects_leaks(bad_text: str) -> None:
    view = load("hazard_view.json")
    view["worker"]["hazards"][0]["what_we_saw"] = bad_text
    with pytest.raises(ValidationError):
        validator("HazardView").validate(view)


def test_worker_hazard_rejects_extra_fields_and_raw_ids() -> None:
    view = load("hazard_view.json")
    view["worker"]["hazards"][0]["zone_ids"] = ["Z07"]
    with pytest.raises(ValidationError):
        validator("HazardView").validate(view)
    view = load("hazard_view.json")
    view["worker"]["hazards"][0]["id"] = "H01"
    with pytest.raises(ValidationError):
        validator("HazardView").validate(view)


def test_technical_video_never_carries_the_source_name() -> None:
    view = load("hazard_view.json")
    view["technical"]["video"]["source_name"] = "4_tr1.mp4"
    with pytest.raises(ValidationError):
        validator("HazardView").validate(view)


def test_job_event_payloads_are_checked_by_event_name() -> None:
    events = load("job_events.json")
    assert [e["event"] for e in events] == ["progress"] * 6 + ["done"]
    bad = copy.deepcopy(load("job_events_agent.json"))
    bad[0]["data"].pop("text")
    with pytest.raises(ValidationError):
        validator("JobEventList").validate(bad)
    bad = copy.deepcopy(events)
    bad[0]["data"].pop("plain_message")
    with pytest.raises(ValidationError):
        validator("JobEventList").validate(bad)
    bad = copy.deepcopy(events)
    bad[-1]["data"] = {"plain_message": "x"}
    with pytest.raises(ValidationError):
        validator("JobEventList").validate(bad)

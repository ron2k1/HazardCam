"""Safety hazard API (/api/hazards): clips, plain worker view, review jobs, media.

The report under test is the REAL teammate run (contracts/examples/hazards/source/,
verbatim). Video and image bytes are placeholders: only HTTP serving is exercised here.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import threading
import types
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT
from apps.api.services import hazards as hz
from apps.api.services.hazards import HazardService
from apps.api.settings import Settings

SOURCE = REPO_ROOT / "contracts" / "examples" / "hazards" / "source"
SCHEMA = json.loads((REPO_ROOT / "contracts" / "hazard_view.schema.json").read_text("utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
WORDING = hz.load_wording()
RUN_ID = "ed487eb3f1181f38"
SOURCE_BYTES = bytes(range(256)) * 64  # 16 KiB placeholder, not a real video
LEAK_CHECKS = (
    r"\b[EZH]\d{2,3}\b",
    r"bbox",
    # "sha" as a word or sha256: the real text legitimately says "shadow" and "shavings".
    r"\bsha(?:-?256)?\b",
    r"http",
    r"needs_verification",
    r"visible_concern",
    r"hazard_candidate",
    r"qwen",
    r"violation",
    r"non-?compliant",
    r"\b[0-9a-f]{16,}\b",
    r"\.(?:mp4|jpg|png|json)\b",
)


def validate(def_name: str, doc: Any) -> None:
    ref = {"$ref": f"{SCHEMA['$id']}#/$defs/{def_name}"}
    Draft202012Validator(ref, registry=REGISTRY).validate(doc)


def load_source(name: str) -> dict[str, Any]:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def write_run(root: Path, clip_id: str, run_id: str, report: dict[str, Any]) -> Path:
    run_dir = root / "reports" / clip_id / run_id
    write_json(run_dir / "hazard_report.json", report)
    write_json(run_dir / "run_manifest.json", load_source("run_manifest.json"))
    (run_dir / "processed.mp4").write_bytes(SOURCE_BYTES[:4096])
    for item in report.get("evidence", []):
        path = run_dir / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff\xe0" + item["evidence_id"].encode() + b"\xff\xd9")
    write_json(
        root / "reports" / clip_id / "latest_run.json",
        {"run_id": run_id, "path": str(run_dir), "status": report.get("status")},
    )
    return run_dir


def write_clip(root: Path, clip_id: str, title: str, duration_s: float) -> None:
    clip_dir = root / "clips" / clip_id
    write_json(
        clip_dir / "clip.json", {"clip_id": clip_id, "title": title, "duration_s": duration_s}
    )
    (clip_dir / "source.mp4").write_bytes(SOURCE_BYTES)


@pytest.fixture
def report_doc() -> dict[str, Any]:
    return load_source("hazard_report.json")


@pytest.fixture
def hazard_root(tmp_path: Path, report_doc: dict[str, Any]) -> Path:
    """hz_00: the real teammate run, reviewed. hz_01: a prepared clip, never reviewed."""
    root = tmp_path / "hazards"
    write_clip(root, "hz_00", "Press line camera", 12.605)
    write_clip(root, "hz_01", "Floor camera 01", 14.982)
    write_run(root, "hz_00", RUN_ID, report_doc)
    write_json(
        root / "labels" / "hz_00.json",
        {"dataset_label": "4_safe_walkway", "dataset_split": "train", "original_name": "4_tr1.mp4"},
    )
    (tmp_path / "outside.txt").write_text("not served", encoding="utf-8")
    (root / "secret.txt").write_text("not served", encoding="utf-8")
    return root


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        manifests_dir=tmp_path / "manifests",
        prepared_dir=tmp_path / "prepared",
        runs_dir=tmp_path / "runs",
        media_root=tmp_path,
    )


@pytest.fixture
async def client(hazard_root: Path, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Fixture profile (the default): reviews replay stored steps, no model call."""
    app = create_app(settings)
    app.state.hazards = HazardService(hazard_root, profile="fixture", replay_pace_s=0.0)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def model_client(
    settings: Settings, hazard_root: Path, review_fn: Callable[..., Any] | None = None
) -> httpx.AsyncClient:
    app = create_app(settings)
    app.state.hazards = HazardService(
        hazard_root, profile="gb10", fixture=False, review_fn=review_fn
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def parse_sse(text: str) -> list[dict[str, Any]]:
    messages = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        data: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data.append(value)
            else:
                fields[key] = value
        if data:
            messages.append(
                {
                    "id": fields.get("id"),
                    "event": fields.get("event"),
                    "data": json.loads("\n".join(data)),
                }
            )
    return messages


async def read_events(
    client: httpx.AsyncClient, job_id: str, **kwargs: Any
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    response = await asyncio.wait_for(
        client.get(f"/api/hazards/jobs/{job_id}/events", **kwargs), timeout=10
    )
    return response, parse_sse(response.text)


def worker_text(worker: dict[str, Any]) -> str:
    """The worker block as JSON with media routes masked: ``*url`` values carry the
    spec'd route ``.../evidence/E###.jpg`` and are never displayed as text."""

    def mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: "<url>" if k.endswith("url") else mask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(v) for v in value]
        return value

    return json.dumps(mask(worker), ensure_ascii=False)


def fake_pipeline_run(
    calls: list[dict[str, Any]],
    *,
    report: dict[str, Any],
    before: Callable[[], None] | None = None,
) -> Callable[..., Path]:
    """A stand-in for ``hazards.pipeline.review_clip`` that writes a finished run."""

    def review_clip(
        video: Path,
        output_root: Path,
        *,
        source_name: str,
        profile: str | None = None,
        skip_model: bool = False,
        refresh: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> Path:
        calls.append(
            {
                "video": video,
                "output_root": output_root,
                "source_name": source_name,
                "profile": profile,
                "skip_model": skip_model,
                "refresh": refresh,
            }
        )
        assert progress is not None
        progress(1, 6, hz.SCRIPT_STEPS[0])
        if before is not None:
            before()
        for step in range(2, 7):
            progress(step, 6, hz.SCRIPT_STEPS[step - 1])
        root = output_root.parents[1]
        return write_run(root, output_root.name, "run_fresh", report)

    return review_clip


# --------------------------------------------------------------------------- clips + view


async def test_list_clips_summarizes_latest_reports(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/hazards/clips")
    assert response.status_code == 200
    body = response.json()
    validate("ClipList", body)
    by_id = {c["clip_id"]: c for c in body["clips"]}
    assert list(by_id) == ["hz_00", "hz_01"]
    assert by_id["hz_00"] == {
        "clip_id": "hz_00",
        "title": "Press line camera",
        "duration_s": 12.605,
        "kind": "hazard",
        "status": "reviewed",
        "hazard_count": 2,
        "top_priority": "medium",
        "needs_check_count": 1,
        "reviewed_at": "2026-10-03T16:55:57.560131+00:00",
    }
    assert by_id["hz_01"]["status"] == "not_reviewed"
    assert by_id["hz_01"]["hazard_count"] == 0
    assert by_id["hz_01"]["top_priority"] is None
    assert by_id["hz_01"]["reviewed_at"] is None


async def test_view_of_real_report_matches_contract(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/hazards/clips/hz_00")
    assert response.status_code == 200
    view = response.json()
    validate("HazardView", view)
    assert view["status"] == "reviewed"
    worker = view["worker"]
    assert worker["headline"] == "2 safety hazards found"
    first, second = worker["hazards"]
    assert first["title"] == "Obstruction in marked aisle"
    assert first["priority"] == "Medium" and first["how_sure"] == "High"
    assert first["needs_check"] is False and second["needs_check"] is True
    # The review's location names its zone, so no zone prefix is added in front.
    assert first["where"] == "Center of the marked aisle, Zone 7"
    assert first["zone_names"] == ["Zone 7"] and second["zone_names"] == ["Zone 3"]
    assert first["short_title"] == "Obstruction in marked aisle"
    assert first["sign"] == {"label": "BLOCKED AISLE", "glyph": "forklift"}
    assert second["sign"] == {"label": "PRESS GUARD", "glyph": "machine"}
    assert first["when"] == "0:00–0:12 of the clip"
    assert first["safety_rule"] == "Aisles and material handling (OSHA 1910.176(a))"
    assert second["safety_rule"] == "Mechanical power press safeguarding (OSHA 1910.217(c)(1)(i))"
    # The card shows the observation's first sentence; the full text is in technical.
    assert first["what_we_saw"] == (
        "A large circular metal object is resting on the floor directly across the yellow "
        "painted boundary line of the main aisle."
    )
    assert second["what_we_saw"] == "A worker is seated at the controls of a mechanical press."
    assert [e["kind_label"] for e in first["evidence"]] == ["Close-up", "Section", "Close-up"]
    assert [e["time_label"] for e in first["evidence"]] == ["0:00", "0:06", "0:12"]
    assert first["evidence"][0] == {
        "image_url": "/api/hazards/clips/hz_00/media/evidence_clean/E024.jpg",
        "raw_url": "/api/hazards/clips/hz_00/media/evidence/E024.jpg",
        "time_s": 0.0,
        "time_label": "0:00",
        "kind_label": "Close-up",
        "kind_word": "Close-up",
        "zone_name": "Zone 7",
        "caption": "Zone 7 · 0:00",
        "cited": True,
    }
    assert first["pictures"][0]["url"] == "/api/hazards/clips/hz_00/media/evidence/E024.jpg"
    assert first["pictures"][0]["clean_url"].endswith("/evidence_clean/E024.jpg")
    assert worker["ruled_out"][0] == {
        "what": "Potential slip hazard from dark area on floor",
        # Zone ids are named the way the zone overlay labels them ("Zone 6").
        "why": (
            "The dark area in Zone 6 is likely a shadow or surface variation; no liquid spill "
            "is visible."
        ),
    }
    vision = view["vision"]
    assert vision["frames_scanned"] == 315
    assert vision["images_sent"] == 35 == len(vision["shown_images"])
    assert vision["areas_marked"] == 10
    assert vision["processed_video_url"] == "/api/hazards/clips/hz_00/media/processed.mp4"
    assert vision["source_video_url"] == "/api/hazards/clips/hz_00/media/source.mp4"
    assert vision["instructions"]["checks"] == WORDING["checks"]
    technical = view["technical"]
    assert technical["dataset_label"] == "4_safe_walkway"
    assert technical["run_id"] == RUN_ID
    assert technical["request_sha256"].startswith("1c52395194440a85")
    assert technical["segmentation_method"] == "FastSAM-s temporal-background masks"
    assert technical["quality_warnings"] == []
    assert technical["system_prompt"].startswith("Review industrial video evidence")
    assert technical["audit_prompt"].startswith("Review and correct the draft report")
    assert [z["zone_id"] for z in technical["zones"]] == [f"Z{i:02d}" for i in range(1, 11)]
    assert [f["finding_id"] for f in technical["findings_raw"]] == ["H01", "H02"]


async def test_worker_block_does_not_leak(client: httpx.AsyncClient) -> None:
    view = (await client.get("/api/hazards/clips/hz_00")).json()
    text = worker_text(view["worker"])
    for pattern in LEAK_CHECKS:
        assert not re.search(pattern, text, re.IGNORECASE), pattern
    assert hz.leaks(text) == []
    for hazard in view["worker"]["hazards"]:
        for image in hazard["evidence"]:
            assert image["image_url"].startswith("/api/hazards/clips/hz_00/media/evidence_clean/")
            assert image["raw_url"].startswith("/api/hazards/clips/hz_00/media/evidence/")


async def test_labels_and_file_names_stay_out_of_worker_and_vision(
    client: httpx.AsyncClient,
) -> None:
    view = (await client.get("/api/hazards/clips/hz_00")).json()
    plain = json.dumps({"worker": view["worker"], "vision": view["vision"], "clip": view["clip"]})
    for secret in (r"safe_walkway", r"4_tr1", r"\btrain\b", r"dataset_"):
        assert not re.search(secret, plain), secret
    # The original file name (whose prefix is the label index) is not served anywhere.
    assert "4_tr1" not in json.dumps(view)
    assert "source_name" not in view["technical"]["video"]


async def test_shown_images_follow_report_order_and_frame_timing(
    client: httpx.AsyncClient, report_doc: dict[str, Any]
) -> None:
    view = (await client.get("/api/hazards/clips/hz_00")).json()
    fps = report_doc["video"]["fps"]
    shown = view["vision"]["shown_images"]
    assert [i["image_url"].rsplit("/", 1)[1] for i in shown] == [
        f"{e['evidence_id']}.jpg" for e in report_doc["evidence"]
    ]
    for image, item in zip(shown, report_doc["evidence"], strict=True):
        # Same assumption as the script: time = frame_index / source_fps.
        assert image["time_s"] == pytest.approx(item["frame_index"] / fps, abs=1e-3)
    kinds = [i["kind_label"] for i in shown]
    # 11 whole-scene pictures: the 8 evenly spaced overview frames are "Whole view", the
    # rest are the motion peaks ("Busiest moment").
    assert kinds[:11].count("Whole view") == 8 and kinds[:11].count("Busiest moment") == 3
    assert kinds[11:] == ["Close-up"] * 20 + ["Section"] * 4


async def test_not_reviewed_view(client: httpx.AsyncClient) -> None:
    view = (await client.get("/api/hazards/clips/hz_01")).json()
    validate("HazardView", view)
    assert view["status"] == "not_reviewed"
    assert view["worker"]["headline"] == "This clip has not been checked yet"
    assert view["worker"]["hazards"] == []
    assert view["vision"]["processed_video_url"] is None
    assert view["vision"]["shown_images"] == []
    assert view["technical"]["dataset_label"] is None


@pytest.mark.parametrize("clip_id", ["hz_99", "..", "hz_00%2F..", ".hidden"])
async def test_unknown_clip_is_404(client: httpx.AsyncClient, clip_id: str) -> None:
    assert (await client.get(f"/api/hazards/clips/{clip_id}")).status_code == 404


async def test_instructions(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/hazards/instructions")).json()
    validate("Instructions", body)
    assert body["checks"] == WORDING["checks"] and body["rules"] == WORDING["rules"]
    assert "Look for objects blocking marked walkways and aisles" in body["checks"][1]
    assert body["system_prompt"].startswith("Review industrial video evidence")
    assert "Return only the requested JSON schema." in body["system_prompt"]
    assert body["audit_prompt"].endswith("Do not invent hazards to fill a checklist.")


async def test_service_is_created_from_env(
    hazard_root: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAZARDS_DIR", str(hazard_root))
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        clips = (await c.get("/api/hazards/clips")).json()["clips"]
    assert [c["clip_id"] for c in clips] == ["hz_00", "hz_01"]
    assert app.state.hazards.fixture is True  # MODEL_PROFILE default: fixture


# --------------------------------------------------------------------------- media


async def test_source_video_answers_range_with_206(client: httpx.AsyncClient) -> None:
    url = "/api/hazards/clips/hz_00/media/source.mp4"
    response = await client.get(url, headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-99/{len(SOURCE_BYTES)}"
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == SOURCE_BYTES[:100]
    full = await client.get(url)
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"


async def test_processed_video_and_evidence_are_served(client: httpx.AsyncClient) -> None:
    processed = await client.get("/api/hazards/clips/hz_00/media/processed.mp4")
    assert processed.status_code == 200 and processed.headers["content-type"] == "video/mp4"
    image = await client.get("/api/hazards/clips/hz_00/media/evidence/E024.jpg")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert b"E024" in image.content
    ranged = await client.get(
        "/api/hazards/clips/hz_00/media/processed.mp4", headers={"Range": "bytes=10-19"}
    )
    assert ranged.status_code == 206 and len(ranged.content) == 10


async def test_motion_timeline_is_served_from_the_current_run(
    hazard_root: Path, client: httpx.AsyncClient
) -> None:
    url = "/api/hazards/clips/hz_00/media/motion_timeline.csv"
    assert (await client.get(url)).status_code == 404  # this run has none yet
    rows = "time_s,motion_fraction,adjacent_change_fraction\n0.0,0.0,0.0\n0.0333,0.0261,0.0012\n"
    (hazard_root / "reports" / "hz_00" / RUN_ID / "motion_timeline.csv").write_bytes(
        rows.encode("utf-8")
    )
    response = await client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text == rows
    assert (await client.get("/api/hazards/clips/hz_01/media/motion_timeline.csv")).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/hazards/clips/hz_00/media/evidence/E999.jpg",
        "/api/hazards/clips/hz_00/media/evidence/E24.jpg",
        "/api/hazards/clips/hz_00/media/evidence/E024.png",
        "/api/hazards/clips/hz_00/media/hazard_report.json",
        "/api/hazards/clips/hz_00/media/clip.json",
        "/api/hazards/clips/hz_00/media/%2e%2e/%2e%2e/secret.txt",
        "/api/hazards/clips/hz_00/media/evidence%2F..%2F..%2F..%2F..%2Fsecret.txt",
        "/api/hazards/clips/hz_00/media/..%2F..%2Flabels%2Fhz_00.json",
        "/api/hazards/clips/hz_00/media//etc/passwd",
        "/api/hazards/clips/..%2Fhazards/media/source.mp4",
        "/api/hazards/clips/hz_99/media/source.mp4",
        "/api/hazards/clips/hz_01/media/processed.mp4",
        "/api/hazards/clips/hz_01/media/evidence/E001.jpg",
    ],
)
async def test_media_refuses_unknown_names_and_traversal(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 404


async def test_media_refuses_files_not_in_the_report_or_outside_the_root(
    hazard_root: Path, tmp_path: Path, client: httpx.AsyncClient
) -> None:
    extra = hazard_root / "reports" / "hz_00" / RUN_ID / "evidence" / "E036.jpg"
    extra.write_bytes(b"\xff\xd8\xff\xd9")
    assert (await client.get("/api/hazards/clips/hz_00/media/evidence/E036.jpg")).status_code == 404
    write_clip(hazard_root, "hz_02", "Floor camera 02", 1.0)
    source = hazard_root / "clips" / "hz_02" / "source.mp4"
    source.unlink()
    source.symlink_to(tmp_path / "outside.txt")
    assert (await client.get("/api/hazards/clips/hz_02/media/source.mp4")).status_code == 404


# --------------------------------------------------------------------------- jobs


async def test_fixture_review_replays_stored_steps_without_model_calls(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_model(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the fixture profile must not run the pipeline")

    monkeypatch.setitem(
        sys.modules, "hazards.pipeline", types.SimpleNamespace(review_clip=no_model)
    )
    response = await client.post("/api/hazards/clips/hz_00/review")
    assert response.status_code == 202
    accepted = response.json()
    validate("ReviewAccepted", accepted)
    stream, messages = await read_events(client, accepted["job_id"])
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert [m["event"] for m in messages] == ["progress"] * 6 + ["done"]
    assert [m["id"] for m in messages] == [str(i) for i in range(1, 8)]
    progress = [m["data"] for m in messages[:6]]
    for event in progress:
        validate("ProgressEvent", event)
    assert [p["message"] for p in progress] == list(hz.SCRIPT_STEPS)
    assert [p["plain_message"] for p in progress] == WORDING["steps"]
    assert messages[-1]["data"] == {
        "clip_id": "hz_00",
        "run_id": RUN_ID,
        "reviewed_at": "2026-10-03T16:55:57.560131+00:00",
        "runner": "direct",
        "replay": True,
        "note": "Replay of the stored run from 2026-10-03 16:55 UTC",
    }
    assert accepted["mode"] == "replay" and accepted["runner"] == "direct"
    clips = (await client.get("/api/hazards/clips")).json()["clips"]
    assert clips[0]["status"] == "reviewed"
    _, resumed = await read_events(client, accepted["job_id"], headers={"Last-Event-ID": "5"})
    assert [m["id"] for m in resumed] == ["6", "7"]


async def test_fixture_review_without_saved_report_fails_in_plain_words(
    client: httpx.AsyncClient,
) -> None:
    job_id = (await client.post("/api/hazards/clips/hz_01/review", json={})).json()["job_id"]
    _, messages = await read_events(client, job_id)
    assert [m["event"] for m in messages] == ["failed"]
    validate("FailedEvent", messages[0]["data"])
    assert messages[0]["data"]["plain_message"] == WORDING["messages"]["no_saved_review"]
    clip = (await client.get("/api/hazards/clips/hz_01")).json()
    assert clip["status"] == "failed"
    assert clip["worker"]["headline"] == "The check did not finish"


async def test_review_conflict_while_running_then_done(
    settings: Settings, hazard_root: Path, report_doc: dict[str, Any]
) -> None:
    started, release = threading.Event(), threading.Event()
    calls: list[dict[str, Any]] = []

    def hold() -> None:
        started.set()
        assert release.wait(10)

    review = fake_pipeline_run(calls, report=report_doc, before=hold)
    async with await model_client(settings, hazard_root, review) as client:
        try:
            first = await client.post("/api/hazards/clips/hz_01/review", json={"refresh": True})
            assert first.status_code == 202
            job_id = first.json()["job_id"]
            assert await asyncio.to_thread(started.wait, 10)
            second = await client.post("/api/hazards/clips/hz_01/review")
            assert second.status_code == 409
            assert second.json()["job_id"] == job_id
            clips = (await client.get("/api/hazards/clips")).json()["clips"]
            assert {c["clip_id"]: c["status"] for c in clips}["hz_01"] == "reviewing"
            other = await client.post("/api/hazards/clips/hz_00/review")
            assert other.status_code == 202  # one job per clip, not per server
        finally:
            release.set()
        _, messages = await read_events(client, job_id)
        assert [m["event"] for m in messages] == ["progress"] * 6 + ["done"]
        assert [m["data"]["step"] for m in messages[:6]] == [1, 2, 3, 4, 5, 6]
        assert messages[0]["data"]["plain_message"] == "Reading the video"
        clips = (await client.get("/api/hazards/clips")).json()["clips"]
        assert {c["clip_id"]: c["status"] for c in clips}["hz_01"] == "reviewed"
        view = (await client.get("/api/hazards/clips/hz_01")).json()
        assert view["technical"]["run_id"] == "run_fresh"
        assert view["technical"]["dataset_label"] is None
    call = next(c for c in calls if c["source_name"] == "hz_01")
    # Neutral clip id as source_name: labels / original names never reach the pipeline.
    assert call["video"] == (hazard_root / "clips" / "hz_01" / "source.mp4").resolve()
    assert call["output_root"] == hazard_root / "reports" / "hz_01"
    assert call["profile"] == "gb10"
    assert call["skip_model"] is False and call["refresh"] is True


async def test_pipeline_is_imported_lazily(
    settings: Settings,
    hazard_root: Path,
    report_doc: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    module = types.ModuleType("hazards.pipeline")
    module.review_clip = fake_pipeline_run(calls, report=report_doc)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hazards.pipeline", module)
    async with await model_client(settings, hazard_root) as client:
        job_id = (await client.post("/api/hazards/clips/hz_01/review")).json()["job_id"]
        _, messages = await read_events(client, job_id)
    assert messages[-1]["id"] == "7" and messages[-1]["event"] == "done"
    done = messages[-1]["data"]
    assert done["clip_id"] == "hz_01" and done["run_id"] == "run_fresh"
    assert done["runner"] == "direct" and done["replay"] is False
    assert calls and calls[0]["refresh"] is False


async def test_pipeline_error_fails_in_plain_words(
    settings: Settings, hazard_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any, progress: Callable[..., None], **kwargs: Any) -> Path:
        progress(1, 6, hz.SCRIPT_STEPS[0])
        raise RuntimeError("vLLM at 127.0.0.1:8000 refused sha deadbeef")

    async with await model_client(settings, hazard_root, broken) as client:
        job_id = (await client.post("/api/hazards/clips/hz_01/review")).json()["job_id"]
        response, messages = await read_events(client, job_id)
        assert [m["event"] for m in messages] == ["progress", "failed"]
        assert messages[-1]["data"] == {"plain_message": WORDING["messages"]["failed"]}
        assert "vLLM" not in response.text and "deadbeef" not in response.text
        assert "vLLM at 127.0.0.1:8000" in caplog.text  # kept for the operator log
        clip = (await client.get("/api/hazards/clips/hz_01")).json()
        assert clip["status"] == "failed"


async def test_model_review_failed_report_fails_the_job(
    settings: Settings, hazard_root: Path, report_doc: dict[str, Any]
) -> None:
    failed = dict(report_doc, status="model_review_failed", model_error="timeout", findings=[])
    review = fake_pipeline_run([], report=failed)
    async with await model_client(settings, hazard_root, review) as client:
        job_id = (await client.post("/api/hazards/clips/hz_01/review")).json()["job_id"]
        _, messages = await read_events(client, job_id)
        assert messages[-1]["event"] == "failed"
        assert messages[-1]["data"]["plain_message"] == WORDING["messages"]["model_failed"]
        view = (await client.get("/api/hazards/clips/hz_01")).json()
        validate("HazardView", view)
        assert view["status"] == "failed"
        assert view["technical"]["model_error"] == "timeout"


async def test_missing_source_video_fails(settings: Settings, hazard_root: Path) -> None:
    (hazard_root / "clips" / "hz_01" / "source.mp4").unlink()
    async with await model_client(settings, hazard_root, fake_pipeline_run([], report={})) as c:
        job_id = (await c.post("/api/hazards/clips/hz_01/review")).json()["job_id"]
        _, messages = await read_events(c, job_id)
    assert messages == [
        {"id": "1", "event": "failed", "data": {"plain_message": WORDING["messages"]["no_video"]}}
    ]


async def test_review_errors(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/hazards/clips/hz_99/review")).status_code == 404
    bad = await client.post("/api/hazards/clips/hz_00/review", json={"refresh": True, "x": 1})
    assert bad.status_code == 422
    assert (await client.get("/api/hazards/jobs/hzjob_000000000000/events")).status_code == 404


# --------------------------------------------------------------------------- composer


def compose(report: dict[str, Any] | None, status: str = "reviewed", **kwargs: Any) -> dict:
    clip = {"clip_id": "hz_00", "title": "Press line camera", "duration_s": 12.605}
    return hz.compose_view(clip=clip, report=report, status=status, wording=WORDING, **kwargs)


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        (
            (
                "A large circular metal object is resting on the floor directly across the yellow "
                "painted boundary line of the main aisle. The object remains stationary in sampled "
                "frames (E024, E025)."
            ),
            (
                "A large circular metal object is resting on the floor directly across the yellow "
                "painted boundary line of the main aisle. The object remains stationary in sampled "
                "frames."
            ),
        ),
        (
            (
                "A worker is seated at the controls of a mechanical press. The worker's hands are "
                "positioned near the machine interface, and their head is close to the machinery "
                "opening (E016, E034)."
            ),
            (
                "A worker is seated at the controls of a mechanical press. The worker's hands are "
                "positioned near the machine interface, and their head is close to the machinery "
                "opening."
            ),
        ),
        ("Center of the marked aisle, Z07", "Center of the marked aisle"),
        ("Machine control station, Z03", "Machine control station"),
        (
            (
                "The dark area in Z06 is likely a shadow or surface variation; no liquid spill is "
                "visible."
            ),
            "The dark area is likely a shadow or surface variation; no liquid spill is visible.",
        ),
        (
            (
                "The object in Z07 appears to be a heavy metal component based on its rigidity and "
                "context, not a rubber tire."
            ),
            (
                "The object appears to be a heavy metal component based on its rigidity and context, "
                "not a rubber tire."
            ),
        ),
        ("See E016 for the guard.", "See for the guard."),
        ("Z07 holds a pallet (see E024).", "This area holds a pallet."),
        ("Pallet in zone Z10, near E030 and E031.", "Pallet."),
        ("Zone Z03 shows a worker.", "This area shows a worker."),
    ],
)
def test_strip_ids_on_real_report_text(raw: str, plain: str) -> None:
    assert hz.strip_ids(raw) == plain


def test_plain_text_scrubs_technical_and_legal_words() -> None:
    raw = (
        "Qwen 3.6 flagged a violation (needs_verification) at bbox [553, 0, 658, 155] with "
        "proposal score 0.103; see https://www.osha.gov/x and 4_tr1.mp4, sha256 "
        "1c52395194440a85a49878e400f384251fe6ef2c58d44e444d3d7a6d4b0d60e4. Non-compliant "
        "with OSHA 1910.176(a)."
    )
    text = hz.plain_text(raw)
    assert hz.leaks(text) == []
    for word in ("http", "4_tr1", "1910", "553", "0.103", "score", "Qwen"):
        assert word not in text
    assert text.startswith("The AI flagged a problem (needs a check)")
    assert "not following the safety rules" in text.lower()


def test_clock_and_when_labels() -> None:
    assert hz.clock(0) == "0:00"
    assert hz.clock(12.565026010404162) == "0:12"
    assert hz.clock(75.9) == "1:15"
    assert hz.clock(3725) == "1:02:05"
    assert hz.when_label(0.0, 12.565) == "0:00–0:12 of the clip"
    assert hz.when_label(6.28, 6.9) == "0:06 of the clip"


def test_sentence_case_titles() -> None:
    assert hz.sentence_case("Obstruction in Marked Aisle") == "Obstruction in marked aisle"
    assert hz.sentence_case("Missing PPE Near Press") == "Missing PPE near press"
    assert hz.sentence_case("Worker near press") == "Worker near press"


def test_hazards_sort_highest_priority_first(report_doc: dict[str, Any]) -> None:
    findings = [
        dict(report_doc["findings"][0], severity="low"),
        dict(report_doc["findings"][1], severity="high"),
    ]
    view = compose(dict(report_doc, findings=findings))
    hazards = view["worker"]["hazards"]
    assert [h["priority"] for h in hazards] == ["High", "Low"]
    assert [h["id"] for h in hazards] == ["hazard-2", "hazard-1"]
    summary = hz.summarize_clip(view["clip"], dict(report_doc, findings=findings), "reviewed")
    assert summary["top_priority"] == "high"


def test_zero_hazards_reads_calmly(report_doc: dict[str, Any]) -> None:
    view = compose(dict(report_doc, findings=[]))
    worker = view["worker"]
    assert worker["headline"] == "No hazards seen in this clip"
    assert "This doesn't mean the area is safe." in worker["summary"]
    validate("HazardView", view)


def test_cannot_tell_states_the_video_assumptions(report_doc: dict[str, Any]) -> None:
    cannot_tell = compose(report_doc)["worker"]["cannot_tell"]
    assert cannot_tell[0].startswith("The AI looked at 35 still pictures from the clip, not the")
    assert "The check assumes the camera stays still for the whole clip." in cannot_tell
    # The model's own limitations follow, in plain words; the script's fixed technical
    # limitations ("All frames scanned by CV; Qwen reviewed ...") are not repeated raw.
    assert cannot_tell[-1] == "Energy isolation status of the machine is unknown."
    assert not any("Qwen" in line or "OSHA" in line for line in cannot_tell)


def test_quality_warnings_are_plain_for_worker_and_raw_for_judges(
    report_doc: dict[str, Any],
) -> None:
    warning = (
        "No reliable floor-like mask found; static-zone ranking uses general scene candidates."
    )
    report = dict(report_doc, limitations=[*report_doc["limitations"][:6], warning])
    view = compose(report, manifest={"quality_warnings": [warning]})
    assert view["technical"]["quality_warnings"] == [warning]
    assert (
        "The floor could not be picked out clearly, so blocked walkways are harder to spot."
        in view["worker"]["cannot_tell"]
    )
    assert warning not in view["worker"]["cannot_tell"]


def test_preprocessing_only_is_not_reviewed(report_doc: dict[str, Any]) -> None:
    report = dict(
        report_doc, status="preprocessing_only", request_sha256=None, model={}, findings=[]
    )
    status = hz.derive_status(report)
    assert status == "not_reviewed"
    view = compose(report, status=status)
    validate("HazardView", view)
    assert view["vision"]["images_sent"] == 0 and view["vision"]["shown_images"] == []
    assert view["vision"]["frames_scanned"] == 315 and view["vision"]["areas_marked"] == 10
    assert view["reviewed_at"] is None


def test_wording_file_overrides_and_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "hazards.yaml"
    path.write_text("steps: [One, Two]\npriority_words: {high: Urgent}\nchecks: 5\n", "utf-8")
    wording = hz.load_wording(path)
    assert wording["steps"] == ["One", "Two"]
    assert wording["priority_words"] == {"high": "Urgent", "medium": "Medium", "low": "Low"}
    assert wording["checks"] == hz.DEFAULT_WORDING["checks"]
    assert hz.load_wording(tmp_path / "missing.yaml") == hz.load_wording(tmp_path / "nope.yml")
    (tmp_path / "broken.yaml").write_text("steps: [", "utf-8")
    assert hz.load_wording(tmp_path / "broken.yaml")["steps"] == hz.DEFAULT_WORDING["steps"]


def test_repo_wording_has_every_default_key() -> None:
    """config/hazards.yaml and the in-code fallback carry the same keys and value types
    (the values are editable wording, so only their shape is pinned here)."""
    raw = yaml.safe_load((REPO_ROOT / "config" / "hazards.yaml").read_text("utf-8"))
    assert set(raw) == set(hz.DEFAULT_WORDING)
    for key, default in hz.DEFAULT_WORDING.items():
        assert isinstance(raw[key], type(default)), key
        if isinstance(default, dict):
            assert set(default) <= set(raw[key]), key
    assert len(raw["steps"]) == hz.TOTAL_STEPS == len(hz.SCRIPT_STEPS)


def test_default_steps_are_the_spec_wording() -> None:
    assert hz.DEFAULT_WORDING["steps"] == [
        "Reading the video",
        "Looking for movement",
        "Marking areas to check",
        "Preparing pictures for the AI",
        "AI is reviewing the pictures",
        "Writing the report",
    ]
    assert hz.SCRIPT_STEPS[4] == "[5/6] Running Qwen 3.6 hazard review..."


def test_latest_run_falls_back_to_newest_report(hazard_root: Path, report_doc: dict) -> None:
    (hazard_root / "reports" / "hz_00" / "latest_run.json").write_text("{", "utf-8")
    store = hz.HazardStore(hazard_root)
    assert store.latest_run_dir("hz_00") == (hazard_root / "reports" / "hz_00" / RUN_ID).resolve()
    shutil.rmtree(hazard_root / "reports" / "hz_00")
    assert store.latest_run_dir("hz_00") is None

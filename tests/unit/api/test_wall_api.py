"""GET /api/wall: the home camera wall (factory hazard clips from CAM 1, then warehouse
blind-spot clips numbered on), configured by config/wall.yaml. Factory only: no /ops scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.api.main import create_app
from apps.api.schemas import REPO_ROOT
from apps.api.services import wall as wl
from apps.api.services.hazards import HazardService
from apps.api.settings import Settings

SCHEMA = json.loads((REPO_ROOT / "contracts" / "hazard_view.schema.json").read_text("utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
OPS_WORDS = ("bus", "station", "intersection", "meva", "scenario", "/ops", "withheld")


def validate(doc: Any) -> None:
    ref = {"$ref": f"{SCHEMA['$id']}#/$defs/Wall"}
    Draft202012Validator(ref, registry=REGISTRY).validate(doc)


def write_clip(root: Path, clip_id: str, **extra: Any) -> None:
    clip_dir = root / "clips" / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    doc = {"clip_id": clip_id, "title": f"Camera {clip_id}", "duration_s": 15.0, **extra}
    (clip_dir / "clip.json").write_text(json.dumps(doc), encoding="utf-8")
    (clip_dir / "source.mp4").write_bytes(b"\x00" * 64)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    data = tmp_path / "hazards"
    for clip_id in ("hz_00", "hz_01", "hz_02", "hz_03"):
        write_clip(data, clip_id)
    for clip_id in ("bs_01", "bs_02", "bs_03", "bs_04"):
        write_clip(data, clip_id, kind="blindspot")
    return data


@pytest.fixture(autouse=True)
def _wall_with_blind_spots(request: pytest.FixtureRequest, monkeypatch, tmp_path: Path):
    """The repo config picks the demo clips; the tests below pin the default wall (every
    staged clip, four per row) instead (the repo-config test reads the real file)."""
    if request.node.name == "test_repo_config_matches_the_defaults":
        return
    raw = {**wl.DEFAULT_WALL, "show_blindspot": True}
    path = tmp_path / "wall.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setattr(wl, "DEFAULT_WALL_CONFIG", path)


def test_repo_config_matches_the_defaults() -> None:
    raw = yaml.safe_load((REPO_ROOT / "config" / "wall.yaml").read_text("utf-8"))
    assert set(raw) == set(wl.DEFAULT_WALL)
    # the demo wall: two factory and two warehouse angles, each with a stored run;
    # everything else is the default
    assert raw["hazard_clips"] == ["hz_00", "hz_01"]
    assert raw["blindspot_clips"] == ["bs_01", "bs_02"]
    assert raw["show_blindspot"] is True
    demo = {"hazard_clips": [], "blindspot_clips": []}  # the defaults pick by id
    assert {**wl.load_wall_config(), **demo} == wl.DEFAULT_WALL
    text = (REPO_ROOT / "config" / "wall.yaml").read_text("utf-8").lower()
    for word in OPS_WORDS:
        assert word not in text


def test_default_wall_fills_four_tiles_per_row(root: Path) -> None:
    doc = wl.wall(HazardService(root, profile="fixture"))
    validate(doc)
    assert doc["title"] == "Site cameras · Factory floor"
    assert doc["hazard_title"] == "Hazard watch"
    assert doc["blindspot_title"] == "Blind spot watch · Warehouse"
    assert [t["clip_id"] for t in doc["hazard_tiles"]] == ["hz_00", "hz_01", "hz_02", "hz_03"]
    assert [t["clip_id"] for t in doc["blindspot_tiles"]] == ["bs_01", "bs_02", "bs_03", "bs_04"]
    assert [t["label"] for t in doc["hazard_tiles"] + doc["blindspot_tiles"]] == [
        f"CAM {i}" for i in range(1, 9)
    ]
    assert {t["watch"] for t in doc["hazard_tiles"]} == {"HAZARD WATCH"}
    assert {t["watch"] for t in doc["blindspot_tiles"]} == {"BLIND SPOT"}
    assert [t["check_after_s"] for t in doc["hazard_tiles"]] == [2.0, 4.0, 6.0, 8.0]
    # a fourth tile past the configured times continues 5 s after the last one
    assert [t["check_after_s"] for t in doc["blindspot_tiles"]] == [3.5, 6.5, 9.5, 14.5]
    tile = doc["hazard_tiles"][0]
    assert tile["source_url"] == "/api/hazards/clips/hz_00/media/source.mp4"
    text = json.dumps(doc).lower()
    for word in OPS_WORDS:
        assert word not in text


def test_configured_ids_order_and_skip_unknown_or_wrong_kind(root: Path, tmp_path: Path) -> None:
    config = tmp_path / "wall.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "title": "Site cameras · Plant 2",
                "hazard_clips": ["hz_03", "hz_99", "bs_01", "hz_01"],
                "blindspot_clips": ["bs_04"],
                "hazard_check_after_s": [1, "x", -2],
                "blindspot_check_after_s": "soon",
            }
        ),
        encoding="utf-8",
    )
    doc = wl.wall(HazardService(root, profile="fixture"), config)
    validate(doc)
    assert doc["title"] == "Site cameras · Plant 2"
    assert [t["clip_id"] for t in doc["hazard_tiles"]] == ["hz_03", "hz_01"]
    # Bad numbers are dropped; missing tiles continue 5 s apart.
    assert [t["check_after_s"] for t in doc["hazard_tiles"]] == [1.0, 6.0]
    # two factory tiles, so the warehouse tile is CAM 3 (numbers never skip)
    assert [(t["cam"], t["clip_id"]) for t in doc["blindspot_tiles"]] == [(3, "bs_04")]
    assert doc["blindspot_tiles"][0]["check_after_s"] == 3.5


def test_cam_numbers_continue_across_rows(root: Path, tmp_path: Path) -> None:
    """Three factory tiles plus one warehouse tile read CAM 1-4, not CAM 1-3 then CAM 5."""
    config = tmp_path / "wall.yaml"
    config.write_text(
        yaml.safe_dump({"hazard_clips": ["hz_00", "hz_01", "hz_02"], "blindspot_clips": ["bs_01"]}),
        encoding="utf-8",
    )
    doc = wl.wall(HazardService(root, profile="fixture"), config)
    validate(doc)
    tiles = doc["hazard_tiles"] + doc["blindspot_tiles"]
    assert [(t["cam"], t["label"], t["clip_id"]) for t in tiles] == [
        (1, "CAM 1", "hz_00"),
        (2, "CAM 2", "hz_01"),
        (3, "CAM 3", "hz_02"),
        (4, "CAM 4", "bs_01"),
    ]


def test_four_tiles_per_row_validate(root: Path, tmp_path: Path) -> None:
    config = tmp_path / "wall.yaml"
    config.write_text(
        yaml.safe_dump(
            {"hazard_clips": ["hz_00", "hz_01", "hz_02", "hz_03"], "blindspot_clips": ["bs_01"]}
        ),
        encoding="utf-8",
    )
    doc = wl.wall(HazardService(root, profile="fixture"), config)
    validate(doc)
    assert [t["cam"] for t in doc["hazard_tiles"] + doc["blindspot_tiles"]] == [1, 2, 3, 4, 5]


def test_broken_or_missing_config_uses_defaults(tmp_path: Path) -> None:
    broken = tmp_path / "wall.yaml"
    broken.write_text("title: [", encoding="utf-8")
    assert wl.load_wall_config(broken) == wl.DEFAULT_WALL
    assert wl.load_wall_config(tmp_path / "missing.yaml") == wl.DEFAULT_WALL
    listed = tmp_path / "list.yaml"
    listed.write_text("- a\n- b\n", encoding="utf-8")
    assert wl.load_wall_config(listed) == wl.DEFAULT_WALL


def test_wall_without_blind_spot_clips(tmp_path: Path) -> None:
    data = tmp_path / "hazards"
    write_clip(data, "hz_00")
    doc = wl.wall(HazardService(data, profile="fixture"))
    validate(doc)
    assert [t["cam"] for t in doc["hazard_tiles"]] == [1]
    assert doc["blindspot_tiles"] == []


async def test_route(root: Path, tmp_path: Path) -> None:
    settings = Settings(
        manifests_dir=tmp_path / "m", prepared_dir=tmp_path / "p", runs_dir=tmp_path / "r"
    )
    app = create_app(settings)
    app.state.hazards = HazardService(root, profile="fixture")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/api/wall")
    assert response.status_code == 200
    body = response.json()
    validate(body)
    assert len(body["hazard_tiles"]) == 4 and len(body["blindspot_tiles"]) == 4


def test_tile_fps_comes_from_the_clip(tmp_path: Path) -> None:
    """Tiles pass the clip's frame rate through (the wall shows frame numbers); a missing or
    nonsense rate is null, never a guess."""
    data = tmp_path / "hazards"
    write_clip(data, "hz_00", fps=24.99)
    write_clip(data, "hz_01")
    write_clip(data, "hz_02", fps="fast")
    write_clip(data, "bs_01", kind="blindspot", fps=30)
    doc = wl.wall(HazardService(data, profile="fixture"))
    validate(doc)
    assert [t["fps"] for t in doc["hazard_tiles"]] == [24.99, None, None]
    assert [t["fps"] for t in doc["blindspot_tiles"]] == [30.0]

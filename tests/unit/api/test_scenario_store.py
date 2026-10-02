"""P03: manifest loading/validation and the judge-safe public scenario view."""

from __future__ import annotations

import json
import logging
import os

import pytest

from apps.api.services.scenarios import ScenarioStore


@pytest.fixture
def store(tmp_path, scenario_doc):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "scenario_001.json").write_text(json.dumps(scenario_doc), encoding="utf-8")
    return ScenarioStore(manifests, media_root=tmp_path / "media", prepared_dir=tmp_path / "prep")


def _write(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_loads_valid_and_skips_invalid_with_warning(store, scenario_doc, caplog):
    bad_gt = json.loads(json.dumps(scenario_doc)) | {"id": "bad_gt"}
    bad_gt["ground_truth_camera"]["model_access"] = True
    _write(store.manifests_dir / "bad_gt.json", bad_gt)
    (store.manifests_dir / "not_json.json").write_text("{nope", encoding="utf-8")
    _write(store.manifests_dir / "scenario_001.provenance.json", {"source": "x"})
    with caplog.at_level(logging.WARNING, logger="apps.api.services.scenarios"):
        loaded = store.list()
    assert [s.id for s in loaded] == ["scenario_001"]
    assert sorted(store.invalid) == ["bad_gt.json", "not_json.json"]
    warned = " ".join(r.getMessage() for r in caplog.records)
    assert "bad_gt.json" in warned and "not_json.json" in warned
    assert "provenance" not in warned


def test_duplicate_ids_keep_first_file(store, scenario_doc):
    _write(store.manifests_dir / "zz_copy.json", scenario_doc | {"title": "copy"})
    assert len(store.list()) == 1
    assert store.get("scenario_001").scenario.title == scenario_doc["title"]
    assert store.invalid == ["zz_copy.json"]


def test_reloads_when_manifests_change(store, scenario_doc):
    assert store.get("scenario_002") is None
    _write(store.manifests_dir / "scenario_002.json", scenario_doc | {"id": "scenario_002"})
    assert store.get("scenario_002") is not None
    (store.manifests_dir / "scenario_002.json").unlink()
    assert store.get("scenario_002") is None


def test_missing_manifest_dir_is_empty(tmp_path):
    empty = ScenarioStore(tmp_path / "absent", tmp_path, tmp_path)
    assert empty.list() == [] and empty.get("scenario_001") is None


def test_public_view_has_no_ground_truth(store, scenario_doc):
    scenario_doc["title"] = "Corner (cam_gt is withheld)"
    scenario_doc["coordinate_frame"] = "derived without hidden_ground_truth.mp4"
    scenario_doc["visible_cameras"][0]["label"] = "north pole, faces cam_gt"
    scenario_doc["provenance"] = {
        "source": "MEVA",
        "license": "CC-BY-4.0",
        "note": "GT is data/prepared/scenario_001/hidden_ground_truth.mp4",
        "original_files": {"cam_gt": "hidden_ground_truth.mp4"},
        "offsets": [1, 2],
        "dataset": 2024,  # whitelisted key, non-string value: dropped
    }
    _write(store.manifests_dir / "scenario_001.json", scenario_doc)
    view = store.public_view(store.get("scenario_001"))
    text = json.dumps(view)
    for token in ("cam_gt", "hidden_ground_truth", "ground_truth_camera"):
        assert token not in text
    assert view["has_ground_truth"] is True
    assert view["provenance"] == {
        "source": "MEVA",
        "license": "CC-BY-4.0",
        "note": "GT is [withheld]",
    }
    assert [c["id"] for c in view["cameras"]] == ["cam_01", "cam_02", "cam_03"]
    assert view["cameras"][0]["media_url"] == "/media/scenarios/scenario_001/cameras/cam_01"
    assert view["cameras"][0]["media_available"] is False
    assert [z["id"] for z in view["zones"]] == ["blind_zone_01", "blind_zone_02"]


def test_public_provenance_is_always_an_object(store, scenario_doc):
    scenario_doc.pop("provenance", None)
    _write(store.manifests_dir / "scenario_001.json", scenario_doc)
    loaded = store.get("scenario_001")
    assert store.public_view(loaded)["provenance"] == {}
    assert store.judge_view(loaded)["provenance"] == {}


def test_media_paths_resolve_against_media_root(store, tmp_path):
    loaded = store.get("scenario_001")
    cam = loaded.scenario.visible_cameras[0]
    assert store.media_path(cam) == tmp_path / "media" / cam.file
    absolute = cam.model_copy(update={"file": str(tmp_path / "abs.mp4")})
    assert store.media_path(absolute) == tmp_path / "abs.mp4"
    target = store.media_path(cam)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"test media")
    assert store.public_view(loaded)["cameras"][0]["media_available"] is True


def test_judge_view_carries_ground_truth_and_expected(store):
    loaded = store.get("scenario_001")
    judge = store.judge_view(loaded)
    assert judge["judge_only"] is True
    assert judge["ground_truth_camera"]["id"] == "cam_gt"
    assert "file" not in judge["ground_truth_camera"]
    assert judge["expected"] is None
    expected_path = store.expected_path("scenario_001")
    expected_path.parent.mkdir(parents=True)
    _write(expected_path, {"event_type": "x", "region": "blind_zone_02"})
    assert store.judge_view(loaded)["expected"] == {"event_type": "x", "region": "blind_zone_02"}


def test_signature_ignores_unchanged_files(store):
    store.list()
    first = store._items
    os.utime(store.manifests_dir)  # directory touch alone is not a manifest change
    store.list()
    assert store._items is first

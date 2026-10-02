#!/usr/bin/env python3
"""Cut prepared scenarios from synchronized MEVA clips.

For every spec in --specs (default scripts/data/scenario_specs.json):
  1. resolve the camera clips for the slot and their scenario-time offsets
     (same sync logic as find_candidates.py);
  2. trim each camera to [start_s, start_s + duration_s] in scenario time and
     transcode to H.264/yuv420p/faststart, no audio, <= 1280 px wide, so all
     prepared files share t = 0 (time_offset_s = 0, residual sync recorded);
  3. derive camera position/heading/FOV from the MEVA KRTD calibration in a
     local metric frame (ENU minus a fixed site origin);
  4. write data/manifests/<id>.json (validated against
     contracts/scenario.schema.json) and the judge-only
     data/prepared/<id>/expected.json, whose labels come from the MEVA
     annotations (or "none" for negatives) and are never invented here;
  5. save a small evidence contact sheet of all four views at the labeled times.

Usage:
  python scripts/data/prepare_scenario.py --raw-dir ~/aum-data/raw [--only scenario_001]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_candidates import (
    COARSE_CLASS,
    IMG_H,
    IMG_W,
    directly_visible,
    load_meva_group,
    locate_events,
)
from meva_geometry import GroundModel, camera_summary, read_ply_vertices

REPO = Path(__file__).resolve().parents[2]
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
VISIBLE_FILES = ("cam_a", "cam_b", "cam_c", "cam_d", "cam_e")

MEVA_PROVENANCE = {
    "dataset": "MEVA (Multiview Extended Video with Activities), KF1 release drops-123-r13",
    "dataset_url": "https://mevadata.org/",
    "video_source": "https://mevadata-public-01.s3.amazonaws.com/drops-123-r13/ (public, no registration)",
    "annotation_source": "https://gitlab.kitware.com/meva/meva-data-repo (annotation/DIVA-phase-2/MEVA/kitware*)",
    "calibration_source": "meva-data-repo metadata/camera-models/krtd + metadata/meva-clip-camera-and-time-table.txt",
    "ground_model_source": "https://mevadata-public-01.s3.amazonaws.com/mutc-3d-model/model_segmentations/coarse/background.ply",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": (
        "'Multiview Extended Video with Activities' (MEVA) dataset by Kitware Inc. and the "
        "Intelligence Advanced Research Projects Activity (IARPA) is licensed under a Creative "
        "Commons Attribution 4.0 International License."
    ),
    "modifications": "Trimmed to a short window, scaled to 1280 px wide, re-encoded H.264, audio removed.",
}

# Event classes a hypothesis may use and still count as correct, per coarse class.
ACCEPTED = {
    "vehicle_turnaround": [
        "vehicle_turnaround",
        "vehicle_reversing",
        "u_turn",
        "vehicle_maneuver",
        "traffic_obstruction",
        "vehicle_activity",
    ],
    "passenger_dropoff_pickup": [
        "passenger_dropoff_pickup",
        "vehicle_stop",
        "stopped_vehicle",
        "vehicle_activity",
        "traffic_obstruction",
        "pedestrian_activity",
    ],
    "vehicle_stop": ["vehicle_stop", "stopped_vehicle", "traffic_obstruction", "vehicle_activity"],
    "vehicle_departure": ["vehicle_departure", "vehicle_activity", "vehicle_maneuver"],
    "vehicle_turn": ["vehicle_turn", "vehicle_maneuver", "vehicle_activity"],
    "vehicle_loading_unloading": [
        "vehicle_loading_unloading",
        "stopped_vehicle",
        "vehicle_activity",
        "pedestrian_activity",
    ],
    "object_transport": ["object_transport", "pedestrian_activity"],
    "none": ["unknown", "none", "no_event"],
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def transcode(src: Path, dst: Path, ss: float, duration: float, max_width: int, crf: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{ss:.3f}",
            "-i",
            str(src),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"scale='min({max_width},iw)':-2:flags=lanczos,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-profile:v",
            "high",
            "-movflags",
            "+faststart",
            "-map_metadata",
            "-1",
            str(dst),
        ]
    )


def probe(path: Path) -> dict:
    out = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames,codec_name,pix_fmt:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    j = json.loads(out.stdout)
    s, f = j["streams"][0], j["format"]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return {
        "width": s["width"],
        "height": s["height"],
        "fps": round(num / den, 3),
        "codec": s["codec_name"],
        "pix_fmt": s["pix_fmt"],
        "duration_s": round(float(f["duration"]), 3),
        "bytes": int(f["size"]),
    }


def grab(path: Path, t: float, width: int = 480) -> np.ndarray:
    out = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-ss",
            f"{max(t, 0):.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    return img if img is not None else np.zeros((270, width, 3), np.uint8)


def contact_sheet(files: list[tuple[str, Path]], times: list[float], dest: Path) -> None:
    rows = []
    for t in times:
        tiles = []
        for name, p in files:
            im = grab(p, t)
            cv2.putText(
                im, f"{name} t={t:.1f}s", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3
            )
            cv2.putText(
                im, f"{name} t={t:.1f}s", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1
            )
            tiles.append(im)
        h = min(x.shape[0] for x in tiles)
        rows.append(np.hstack([x[:h] for x in tiles]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 72])


def local_xy(enu: list[float] | np.ndarray, origin: list[float]) -> list[float]:
    return [round(float(enu[0]) - origin[0], 1), round(float(enu[1]) - origin[1], 1)]


def nearest_zone(xy: list[float], zones: list[dict]) -> dict | None:
    best = min(zones, key=lambda z: math.dist(z["center"], xy)) if zones else None
    return best if best and math.dist(best["center"], xy) <= best["radius_m"] else None


def build(spec: dict, site: dict, args: argparse.Namespace, ground: GroundModel | None) -> dict:
    raw = Path(args.raw_dir).expanduser()
    repo = Path(args.repo_dir).expanduser() if args.repo_dir else raw / "meva-data-repo"
    sid, slot, gt, visible = spec["id"], spec["slot"], spec["gt"], spec["visible"]
    clips = load_meva_group(raw, repo, slot, [gt] + visible)
    by = {c.camera: c for c in clips}
    missing = [c for c in [gt] + visible if c not in by or by[c].video is None]
    if missing:
        raise SystemExit(f"{sid}: missing clip/video for {missing}; run fetch_meva.py clips first")
    for c in clips:
        locate_events(c, ground)
    start, dur = float(spec["start_s"]), float(spec["duration_s"])
    origin = site["origin_enu"]
    zones = site["zones"]
    out_dir = REPO / "data" / "prepared" / sid
    names = {gt: "hidden_ground_truth"} | {v: VISIBLE_FILES[i] for i, v in enumerate(visible)}
    ids = {gt: "cam_gt"} | {v: f"cam_{chr(ord('a') + i)}" for i, v in enumerate(visible)}

    cams, prov_files, media = {}, [], {}
    for cam_id in [gt] + visible:
        c = by[cam_id]
        ss = start - c.t0
        if ss < 0 or ss + dur > 300.5:
            raise SystemExit(f"{sid}: window outside {cam_id} clip (ss={ss:.2f})")
        dst = out_dir / f"{names[cam_id]}.mp4"
        if args.force or not dst.exists():
            transcode(c.video, dst, ss, dur, args.max_width, args.crf)
        media[cam_id] = probe(dst)
        summ = camera_summary(c.krtd, IMG_W, IMG_H, ground)
        cams[cam_id] = {
            "id": ids[cam_id],
            "file": f"data/prepared/{sid}/{names[cam_id]}.mp4",
            "model_access": cam_id != gt,
            "label": site["camera_labels"].get(cam_id, cam_id),
            "position": local_xy(summ["position_enu_m"], origin),
            "heading_deg": summ["heading_deg"],
            "fov_deg": summ["fov_deg"],
            "time_offset_s": 0.0,
        }
        prov_files.append(
            {
                "camera_id": ids[cam_id],
                "meva_camera": cam_id,
                "source_clip": f"{c.clip}.r13.avi",
                "source_url": f"https://mevadata-public-01.s3.amazonaws.com/drops-123-r13/"
                f"{c.clip[:10]}/{c.clip.split('.')[1][:2]}/{c.clip}.r13.avi",
                "clip_t0_scenario_s": round(c.t0, 3),
                "trim_start_in_source_s": round(ss, 3),
                "trim_duration_s": dur,
                "sync_method": c.sync,
                "sync_uncertainty_s": round(c.sync_uncertainty_s, 3),
                "camera_height_above_ground_m": summ["height_above_ground_m"],
                "pitch_deg": summ["pitch_deg"],
                "position_enu_m": summ["position_enu_m"],
                "prepared_media": media[cam_id],
            }
        )
    # Fixed zone list for the whole camera configuration (identical across scenarios).
    manifest = {
        "id": sid,
        "title": spec["title"],
        "duration_seconds": dur,
        "coordinate_frame": (
            f"Local metric frame: x = east m, y = north m, origin = MEVA ENU {origin} (ENU origin lat 39.04977294, "
            "lon -85.52924953). Positions/headings/FOV from MEVA KRTD calibrations (K,R,T,D); heading = compass "
            "bearing of the optical axis, fov = horizontal FOV at 1920 px. Uncertainty: calibration registered to "
            "the MEVA 3-D site model, expect ~1-3 m position and ~1-2 deg heading error; event points mapped to "
            "the coarse ground mesh, expect ~2-5 m at 30-60 m range."
        ),
        "visible_cameras": [cams[v] for v in visible],
        "ground_truth_camera": cams[gt],
        "zones": zones,
        "provenance": {
            **MEVA_PROVENANCE,
            "slot": slot,
            "window_scenario_s": [start, start + dur],
            "scenario_time_zero_wallclock": spec.get("wallclock_t0"),
            "files": prov_files,
            "selection": (
                "Window chosen from scripts/data/find_candidates.py output using MEVA annotations; "
                "category and label are judge-only (data/prepared/<id>/expected.json)."
            ),
        },
    }
    manifest["provenance"]["scenario_time_zero_wallclock"] = _wallclock(slot, start)

    # ---------------------------------------------------------------- judge-only expected labels
    label = spec["label"]
    expected = {
        "scenario_id": sid,
        "judge_only": True,
        "category": spec["category"],
        "label_method": label["method"],
        "notes": spec.get("notes", ""),
    }
    if label.get("gt_act_ids"):
        evs = [e for e in by[gt].events if e["act_id"] in label["gt_act_ids"]]
        if len(evs) != len(label["gt_act_ids"]):
            raise SystemExit(
                f"{sid}: GT activity ids {label['gt_act_ids']} not all found in {by[gt].clip}"
            )
        evs.sort(key=lambda e: e["t_start"])
        primary = evs[0]
        pts = [e["ground_xy"] for e in evs if e["ground_xy"]]
        cxy = [float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))]
        loc = local_xy(cxy, origin)
        zone = nearest_zone(loc, zones)
        coarse = COARSE_CLASS.get(primary["label"], "other_activity")
        coarse = label.get("event_type", coarse)
        direct = {}
        for v in visible:
            vis = [directly_visible(e, by[v]) for e in evs]
            direct[ids[v]] = {
                "visible": any(d for d, _ in vis),
                "why": "; ".join(w for _, w in vis),
            }
        cues = []
        for v in visible:
            for o in by[v].events:
                if o["ground_xy"] is None:
                    continue
                d = min(math.dist(o["ground_xy"], p) for p in pts)
                if (
                    o["t_end"] >= start
                    and o["t_start"] <= start + dur
                    and d <= label.get("cue_radius_m", 30.0)
                ):
                    cues.append(
                        {
                            "camera_id": ids[v],
                            "dataset_label": o["label"],
                            "t_start": round(o["t_start"] - start, 2),
                            "t_end": round(o["t_end"] - start, 2),
                            "distance_to_event_m": round(d, 1),
                            "source": "MEVA annotation (visible camera)",
                        }
                    )
        cues.sort(key=lambda c: c["t_start"])
        expected.update(
            {
                "event_type": coarse,
                "accepted_event_types": ACCEPTED.get(coarse, [coarse]),
                "dataset_event_labels": sorted({e["label"] for e in evs}),
                "abstention_acceptable": spec["category"] != "positive",
                # Clamped to the clip; the full dataset span is kept per activity in derivation.
                "time_window": {
                    "start_s": round(max(0.0, min(e["t_start"] for e in evs) - start), 2),
                    "end_s": round(min(dur, max(e["t_end"] for e in evs) - start), 2),
                    "clamped_to_clip": (
                        min(e["t_start"] for e in evs) < start
                        or max(e["t_end"] for e in evs) > start + dur
                    ),
                },
                "region": {
                    "zone_id": zone["id"] if zone else None,
                    "accepted_zone_ids": label.get("accepted_zones", [zone["id"]] if zone else []),
                    "event_point_local_m": loc,
                    "uncertainty_m": 5.0,
                },
                "direct_visibility": direct,
                "indirect_cues": cues,
                "indirect_cues_note": (
                    "Every MEVA-annotated activity in a visible camera that overlaps the window and "
                    f"maps within {label.get('cue_radius_m', 30.0):g} m of the event point. "
                    "Concurrency only: not a claim that the activity was caused by the event."
                ),
                "derivation": {
                    "method": "MEVA kitware activity annotations in the GT camera clip; event point = bottom-center "
                    "of the first actor's box at mid-activity, ray-cast onto the MEVA coarse ground mesh",
                    "gt_clip": by[gt].clip,
                    "gt_activities": [
                        {
                            "act_id": e["act_id"],
                            "label": e["label"],
                            "actor_ids": e["actor_ids"],
                            "actor_kind": e["actor_kind"],
                            "frames": [e["start_frame"], e["end_frame"]],
                            "t_scenario_s": [
                                round(e["t_start"] - start, 2),
                                round(e["t_end"] - start, 2),
                            ],
                            "ground_xy_local_m": local_xy(e["ground_xy"], origin)
                            if e["ground_xy"]
                            else None,
                        }
                        for e in evs
                    ],
                    "visibility_test": "projection of the event point (+0/1/1.6 m) into each visible camera's KRTD "
                    "model, plus same-kind co-annotation within 3 s / 10 m",
                },
            }
        )
        sheet_times = [
            max(0.0, expected["time_window"]["start_s"]),
            min(
                dur - 0.1,
                (expected["time_window"]["start_s"] + expected["time_window"]["end_s"]) / 2,
            ),
            min(dur - 0.1, expected["time_window"]["end_s"]),
        ]
    else:
        # Negative: GT camera has no salient annotated activity near the configured zones in the window.
        gt_acts = [e for e in by[gt].events if e["t_end"] >= start and e["t_start"] <= start + dur]
        expected.update(
            {
                "event_type": "none",
                "accepted_event_types": ACCEPTED["none"],
                "dataset_event_labels": [],
                "abstention_acceptable": True,
                "time_window": None,
                "region": {"zone_id": None, "accepted_zone_ids": [], "event_point_local_m": None},
                "direct_visibility": {},
                "indirect_cues": [],
                "derivation": {
                    "method": label.get(
                        "why", "No salient MEVA-annotated activity in the GT camera in this window."
                    ),
                    "gt_clip": by[gt].clip,
                    "gt_activities_in_window": [
                        {
                            "label": e["label"],
                            "t_scenario_s": [
                                round(e["t_start"] - start, 2),
                                round(e["t_end"] - start, 2),
                            ],
                            "ground_xy_local_m": local_xy(e["ground_xy"], origin)
                            if e["ground_xy"]
                            else None,
                        }
                        for e in gt_acts
                    ],
                },
            }
        )
        sheet_times = [dur * 0.2, dur * 0.5, dur * 0.8]
    if label["method"] == "inspection-labeled" or spec.get("inspection"):
        expected["inspection"] = spec.get("inspection")
    sheet = out_dir / "evidence" / "contact_sheet.jpg"
    contact_sheet(
        [(ids[v], out_dir / f"{names[v]}.mp4") for v in visible]
        + [("cam_gt", out_dir / "hidden_ground_truth.mp4")],
        [round(t, 2) for t in sheet_times],
        sheet,
    )
    expected["evidence_frames"] = {
        "contact_sheet": f"data/prepared/{sid}/evidence/contact_sheet.jpg",
        "rows_t_s": [round(t, 2) for t in sheet_times],
        "columns": [ids[v] for v in visible] + ["cam_gt"],
    }
    (out_dir / "expected.json").write_text(json.dumps(expected, indent=2))
    mpath = REPO / "data" / "manifests" / f"{sid}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2))
    return manifest


def _wallclock(slot: str, start_s: float) -> str:
    from datetime import datetime, timedelta

    return (datetime.strptime(slot, "%Y-%m-%d.%H-%M-%S") + timedelta(seconds=start_s)).isoformat()


def validate(manifest: dict) -> list[str]:
    import jsonschema

    schema = json.loads((REPO / "contracts" / "scenario.schema.json").read_text())
    errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(manifest)]
    try:
        sys.path.insert(0, str(REPO))
        from apps.api.schemas.scenario import Scenario  # optional second check (pydantic mirror)

        Scenario.model_validate(manifest)
    except ImportError:
        pass
    except (ValueError, PermissionError) as exc:  # ValidationError, GroundTruthAccessError
        errors.append(f"pydantic: {exc}")
    for cam in manifest["visible_cameras"] + [manifest["ground_truth_camera"]]:
        if not (REPO / cam["file"]).exists():
            errors.append(f"missing media {cam['file']}")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--repo-dir", default=None)
    ap.add_argument("--specs", default=str(Path(__file__).resolve().parent / "scenario_specs.json"))
    ap.add_argument("--only", default=None, help="comma list of scenario ids")
    ap.add_argument("--max-width", type=int, default=1280)
    ap.add_argument("--crf", type=int, default=26)
    ap.add_argument("--force", action="store_true", help="re-transcode even if the mp4 exists")
    args = ap.parse_args()
    specs = json.loads(Path(args.specs).read_text())
    ply = Path(args.raw_dir).expanduser() / "meva" / "ground_background_coarse.ply"
    ground = GroundModel(read_ply_vertices(ply)) if ply.exists() else None
    only = set(args.only.split(",")) if args.only else None
    ok = 0
    for spec in specs["scenarios"]:
        if only and spec["id"] not in only:
            continue
        site = specs["sites"][spec["site"]]
        manifest = build(spec, site, args, ground)
        errs = validate(manifest)
        status = "VALID" if not errs else "INVALID: " + "; ".join(errs)
        ok += not errs
        print(f"{spec['id']}: {status}", flush=True)
    print(f"{ok} valid manifests")


if __name__ == "__main__":
    main()

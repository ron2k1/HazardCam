#!/usr/bin/env python3
"""Rank candidate blind-zone windows in synchronized multi-camera footage.

Two signals, both CPU-only:

1. Annotation signal (preferred, MEVA mode). Every annotated activity in the
   designated ground-truth (GT) camera is located on the ground (KRTD camera
   model + 3-D ground mesh), then tested against each visible camera:
   - direct visibility: the ground point (and 1 m above it) projects inside the
     visible camera's image, OR the visible camera annotates an activity of the
     same actor kind within +/-3 s and 10 m (the same event seen twice);
   - indirect cues: annotated activities in visible cameras overlapping the
     event window (+/- cue tolerance) within cue radius of the event point.
   A positive candidate is salient, directly visible to no visible camera and
   has cues in as many visible cameras as possible.

2. Motion signal (confirmation, and the only signal in generic mode). ffmpeg
   samples each video at ~2 fps; grayscale frame-difference energy is robust-z
   normalized per camera; windows are ranked where one camera spikes and the
   others change within a tolerance. Pairwise best cross-correlation lags are
   reported as a sync sanity check.

Usage (MEVA):
  python scripts/data/find_candidates.py --raw-dir ~/aum-data/raw \
      --slots 2018-03-15.15-35-00 --gt G341 --visible G506,G340,G436
Usage (generic, any folder of already-aligned videos; motion only):
  python scripts/data/find_candidates.py --scenario-dir data/prepared/scenario_001
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meva_annotations import (
    index_annotations,
    load_activities,
    load_clip_table,
    load_geom,
    load_types,
    parse_clip_name,
    sibling,
)
from meva_geometry import (
    GroundModel,
    in_view,
    load_krtd,
    pixel_to_ground,
    read_ply_vertices,
)
from motion_energy import Timeline, best_lag, resample, timeline_for

REPO_ROOT = Path(__file__).resolve().parents[2]
MEVA_FPS = 30.0
IMG_W, IMG_H = 1920, 1080
FILENAME_SYNC_UNCERTAINTY_S = 1.0

# Salience of MEVA activity labels as a blind-zone "event" (0 = not an event worth hiding).
SALIENCE = {
    "vehicle_makes_u_turn": 3.0,
    "vehicle_reverses": 3.0,
    "person_abandons_package": 3.0,
    "person_steals_object": 3.0,
    "vehicle_drops_off_person": 2.5,
    "vehicle_picks_up_person": 2.5,
    "person_unloads_vehicle": 2.0,
    "person_loads_vehicle": 2.0,
    "vehicle_stops": 2.0,
    "vehicle_starts": 1.5,
    "vehicle_turns_left": 1.5,
    "vehicle_turns_right": 1.5,
    "person_carries_heavy_object": 1.5,
    "person_rides_bicycle": 1.5,
    "person_exits_vehicle": 1.0,
    "person_enters_vehicle": 1.0,
    "person_opens_trunk": 1.0,
    "person_closes_trunk": 1.0,
    "person_embraces_person": 1.0,
    "person_transfers_object": 1.0,
}

# Coarse, judge-facing event classes for each MEVA label (used by expected.json).
COARSE_CLASS = {
    "vehicle_makes_u_turn": "vehicle_turnaround",
    "vehicle_reverses": "vehicle_turnaround",
    "vehicle_stops": "vehicle_stop",
    "vehicle_starts": "vehicle_departure",
    "vehicle_turns_left": "vehicle_turn",
    "vehicle_turns_right": "vehicle_turn",
    "vehicle_drops_off_person": "passenger_dropoff_pickup",
    "vehicle_picks_up_person": "passenger_dropoff_pickup",
    "person_exits_vehicle": "passenger_dropoff_pickup",
    "person_enters_vehicle": "passenger_dropoff_pickup",
    "person_unloads_vehicle": "vehicle_loading_unloading",
    "person_loads_vehicle": "vehicle_loading_unloading",
    "person_opens_trunk": "vehicle_loading_unloading",
    "person_closes_trunk": "vehicle_loading_unloading",
    "person_abandons_package": "object_left_behind",
    "person_steals_object": "object_taken",
    "person_carries_heavy_object": "object_transport",
    "person_rides_bicycle": "cyclist_movement",
}


@dataclass
class CamClip:
    camera: str
    clip: str
    t0: float  # scenario time (s since slot reference) of frame 0
    sync: str  # how t0 was derived
    sync_uncertainty_s: float
    krtd: object | None = None
    activities_path: Path | None = None
    video: Path | None = None
    timeline: Timeline | None = None
    events: list[dict] = field(default_factory=list)


# ----------------------------------------------------------------------------- MEVA loading


def find_video(raw_dir: Path, clip: str) -> Path | None:
    for p in (
        raw_dir / "meva" / "video" / f"{clip}.r13.avi",
        raw_dir / "meva" / "video" / f"{clip}.avi",
    ):
        if p.exists():
            return p
    return None


def load_meva_group(raw_dir: Path, repo: Path, slot: str, cameras: list[str]) -> list[CamClip]:
    """One clip per camera for a reference slot, with scenario-time offsets.

    t0 comes from the wall-clock start in the clip name (1 s resolution). When a
    clip's camera-set reference clip is also in the group, t0 is re-derived from
    the clip-table frame offset instead.

    Sign of the offset: metadata/clip-table-readme.md says frame f of clip A is
    frame f + offset of its reference B, i.e. t0_A = t0_B + offset/30. The data
    says the opposite. With t0_A = t0_B - offset/30 every exterior clip we use
    agrees with its own filename start to the second (e.g. 2018-03-15.15-00
    G341 "15-00-06", offset -180 vs G336 "15-00-00" -> +6 s). The README sign
    gives 12 s disagreements and makes a car leave G436 after it reaches G341
    in scenario_001. So we use the minus sign, and the residual uncertainty is
    the table's own precision (30 frames = 1 s).
    """
    table = load_clip_table(repo)
    ann = index_annotations(repo)
    ref = datetime.strptime(slot, "%Y-%m-%d.%H-%M-%S")
    chosen: dict[str, str] = {}
    for clip, row in table.items():
        cn = parse_clip_name(clip)
        if row.slot == slot and cn.camera in cameras:
            # prefer the longest clip of that camera in the slot
            prev = chosen.get(cn.camera)
            if prev is None or (cn.end_dt - cn.start_dt) > (
                parse_clip_name(prev).end_dt - parse_clip_name(prev).start_dt
            ):
                chosen[cn.camera] = clip
    out: dict[str, CamClip] = {}
    for cam in cameras:
        clip = chosen.get(cam)
        if clip is None:
            continue
        cn = parse_clip_name(clip)
        row = table[clip]
        t0 = (cn.start_dt - ref).total_seconds()
        out[cam] = CamClip(
            camera=cam,
            clip=clip,
            t0=t0,
            sync="filename wall-clock start (1 s resolution)",
            sync_uncertainty_s=FILENAME_SYNC_UNCERTAINTY_S,
            krtd=load_krtd(repo / "metadata" / "camera-models" / "krtd" / row.krtd)
            if row.krtd
            else None,
            activities_path=ann.get(clip),
            video=find_video(raw_dir, clip),
        )
    by_clip = {c.clip: c for c in out.values()}
    for c in out.values():
        row = table[c.clip]
        if (
            row.ref_clip
            and row.ref_clip != c.clip
            and row.ref_clip in by_clip
            and row.ref_precision_frames >= 0
        ):
            r = by_clip[row.ref_clip]
            c.t0 = r.t0 - row.ref_offset_frames / MEVA_FPS
            c.sync = f"clip-table frame offset {row.ref_offset_frames} vs {r.camera} (camera set {row.camera_set})"
            c.sync_uncertainty_s = max(row.ref_precision_frames, 1) / MEVA_FPS
    return [out[c] for c in cameras if c in out]


def locate_events(c: CamClip, ground: GroundModel | None) -> None:
    """Fill c.events with every annotated activity, its scenario time and ground point."""
    if c.activities_path is None:
        return
    acts = load_activities(c.activities_path)
    types = load_types(sibling(c.activities_path, "types"))
    need = {a.actors[0] for a in acts if a.actors}
    geom = load_geom(sibling(c.activities_path, "geom"), need) if need else {}
    for a in acts:
        ev = {
            "camera": c.camera,
            "clip": c.clip,
            "label": a.label,
            "act_id": a.act_id,
            "start_frame": a.start_frame,
            "end_frame": a.end_frame,
            "t_start": round(c.t0 + a.start_frame / MEVA_FPS, 2),
            "t_end": round(c.t0 + a.end_frame / MEVA_FPS, 2),
            "actor_ids": a.actors,
            "actor_kind": types.get(a.actors[0], "unknown") if a.actors else "unknown",
            "ground_xy": None,
            "box": None,
        }
        boxes = geom.get(a.actors[0], {}) if a.actors else {}
        if boxes and c.krtd is not None:
            mid = (a.start_frame + a.end_frame) // 2
            f = min(boxes, key=lambda k: abs(k - mid))
            x1, y1, x2, y2 = boxes[f]
            p = pixel_to_ground(c.krtd, (x1 + x2) / 2.0, y2, ground)
            ev["box"] = {"frame": f, "xyxy": [x1, y1, x2, y2]}
            if p is not None:
                ev["ground_xyz"] = [round(float(v), 2) for v in p]
                ev["ground_xy"] = ev["ground_xyz"][:2]
        c.events.append(ev)


def directly_visible(ev: dict, vis: CamClip) -> tuple[bool, str]:
    if ev.get("ground_xyz") is None or vis.krtd is None:
        return False, "unknown (no geometry)"
    p = np.array(ev["ground_xyz"])
    for dz in (0.0, 1.0, 1.6):
        if in_view(vis.krtd, p + np.array([0, 0, dz]), IMG_W, IMG_H):
            return True, f"ground point +{dz} m projects inside the image"
    for o in vis.events:
        if o["ground_xy"] is None or o["actor_kind"] != ev["actor_kind"]:
            continue
        if (
            abs(o["t_start"] - ev["t_start"]) <= 3.0
            and math.dist(o["ground_xy"], ev["ground_xy"]) <= 10.0
        ):
            return True, f"co-annotated {o['label']} at {o['t_start']}s"
    return False, "outside image and no co-annotation"


def annotation_candidates(
    gt: CamClip, visible: list[CamClip], slot: str, cue_tol_s: float, cue_radius_m: float
) -> list[dict]:
    out = []
    for ev in gt.events:
        sal = SALIENCE.get(ev["label"], 0.0)
        if sal == 0 or ev["ground_xy"] is None:
            continue
        direct, cues = {}, {}
        for v in visible:
            d, why = directly_visible(ev, v)
            direct[v.camera] = {"visible": d, "why": why}
            near = [
                o
                for o in v.events
                if o["ground_xy"] is not None
                and o["t_start"] <= ev["t_end"] + cue_tol_s
                and o["t_end"] >= ev["t_start"] - cue_tol_s
                and math.dist(o["ground_xy"], ev["ground_xy"]) <= cue_radius_m
            ]
            cues[v.camera] = [
                {
                    "label": o["label"],
                    "t_start": o["t_start"],
                    "t_end": o["t_end"],
                    "dist_m": round(math.dist(o["ground_xy"], ev["ground_xy"]), 1),
                }
                for o in near
            ]
        n_direct = sum(1 for d in direct.values() if d["visible"])
        n_cue_cams = sum(1 for v in cues.values() if v)
        score = (
            sal
            + 1.0 * n_cue_cams
            + 0.25 * min(sum(len(v) for v in cues.values()), 8)
            - 3.0 * n_direct
        )
        out.append(
            {
                "slot": slot,
                "gt_camera": gt.camera,
                **{
                    k: ev[k]
                    for k in (
                        "label",
                        "clip",
                        "act_id",
                        "actor_ids",
                        "actor_kind",
                        "t_start",
                        "t_end",
                        "ground_xy",
                        "box",
                        "start_frame",
                        "end_frame",
                    )
                },
                "coarse_class": COARSE_CLASS.get(ev["label"], "other_activity"),
                "blind": n_direct == 0,
                "direct_visibility": direct,
                "cues": cues,
                "n_cue_cameras": n_cue_cams,
                "score": round(score, 2),
            }
        )
    return out


# ----------------------------------------------------------------------------- motion


def compute_timelines(clips: list[CamClip], fps: float, cache_dir: Path | None) -> None:
    for c in clips:
        if c.video is None:
            continue
        cache = cache_dir / f"{c.video.stem}.fps{fps:g}.npy" if cache_dir else None
        if cache is not None and cache.exists():
            c.timeline = Timeline(c.camera, fps, c.t0, np.load(cache))
            continue
        c.timeline = timeline_for(c.video, c.camera, fps, t0=c.t0)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, c.timeline.energy)


def motion_candidates(
    clips: list[CamClip],
    fps: float,
    window_s: float,
    tol_s: float,
    primary_z: float,
    secondary_z: float,
    top: int,
) -> tuple[list[dict], list[dict]]:
    tls = [c.timeline for c in clips if c.timeline is not None and len(c.timeline.energy) > 4]
    if len(tls) < 2:
        return [], []
    start = max(t.t0 for t in tls)
    end = min(t.t0 + len(t.energy) / t.fps for t in tls)
    grid = np.arange(start, end, 1.0 / fps)
    Z = {t.camera: resample(t, grid) for t in tls}
    lags = []
    names = list(Z)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            lag, r = best_lag(Z[names[i]], Z[names[j]], round(tol_s * fps) * 2)
            lags.append(
                {
                    "a": names[i],
                    "b": names[j],
                    "best_lag_s": round(lag / fps, 2),
                    "ncc": round(r, 3),
                }
            )
    cands = []
    step = max(1, round(window_s * fps / 2))
    win = max(1, round(window_s * fps))
    tol = round(tol_s * fps)
    for s in range(0, len(grid) - win, step):
        for cam in names:
            seg = Z[cam][s : s + win]
            if np.all(np.isnan(seg)):
                continue
            p = float(np.nanmax(seg))
            if p < primary_z:
                continue
            sec = {}
            for other in names:
                if other == cam:
                    continue
                o = Z[other][max(0, s - tol) : s + win + tol]
                sec[other] = round(float(np.nanmax(o)), 2) if not np.all(np.isnan(o)) else None
            vals = sorted((v for v in sec.values() if v is not None), reverse=True)
            n_sec = sum(1 for v in vals if v >= secondary_z)
            score = min(p, 12.0) + 0.5 * sum(min(max(v, 0.0), 12.0) for v in vals[:3])
            cands.append(
                {
                    "t_start": round(float(grid[s]), 2),
                    "t_end": round(float(grid[s] + window_s), 2),
                    "primary_camera": cam,
                    "primary_z": round(p, 2),
                    "secondary_z": sec,
                    "n_secondary_over_threshold": n_sec,
                    "score": round(score, 2),
                }
            )
    cands.sort(key=lambda c: -c["score"])
    kept: list[dict] = []
    for c in cands:  # non-maximum suppression in time
        if all(abs(c["t_start"] - k["t_start"]) >= window_s * 2 for k in kept):
            kept.append(c)
        if len(kept) >= top:
            break
    return kept, lags


def attach_motion(cands: list[dict], clips: list[CamClip], tol_s: float) -> None:
    by_cam = {c.camera: c for c in clips}
    for cand in cands:
        m = {}
        for cam, c in by_cam.items():
            if c.timeline is None:
                continue
            z = c.timeline.robust_z()
            t = c.timeline.times
            pad = 0.0 if cam == cand["gt_camera"] else tol_s
            sel = (t >= cand["t_start"] - pad) & (t <= cand["t_end"] + pad)
            m[cam] = round(float(z[sel].max()), 2) if sel.any() else None
        cand["motion_max_z"] = m


# ----------------------------------------------------------------------------- reports


def write_reports(report: dict, out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2))
    lines = [
        "# Candidate window ranking",
        "",
        f"Generated {report['generated_at']} by `scripts/data/find_candidates.py`.",
        "",
        "Scores are heuristics for triage, not labels. Every scenario still gets a human check.",
        "",
    ]
    for grp in report["groups"]:
        lines += [
            f"## Slot {grp['slot']} (GT {grp['gt_camera']}, visible {', '.join(grp['visible_cameras'])})",
            "",
        ]
        lines += ["| camera | clip | t0 s | sync | +/- s | video |", "|---|---|---|---|---|---|"]
        for c in grp["cameras"]:
            lines.append(
                f"| {c['camera']} | `{c['clip']}` | {c['t0']} | {c['sync']} | {c['sync_uncertainty_s']} | {'yes' if c['video'] else 'no'} |"
            )
        lines.append("")
        ac = grp.get("annotation_candidates", [])
        if ac:
            lines += [
                "### Annotation candidates (GT-camera activities)",
                "",
                "| rank | score | label | t (s) | ground xy (ENU m) | blind | cue cams | motion z (GT / others) |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for i, c in enumerate(ac[:15], 1):
                mz = c.get("motion_max_z") or {}
                mzs = " / ".join(f"{k}:{v}" for k, v in mz.items()) if mz else "n/a"
                lines.append(
                    f"| {i} | {c['score']} | {c['label']} | {c['t_start']}-{c['t_end']} | {c['ground_xy']} | "
                    f"{'yes' if c['blind'] else 'no'} | {c['n_cue_cameras']} | {mzs} |"
                )
            lines.append("")
        mc = grp.get("motion_candidates", [])
        if mc:
            lines += [
                "### Motion candidates",
                "",
                "| rank | score | t (s) | primary | z | secondary z |",
                "|---|---|---|---|---|---|",
            ]
            for i, c in enumerate(mc[:10], 1):
                lines.append(
                    f"| {i} | {c['score']} | {c['t_start']}-{c['t_end']} | {c['primary_camera']} | {c['primary_z']} | {c['secondary_z']} |"
                )
            lines.append("")
        if grp.get("pairwise_lags"):
            lines += [
                "### Sync check (best motion cross-correlation lag)",
                "",
                "| a | b | lag s | ncc |",
                "|---|---|---|---|",
            ]
            for l in grp["pairwise_lags"]:
                lines.append(f"| {l['a']} | {l['b']} | {l['best_lag_s']} | {l['ncc']} |")
            lines.append("")
    out_md.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument(
        "--repo-dir", default=None, help="meva-data-repo (default <raw>/meva-data-repo)"
    )
    ap.add_argument("--slots", default=None, help="comma list of MEVA reference slots")
    ap.add_argument("--gt", default=None, help="MEVA camera id used as the withheld GT view")
    ap.add_argument(
        "--visible", default=None, help="comma list of MEVA camera ids used as visible views"
    )
    ap.add_argument("--scenario-dir", default=None, help="generic mode: folder of aligned videos")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--tolerance", type=float, default=2.0, help="secondary-change tolerance (s)")
    ap.add_argument(
        "--cue-tolerance", type=float, default=10.0, help="annotation cue window pad (s)"
    )
    ap.add_argument("--cue-radius", type=float, default=30.0, help="annotation cue radius (m)")
    ap.add_argument("--primary-z", type=float, default=3.0)
    ap.add_argument("--secondary-z", type=float, default=1.5)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--no-motion", action="store_true")
    ap.add_argument("--out-json", default=str(REPO_ROOT / "artifacts/data/candidate_ranking.json"))
    ap.add_argument("--out-md", default=str(REPO_ROOT / "artifacts/data/candidate_ranking.md"))
    args = ap.parse_args()

    raw = Path(args.raw_dir).expanduser()
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "config": {k: v for k, v in vars(args).items() if k not in ("out_json", "out_md")},
        "groups": [],
    }

    if args.scenario_dir:
        d = Path(args.scenario_dir)
        clips = [
            CamClip(
                camera=p.stem,
                clip=p.name,
                t0=0.0,
                sync="assumed aligned (offset 0)",
                sync_uncertainty_s=0.0,
                video=p,
            )
            for p in sorted(d.glob("*"))
            if p.suffix.lower() in (".mp4", ".avi", ".mov", ".mkv")
        ]
        compute_timelines(clips, args.fps, None)
        mc, lags = motion_candidates(
            clips, args.fps, args.window, args.tolerance, args.primary_z, args.secondary_z, args.top
        )
        report["groups"].append(
            {
                "slot": d.name,
                "gt_camera": None,
                "visible_cameras": [c.camera for c in clips],
                "cameras": [
                    {
                        "camera": c.camera,
                        "clip": c.clip,
                        "t0": c.t0,
                        "sync": c.sync,
                        "sync_uncertainty_s": c.sync_uncertainty_s,
                        "video": True,
                    }
                    for c in clips
                ],
                "motion_candidates": mc,
                "pairwise_lags": lags,
            }
        )
    else:
        if not (args.slots and args.gt and args.visible):
            ap.error("MEVA mode needs --slots, --gt and --visible (or use --scenario-dir)")
        repo = Path(args.repo_dir).expanduser() if args.repo_dir else raw / "meva-data-repo"
        ply = raw / "meva" / "ground_background_coarse.ply"
        ground = GroundModel(read_ply_vertices(ply)) if ply.exists() else None
        visible = args.visible.split(",")
        for slot in args.slots.split(","):
            clips = load_meva_group(raw, repo, slot, [args.gt] + visible)
            by = {c.camera: c for c in clips}
            if args.gt not in by:
                print(f"{slot}: GT camera {args.gt} not recorded, skipped")
                continue
            for c in clips:
                locate_events(c, ground)
            ac = annotation_candidates(
                by[args.gt],
                [by[v] for v in visible if v in by],
                slot,
                args.cue_tolerance,
                args.cue_radius,
            )
            mc, lags = [], []
            if not args.no_motion:
                compute_timelines(clips, args.fps, raw / "cache" / "energy")
                attach_motion(ac, clips, args.tolerance)
                mc, lags = motion_candidates(
                    clips,
                    args.fps,
                    args.window,
                    args.tolerance,
                    args.primary_z,
                    args.secondary_z,
                    args.top,
                )
            ac.sort(key=lambda c: -c["score"])
            report["groups"].append(
                {
                    "slot": slot,
                    "gt_camera": args.gt,
                    "visible_cameras": [v for v in visible if v in by],
                    "ground_model": str(ply.name) if ground else "flat z=0 plane",
                    "cameras": [
                        {
                            "camera": c.camera,
                            "clip": c.clip,
                            "t0": round(c.t0, 3),
                            "sync": c.sync,
                            "sync_uncertainty_s": round(c.sync_uncertainty_s, 3),
                            "video": c.video is not None,
                            "n_activities": len(c.events),
                        }
                        for c in clips
                    ],
                    "annotation_candidates": ac[: args.top * 3],
                    "motion_candidates": mc,
                    "pairwise_lags": lags,
                }
            )
            n_blind = sum(1 for c in ac if c["blind"])
            print(
                f"{slot}: {len(ac)} salient GT activities, {n_blind} blind; "
                f"top={ac[0]['label'] + '@' + str(ac[0]['t_start']) if ac else '-'}; "
                f"videos={sum(1 for c in clips if c.video)}/{len(clips)}",
                flush=True,
            )
    write_reports(report, Path(args.out_json), Path(args.out_md))
    print(f"wrote {args.out_json} and {args.out_md}")


if __name__ == "__main__":
    main()

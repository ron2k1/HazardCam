#!/usr/bin/env python3
"""Stage factory clips for the Safety hazard page under neutral clip ids.

Default: from the "Safe and Unsafe Behaviours" dataset (operator's USB drive), take the
first clip per label by natural sort that decodes cleanly from the test split (8 clips),
copy it to ``data/hazards/clips/<clip_id>/source.mp4`` and write ``clip.json``
``{clip_id, title, duration_s, fps, width, height, source_sha256}``.

Dataset file names start with the label index (``0_te1.mp4``), so a name leaks the label.
The label, split and original name therefore go ONLY to the judge-only
``data/hazards/labels/<clip_id>.json``; ids (``hz_01``..) and titles ("Floor camera 01")
are neutral and assigned in a seeded shuffled order, so the id order does not follow the
label order either. The review pipeline and the model only ever see the clip id.

``--import-example`` imports the teammate's real run as ``hz_00`` "Press line camera":
source video, evidence images and report JSON go to ``data/hazards/reports/hz_00/<run_id>/``
(processed video transcoded to browser H.264), with the verbatim prompts added as
``instructions`` and ``model.inference_source`` = "teammate run (Ollama, macOS)".

Nothing reads ``/media`` at runtime: everything needed is copied into ``data/hazards``.

Usage::

    .venv/bin/python scripts/hazards/prepare_clips.py                  # 8 dataset clips
    .venv/bin/python scripts/hazards/prepare_clips.py --import-example # + teammate run
    .venv/bin/python scripts/hazards/prepare_clips.py --skip-dataset --import-example
    # only some labels (dir name or its index), dropping other staged dataset clips:
    .venv/bin/python scripts/hazards/prepare_clips.py --labels 0,1,3 --prune --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2

from hazards.review import AUDIT_PROMPT, SYSTEM_PROMPT, validate_model_report
from hazards.scan import (
    CFG,
    PROCESSED_VIDEO_NAME,
    UPSTREAM_SHA256,
    UPSTREAM_VERSION,
    probe_video,
    save_json,
    sha256_file,
)
from tools.media.binaries import MediaToolError, ffmpeg_bin, passthrough_args, run_tool

DEFAULT_DATASET = Path(
    "/media/dell/GB10_BUNDLE/Video Dataset for Safe and Unsafe Behaviours/"
    "Safe and Unsafe Behaviours Dataset"
)
EXAMPLE_DIRS = (
    Path("/home/dell/factory-safety-agent/safety_hazard"),
    Path("/media/dell/GB10_BUNDLE/safety_hazard"),
)
DATA_DIR_ENV = "HAZARDS_DIR"
DEFAULT_SEED = 20261003
CLIP_PREFIX = "hz_"
DATASET_TITLE = "Floor camera {n:02d}"

EXAMPLE_CLIP_ID = "hz_00"
EXAMPLE_TITLE = "Press line camera"
EXAMPLE_VIDEO = "4_tr1.mp4"
EXAMPLE_LABEL = {
    "dataset_label": "4_safe_walkway",
    "dataset_split": "train",
    "original_name": "4_tr1.mp4",
}
EXAMPLE_INFERENCE_SOURCE = "teammate run (Ollama, macOS)"
SCRIPT_STEPS = (
    "[1/6] Scanning video frames...",
    "[2/6] Measuring motion...",
    "[3/6] Finding movement and obstruction zones...",
    "[4/6] Exporting annotated video and evidence...",
    "[5/6] Running Qwen 3.6 hazard review...",
    "[6/6] Writing and validating reports...",
)
_NATURAL = re.compile(r"(\d+)")


def natural_key(name: str) -> list[Any]:
    return [int(p) if p.isdigit() else p.lower() for p in _NATURAL.split(name)]


def visible(path: Path) -> bool:
    """Skip macOS resource forks (``._*``) and other hidden files."""
    return not path.name.startswith(".")


def default_data_dir() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV) or REPO_ROOT / "data" / "hazards")


@dataclass(frozen=True)
class ClipInfo:
    duration_s: float
    fps: float
    width: int
    height: int
    frames: int


def probe_clip(path: Path) -> ClipInfo | None:
    """Clip info when ffmpeg decodes it with no error AND cv2 reads >= 2 frames.

    The frame count / fps come from a full cv2 decode, i.e. exactly what the review
    pipeline will see (duration = frames / fps, the pipeline's timing).
    """
    try:
        proc = run_tool(
            [ffmpeg_bin(), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0"]
            + ["-f", "null", "-"],
            what=f"decode check {path.name}",
        )
    except MediaToolError:  # any decode failure just disqualifies the clip
        return None
    if proc.stderr.strip():
        return None
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = 0
        while cap.grab():
            frames += 1
            if frames > CFG["max_frames"]:
                return None
    finally:
        cap.release()
    if not (fps > 0 and width > 0 and height > 0 and frames >= 2):
        return None
    return ClipInfo(round(frames / fps, 3), fps, width, height, frames)


def label_index(name: str) -> str:
    """The leading index of a label dir name (``"3"`` for ``3_carrying...``), else ``""``."""
    match = re.match(r"(\d+)_", name)
    return match.group(1) if match else ""


def filter_labels(label_dirs: list[Path], wanted: Sequence[str] | None) -> list[Path]:
    """Keep the label dirs named in ``wanted`` (exact dir name or index); natural order.

    An entry that matches no label dir is an error, so a typo never silently drops a label.
    """
    if not wanted:
        return label_dirs
    keep: list[Path] = []
    for entry in wanted:
        entry = entry.strip()
        hits = [d for d in label_dirs if entry in (d.name, label_index(d.name))]
        if not hits:
            names = ", ".join(d.name for d in label_dirs)
            raise SystemExit(f"unknown label {entry!r}; available: {names}")
        keep += [d for d in hits if d not in keep]
    return sorted(keep, key=lambda d: natural_key(d.name))


def select_dataset_clips(
    dataset: Path, split: str, per_label: int, labels: Sequence[str] | None = None
) -> list[tuple[str, Path]]:
    """``(label, path)``: the first ``per_label`` clean clips per label, natural sort.

    ``labels`` (dir names or indices) narrows the selection; ``None`` takes every label.
    """
    split_dir = dataset / split
    if not split_dir.is_dir():
        raise SystemExit(f"dataset split not found: {split_dir}")
    chosen: list[tuple[str, Path]] = []
    label_dirs = sorted(
        (d for d in split_dir.iterdir() if d.is_dir() and visible(d)),
        key=lambda d: natural_key(d.name),
    )
    for label_dir in filter_labels(label_dirs, labels):
        files = sorted(
            (f for f in label_dir.glob("*.mp4") if visible(f) and f.is_file()),
            key=lambda f: natural_key(f.name),
        )
        taken = 0
        for path in files:
            if taken >= per_label:
                break
            if probe_clip(path) is None:
                print(f"  skip (does not decode cleanly): {label_dir.name}/{path.name}")
                continue
            chosen.append((label_dir.name, path))
            taken += 1
        if taken < per_label:
            print(f"  warning: only {taken} clean clip(s) for {label_dir.name}")
    return chosen


def assign_ids(count: int, seed: int, start: int = 1) -> list[int]:
    """Neutral clip numbers in a seeded shuffled order (id order != label order)."""
    numbers = list(range(start, start + count))
    random.Random(seed).shuffle(numbers)
    return numbers


def copy_verified(src: Path, dest: Path) -> str:
    """Copy ``src`` to ``dest`` atomically and return the verified sha256."""
    want = sha256_file(src)
    if dest.is_file() and sha256_file(dest) == want:
        return want
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    if sha256_file(tmp) != want:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"copy of {src.name} failed verification")
    tmp.replace(dest)
    return want


def guard_clip_slot(data_dir: Path, clip_id: str, source_sha256: str, force: bool) -> None:
    """Refuse to swap the video behind an existing clip id (its reports would be stale)."""
    existing = data_dir / "clips" / clip_id / "clip.json"
    if not existing.is_file():
        return
    old = json.loads(existing.read_text()).get("source_sha256")
    if old == source_sha256:
        return
    if not force:
        raise SystemExit(
            f"{clip_id} already holds a different video; pass --force to replace it "
            "(its stored reports are removed)"
        )
    stale = data_dir / "reports" / clip_id
    if stale.is_dir():
        print(f"  removing stale reports for {clip_id}")
        shutil.rmtree(stale)


def write_clip(
    data_dir: Path,
    clip_id: str,
    title: str,
    src: Path,
    info: ClipInfo,
    label: dict[str, str],
    *,
    force: bool,
) -> dict[str, Any]:
    source_sha256 = sha256_file(src)
    guard_clip_slot(data_dir, clip_id, source_sha256, force)
    clip_dir = data_dir / "clips" / clip_id
    copied = copy_verified(src, clip_dir / "source.mp4")
    clip = {
        "clip_id": clip_id,
        "title": title,
        "duration_s": info.duration_s,
        "fps": info.fps,
        "width": info.width,
        "height": info.height,
        "source_sha256": copied,
    }
    save_json(clip_dir / "clip.json", clip)
    labels_dir = data_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    save_json(labels_dir / f"{clip_id}.json", {**label, "source_sha256": copied})
    return clip


def prune_dataset_slots(data_dir: Path, keep: set[str]) -> list[str]:
    """Remove staged dataset clip ids not in ``keep`` (clip, label and reports).

    The teammate example (hz_00) is never touched. Returns the removed ids.
    """
    clips_dir = data_dir / "clips"
    if not clips_dir.is_dir():
        return []
    removed = []
    for clip_dir in sorted(clips_dir.iterdir(), key=lambda d: natural_key(d.name)):
        clip_id = clip_dir.name
        if not clip_dir.is_dir() or not re.fullmatch(rf"{CLIP_PREFIX}\d+", clip_id):
            continue
        if clip_id in keep or clip_id == EXAMPLE_CLIP_ID:
            continue
        shutil.rmtree(clip_dir)
        (data_dir / "labels" / f"{clip_id}.json").unlink(missing_ok=True)
        reports = data_dir / "reports" / clip_id
        if reports.is_dir():
            shutil.rmtree(reports)
        removed.append(clip_id)
        print(f"  pruned {clip_id} (not in this selection)")
    return removed


def prepare_dataset(args: argparse.Namespace, data_dir: Path) -> list[dict[str, Any]]:
    print(f"selecting clips from {args.dataset / args.split}")
    labels = [x for x in args.labels.split(",") if x.strip()] if args.labels else None
    chosen = select_dataset_clips(args.dataset, args.split, args.per_label, labels)
    numbers = assign_ids(len(chosen), args.seed)
    written = []
    for (label, path), number in zip(chosen, numbers, strict=True):
        info = probe_clip(path)
        if info is None:  # pragma: no cover - selection already checked it
            continue
        clip_id = f"{CLIP_PREFIX}{number:02d}"
        clip = write_clip(
            data_dir,
            clip_id,
            DATASET_TITLE.format(n=number),
            path,
            info,
            {"dataset_label": label, "dataset_split": args.split, "original_name": path.name},
            force=args.force,
        )
        written.append(clip)
        print(f"  {clip_id}  {clip['title']}  {info.duration_s:.2f}s  {info.width}x{info.height}")
    if args.prune:
        prune_dataset_slots(data_dir, {c["clip_id"] for c in written})
    return written


def upstream_run_id(manifest: dict[str, Any]) -> str:
    """The teammate script's RUN_ID: sha256({source, config, weights})[:16]."""
    key = {
        "source": manifest["source_sha256"],
        "config": manifest["config"],
        "weights": manifest.get("weights_sha256"),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def transcode_h264(src: Path, dest: Path, expected_frames: int) -> dict[str, Any]:
    ffmpeg = ffmpeg_bin()
    run_tool(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src)]
        + ["-map", "0:v:0", "-an", *passthrough_args(ffmpeg)]
        + ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast"]
        + ["-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)],
        what=f"H.264 transcode of {src.name}",
    )
    probe = probe_video(dest)
    if probe["codec"] != "h264" or probe["pix_fmt"] != "yuv420p":
        raise SystemExit(f"{dest.name} is not browser H.264: {probe}")
    if probe["frames"] != expected_frames:
        raise SystemExit(f"{dest.name} has {probe['frames']} frames, expected {expected_frames}")
    return {"name": dest.name, **probe, "faststart": True}


def import_example(example_dir: Path, data_dir: Path, *, force: bool) -> Path:
    """The teammate's real run as hz_00 (neutral source_name, verbatim model output)."""
    video = example_dir / EXAMPLE_VIDEO
    out_dir = example_dir / "example_output"
    report_path = out_dir / "hazard_report.json"
    manifest_path = out_dir / "run_manifest.json"
    for need in (video, report_path, manifest_path, out_dir / "evidence"):
        if not need.exists():
            raise SystemExit(f"example input missing: {need}")
    info = probe_clip(video)
    if info is None:
        raise SystemExit(f"{video} does not decode cleanly")
    write_clip(
        data_dir, EXAMPLE_CLIP_ID, EXAMPLE_TITLE, video, info, dict(EXAMPLE_LABEL), force=force
    )

    report = json.loads(report_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if report["video"]["source_sha256"] != sha256_file(video):
        raise SystemExit("example report does not belong to the example video")
    run_id = upstream_run_id(manifest)
    run_dir = data_dir / "reports" / EXAMPLE_CLIP_ID / run_id
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)

    by_id = {e["evidence_id"]: e for e in report["evidence"]}
    for e in report["evidence"]:
        src = out_dir / e["path"]
        dest = run_dir / e["path"]
        if copy_verified(src, dest) != e["sha256"]:
            raise SystemExit(f"evidence {e['evidence_id']} hash differs from the report")
    zones = report["zones"]
    model_part = {
        "scene_summary": report["scene_summary"],
        "findings": [
            {k: f[k] for k in f if k not in _DERIVED_FINDING_KEYS} for f in report["findings"]
        ],
        "zone_reviews": report["zone_reviews"],
        "dismissed": report["dismissed"],
        "limitations": [],
    }
    validate_model_report(json.dumps(model_part), zones, by_id)

    processed_src = out_dir / report["artifacts"]["processed_video"]
    processed = transcode_h264(
        processed_src, run_dir / PROCESSED_VIDEO_NAME, int(report["video"]["decoded_frames"])
    )
    for name in ("zones_overview.jpg", "zones.json", "evidence_manifest.json"):
        if (out_dir / name).is_file():
            shutil.copyfile(out_dir / name, run_dir / name)

    original_sha = sha256_file(report_path)
    report["video"]["source_name"] = EXAMPLE_CLIP_ID
    report["model"]["inference_source"] = EXAMPLE_INFERENCE_SOURCE
    report["artifacts"]["processed_video"] = PROCESSED_VIDEO_NAME
    report["instructions"] = {"system_prompt": SYSTEM_PROMPT, "audit_prompt": AUDIT_PROMPT}
    report["pipeline"] = {
        "version": UPSTREAM_VERSION,
        "upstream_version": UPSTREAM_VERSION,
        "ported_from_sha256": UPSTREAM_SHA256,
        "run_id": run_id,
        "imported": True,
        "imported_from": (
            "teammate example_output: Ollama qwen3.6:35b-a3b on macOS, FastSAM-s, astra-1.1"
        ),
        "original_report_sha256": original_sha,
        "quality_warnings": manifest.get("quality_warnings") or [],
        "processed_video": processed,
    }
    save_json(run_dir / "hazard_report.json", report)

    manifest["source"]["source_name"] = EXAMPLE_CLIP_ID
    manifest["imported"] = {
        "from": "teammate example_output (verbatim model output)",
        "original_report_sha256": original_sha,
        "processed_video": "re-encoded to browser H.264 (yuv420p, faststart)",
    }
    save_json(run_dir / "run_manifest.json", manifest)
    save_json(
        run_dir / "progress.json",
        [{"step": i, "total": 6, "message": m} for i, m in enumerate(SCRIPT_STEPS, 1)],
    )
    latest = {
        "run_id": run_id,
        "path": str(run_dir),
        "status": report["status"],
        "run_dir": run_id,
    }
    (run_dir.parent / "latest_run.json").write_text(json.dumps(latest, indent=2))
    print(f"  {EXAMPLE_CLIP_ID}  {EXAMPLE_TITLE}  report {run_id} ({report['status']})")
    return run_dir


_DERIVED_FINDING_KEYS = frozenset(
    {
        "finding_id",
        "first_observed_s",
        "last_observed_s",
        "observed_times_s",
        "evidence_paths",
        "standard_links",
    }
)


def find_example_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in EXAMPLE_DIRS:
        if (candidate / EXAMPLE_VIDEO).is_file():
            return candidate
    raise SystemExit(f"no teammate example found in {[str(p) for p in EXAMPLE_DIRS]}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", default="test", choices=("test", "train"))
    parser.add_argument("--per-label", type=int, default=1)
    parser.add_argument(
        "--labels",
        default=None,
        metavar="L[,L...]",
        help="only these labels: dir names or their index, e.g. 0,1,3 (default: all)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="remove staged dataset clips (and their reports) not in this selection; hz_00 is kept",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="clip id shuffle seed")
    parser.add_argument(
        "--out", type=Path, default=None, help="default: $HAZARDS_DIR or data/hazards"
    )
    parser.add_argument("--skip-dataset", action="store_true", help="do not stage dataset clips")
    parser.add_argument(
        "--import-example",
        nargs="?",
        const="auto",
        default=None,
        metavar="DIR",
        help="import the teammate run (folder holding 4_tr1.mp4 and example_output/)",
    )
    parser.add_argument("--force", action="store_true", help="replace a clip id's video")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = (args.out or default_data_dir()).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_dataset:
        prepare_dataset(args, data_dir)
    if args.import_example is not None:
        explicit = None if args.import_example == "auto" else Path(args.import_example)
        example = find_example_dir(explicit)
        print(f"importing teammate run from {example}")
        import_example(example, data_dir, force=args.force)
    print(f"done: {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Review one prepared clip with the local pipeline (CV scan + local Qwen review/audit).

Writes ``data/hazards/reports/<clip_id>/<run_id>/`` (hazard_report.json, evidence/,
processed.mp4, manifests) and ``reports/<clip_id>/latest_run.json``. The model sees only
the neutral clip id, never a file name or dataset label.

Usage::

    QWEN_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4 MISTRAL_MODEL=nvidia/Cosmos-Reason2-8B \\
      .venv/bin/python scripts/hazards/review_clip.py hz_01 --profile gb10
    .venv/bin/python scripts/hazards/review_clip.py hz_01 --skip-model     # CV stages only
    .venv/bin/python scripts/hazards/review_clip.py --video clip.mp4 \\
      --output-dir /tmp/out --source-name hz_99 --profile gb10              # any video

Exit codes: 0 done, 2 model review failed (report still written), 1 error.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hazards.pipeline import review_clip

DATA_DIR_ENV = "HAZARDS_DIR"


def format_summary(report: dict[str, Any], run_dir: Path, elapsed: float) -> str:
    """Port of the upstream console summary."""
    video, model, findings = report["video"], report["model"], report["findings"]
    moving = sum(z["kind"] == "movement" for z in report["zones"])
    static = len(report["zones"]) - moving
    rows = [
        "",
        "ASTRA VIDEO HAZARD REVIEW (GB10 port)",
        f"Status:   {report['status']}",
        (
            f"Video:    {video['source_name']} | {video['duration_s']:.2f}s | "
            f"{video['decoded_frames']} frames"
        ),
        f"Zones:    {len(report['zones'])} ({moving} movement, {static} possible obstructions)",
        f"Segments: {report['segmentation_method']}",
        f"Evidence: {len(report['evidence'])} timestamped images",
        (
            f"Model:    {model.get('name', 'not run')} | inference: "
            f"{model.get('inference_source', 'not run')} | review: {model.get('audit_source', 'not run')}"
        ),
    ]
    if model.get("prompt_tokens") is not None:
        audit = model.get("audit") or {}
        rows.append(
            f"Tokens:   review {model.get('prompt_tokens')} in / {model.get('completion_tokens')} "
            f"out ({model.get('elapsed_seconds')}s); audit {audit.get('prompt_tokens')} in / "
            f"{audit.get('completion_tokens')} out ({audit.get('elapsed_seconds')}s)"
        )
    rows.append(f"Findings: {len(findings)} | Elapsed: {elapsed:.1f}s")
    if report["model_error"]:
        rows += [f"Error: {report['model_error']}"]
    for finding in findings:
        rows += [
            "",
            f"{finding['finding_id']} [{finding['severity'].upper()}] {finding['title']}",
            f"  Status: {finding['status']} | Confidence: {finding['confidence']}",
            (
                f"  Observed: {finding['first_observed_s']:.2f}-{finding['last_observed_s']:.2f}s "
                "(sampled frames)"
            ),
            f"  References: {', '.join(finding['standards']) or 'None mapped'}",
        ]
    rows += [
        "",
        "Model findings require human review; this is not a compliance certification.",
        f"Report: {run_dir / 'hazard_report.html'}",
        f"JSON:   {run_dir / 'hazard_report.json'}",
        f"Video:  {run_dir / report['artifacts']['processed_video']}",
    ]
    return "\n".join(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("clip_id", nargs="?", help="prepared clip id, e.g. hz_01")
    parser.add_argument(
        "--root", type=Path, default=None, help="default: $HAZARDS_DIR or data/hazards"
    )
    parser.add_argument("--video", type=Path, help="review this video instead of a clip id")
    parser.add_argument("--output-dir", type=Path, help="with --video: output root")
    parser.add_argument("--source-name", help="with --video: neutral id the model sees")
    parser.add_argument("--profile", default=None, help="model profile (default $MODEL_PROFILE)")
    parser.add_argument("--skip-model", action="store_true", help="CV stages only")
    parser.add_argument("--refresh", action="store_true", help="ignore cached model results")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.video is None and not args.clip_id:
        parser.error("give a clip id or --video")
    if args.video is not None and not (args.output_dir and args.source_name):
        parser.error("--video needs --output-dir and --source-name")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if args.video is not None:
        video, output_root, source_name = args.video, args.output_dir, args.source_name
    else:
        root = args.root or Path(os.environ.get(DATA_DIR_ENV) or REPO_ROOT / "data/hazards")
        video = root / "clips" / args.clip_id / "source.mp4"
        output_root = root / "reports" / args.clip_id
        source_name = args.clip_id
    started = time.monotonic()

    def progress(step: int, total: int, message: str) -> None:
        print(f"{message} (+{time.monotonic() - started:.1f}s)", flush=True)

    try:
        run_dir = review_clip(
            video,
            output_root,
            source_name=source_name,
            profile=args.profile,
            skip_model=args.skip_model,
            refresh=args.refresh,
            progress=progress,
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    report = json.loads((run_dir / "hazard_report.json").read_text())
    print(format_summary(report, run_dir, time.monotonic() - started))
    return 2 if report["status"] == "model_review_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

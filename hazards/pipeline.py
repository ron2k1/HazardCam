"""``review_clip``: the six upstream steps for one video, end to end.

Run directory: ``<output_root>/<run_id>/`` where ``run_id`` is the first 16 hex of
sha256({source sha256, CFG, detector model sha256s, pipeline version}) (upstream used the
FastSAM weight sha256). ``<output_root>/latest_run.json`` points at the newest run.

The model only ever sees ``source_name`` (a neutral clip id such as ``hz_03``), never the
file name, dataset label or path.

Review mode: ``mode=None`` reads ``review_mode`` from the clip store's ``clip.json`` next to
the video (``data/hazards/clips/<id>/source.mp4``), else ``"hazard"``. So the API and the
agent runner seam (``runner(video, output_root, *, source_name, refresh, progress)``) stay
unchanged and blind-spot clips (``bs_*``) get their own instructions automatically. The
hazard mode's run ids are unchanged; another mode adds its name to the run-id key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from inference.profiles import load_profile

from .detector.client import DEFAULT_CONF, DEFAULT_MODELS, DetectorClient
from .report import build_report, write_outputs
from .review import (
    DEFAULT_REVIEW_MODE,
    REVIEW_MODES,
    STATUS_PREPROCESSING,
    HazardReviewer,
    ReviewOutcome,
    get_review_mode,
    run_review,
)
from .scan import CFG, PIPELINE_VERSION, run_scan, save_json, sha256_file, single_threaded_cv

log = logging.getLogger(__name__)

TOTAL_STEPS = 6
# The upstream progress messages, verbatim (``progress("[1/6] ...")`` in run_pipeline).
STEP_MESSAGES = (
    "[1/6] Scanning video frames...",
    "[2/6] Measuring motion...",
    "[3/6] Finding movement and obstruction zones...",
    "[4/6] Exporting annotated video and evidence...",
    "[5/6] Running Qwen 3.6 hazard review...",
    "[6/6] Writing and validating reports...",
)
PROGRESS_FILE = "progress.json"
ProgressFn = Callable[[int, int, str], None]
_SOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def check_source_name(source_name: str, video: Path) -> str:
    """A neutral clip id: no extension, no path, and not the dataset file's own stem."""
    if not _SOURCE_NAME.match(source_name or ""):
        raise ValueError(
            f"source_name {source_name!r} must be a neutral clip id like 'hz_01' "
            "(letters, digits, '_' or '-'; no file name)"
        )
    if video.stem != "source" and source_name == video.stem:
        raise ValueError("source_name must not be the video's file name (it can leak the label)")
    return source_name


def compute_run_id(
    source_sha256: str, weights: Mapping[str, str] | None, mode: str = DEFAULT_REVIEW_MODE
) -> str:
    key: dict[str, object] = {
        "source": source_sha256,
        "config": CFG,
        "weights": weights,
        "pipeline": PIPELINE_VERSION,
    }
    if mode != DEFAULT_REVIEW_MODE:  # hazard run ids stay exactly as before
        key["review_mode"] = mode
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


CLIP_MANIFEST = "clip.json"


def resolve_review_mode(video: Path, mode: str | None = None) -> str:
    """``mode`` if given, else the clip manifest's ``review_mode`` next to ``video``, else
    ``"hazard"``. Raises ValueError for an unknown mode."""
    if mode is None:
        manifest = Path(video).parent / CLIP_MANIFEST
        if manifest.is_file():
            try:
                clip = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                clip = {}
            if isinstance(clip, dict) and isinstance(clip.get("review_mode"), str):
                mode = clip["review_mode"]
    mode = mode or DEFAULT_REVIEW_MODE
    if mode not in REVIEW_MODES:
        raise ValueError(f"unknown review mode {mode!r}; expected one of {', '.join(REVIEW_MODES)}")
    return mode


def review_clip(
    video: Path,
    output_root: Path,
    *,
    source_name: str,
    profile: str | None = None,
    skip_model: bool = False,
    refresh: bool = False,
    progress: ProgressFn | None = None,
    detector: DetectorClient | None = None,
    detector_models: Sequence[str] = DEFAULT_MODELS,
    reviewer: HazardReviewer | None = None,
    env: Mapping[str, str] | None = None,
    mode: str | None = None,
) -> Path:
    """Scan ``video``, review it with the local Qwen (unless ``skip_model``), write reports.

    Returns the run directory. ``progress(step, 6, message)`` gets the upstream step
    messages (``STEP_MESSAGES``, also saved as ``progress.json`` in the run directory). ``detector``/``reviewer``/``env`` are injection points for tests; by default
    the detector is ``DetectorClient()`` (``$HAZARDS_DETECTOR_URL`` or 127.0.0.1:8003) and
    the reviewer comes from the model profile (``profile`` or ``$MODEL_PROFILE``).
    Raises on unreadable video or a profile without a model endpoint; a model failure is
    recorded in the report as ``model_review_failed`` (upstream behaviour).
    ``mode`` ("hazard" | "blindspot") picks the instructions and standards; None reads the
    clip manifest's ``review_mode`` (see :func:`resolve_review_mode`).
    """
    video = Path(video).resolve()
    output_root = Path(output_root).resolve()
    if not video.is_file():
        raise FileNotFoundError(f"Missing input video: {video.name}")
    check_source_name(source_name, video)
    review_mode = get_review_mode(resolve_review_mode(video, mode))
    report_progress: ProgressFn = progress or (lambda _s, _t, _m: None)
    steps_seen: list[dict[str, object]] = []

    def step(n: int) -> None:
        message = STEP_MESSAGES[n - 1]
        log.info("%s", message)
        steps_seen.append({"step": n, "total": TOTAL_STEPS, "message": message})
        report_progress(n, TOTAL_STEPS, message)

    profile_name = profile
    if not skip_model and reviewer is None:
        loaded = load_profile(profile, env=env)
        profile_name = loaded.profile
        reviewer = HazardReviewer.from_profile(loaded, env=env)
    elif reviewer is not None:
        profile_name = reviewer.profile_name or profile

    detector = detector if detector is not None else DetectorClient()
    health = detector.health()
    weights = (
        {m: health.models[m] for m in detector_models if m in health.models} or None
        if health.ok
        else None
    )
    source_sha256 = sha256_file(video)
    run_id = compute_run_id(source_sha256, weights, review_mode.name)
    out = output_root / run_id
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    log.info(
        "input %s | run %s | mode %s | model %s",
        source_name,
        run_id,
        review_mode.name,
        reviewer and reviewer.model,
    )

    started = time.monotonic()
    with single_threaded_cv():
        scan = run_scan(
            video,
            out,
            source_name=source_name,
            source_sha256=source_sha256,
            detector=detector,
            detector_health=health,
            detector_models=detector_models,
            detector_conf=DEFAULT_CONF,
            progress=step,
        )
    scanned = time.monotonic()

    step(5)
    if skip_model or reviewer is None:
        outcome = ReviewOutcome(status=STATUS_PREPROCESSING)
        log.info("Qwen disabled; report holds preprocessing evidence only")
    else:
        outcome = run_review(
            reviewer,
            out,
            meta=scan.meta,
            zones=scan.zones,
            evidence=scan.evidence,
            quality_warnings=scan.quality_warnings,
            refresh=refresh,
            mode=review_mode,
        )
    reviewed = time.monotonic()

    step(6)
    report = build_report(scan, outcome, run_id=run_id, profile=profile_name, mode=review_mode)
    timings = {
        "scan": round(scanned - started, 2),
        "review": round(reviewed - scanned, 2),
        "total": round(time.monotonic() - started, 2),
    }
    # Stored steps let the API's fixture profile replay this run without a model call.
    save_json(out / PROGRESS_FILE, steps_seen)
    write_outputs(out, output_root, report, scan, run_id=run_id, timings=timings)
    log.info(
        "validated %d frames, %d zones, %d evidence images; status %s",
        scan.n,
        len(scan.zones),
        len(scan.evidence),
        report["status"],
    )
    return out

"""Step 6 of the upstream script: hazard_report.{json,csv,md,html}, manifests, assertions.

``hazard_report.json`` keeps the upstream shape (title, status, generated_at_utc, video,
model, request_sha256, model_error, scene_summary, findings H01.., zone_reviews,
dismissed, limitations, standards, zones, evidence, config, segmentation_method,
segmentation_weights_sha256, artifacts) and adds ``instructions`` (the verbatim prompts)
and ``pipeline`` (port version, upstream sha256, detector record, zone sources, warnings).
"""

from __future__ import annotations

import copy
import csv
import html
import importlib.metadata
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .review import (
    HAZARD_MODE,
    HAZARD_REPORT_TITLE,
    STANDARDS,
    ReviewMode,
    ReviewOutcome,
)
from .scan import (
    CFG,
    PIPELINE_VERSION,
    UPSTREAM_PATH,
    UPSTREAM_SHA256,
    UPSTREAM_VERSION,
    ScanResult,
    save_json,
    sha256_file,
)

REPORT_TITLE = HAZARD_REPORT_TITLE  # a review mode may set its own (report["title"])
NO_REVIEW_SUMMARY = "Qwen review not completed; no hazard conclusions are available."
# Verbatim upstream limitations (quality warnings and the model's own limitations follow).
LIMITATIONS = [
    (
        "Visual screening against OSHA General Industry references; jurisdiction and legal "
        "compliance are not established."
    ),
    (
        "All frames scanned by CV; Qwen reviewed only the listed sampled frames and crops. "
        "No audio analyzed."
    ),
    (
        "Observation spans do not establish continuity; hidden controls, energy state, and "
        "training cannot be verified."
    ),
    (
        "Static region ranking is heuristic, not a complete obstruction detector; no clear-scene "
        "baseline or metric clearance calibration is available."
    ),
    "Camera housing, occlusion, resolution and sampling can hide hazards.",
    (
        "The bounded citation library is not an exhaustive factory-safety checklist; "
        "machine-specific rules need further review."
    ),
]
VALIDATION_NOTE = (
    "Decoded all available frames; checked output video count, evidence hashes, IDs, bounds, "
    "schema and report files."
)
CSV_COLUMNS = [
    "finding_id",
    "title",
    "status",
    "severity",
    "confidence",
    "first_observed_s",
    "last_observed_s",
    "location",
    "observation",
    "risk_interpretation",
    "standards",
    "evidence_ids",
    "recommended_actions",
    "unknowns",
]
_VERSION_PACKAGES = (
    "numpy",
    "opencv-python",
    "opencv-python-headless",
    "pydantic",
    "httpx",
    "PyYAML",
)


def build_findings(
    findings: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    standards: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """H01.. with the observed times, evidence paths and standard links upstream derives."""
    table = STANDARDS if standards is None else standards
    out = []
    for i, f in enumerate(findings, 1):
        times = sorted({evidence_by_id[e]["timestamp_s"] for e in f["evidence_ids"]})
        out.append(
            {
                "finding_id": f"H{i:02d}",
                **f,
                "first_observed_s": times[0],
                "last_observed_s": times[-1],
                "observed_times_s": times,
                "evidence_paths": [evidence_by_id[e]["path"] for e in f["evidence_ids"]],
                "standard_links": [table[s]["url"] for s in f["standards"]],
            }
        )
    return out


def build_report(
    scan: ScanResult,
    outcome: ReviewOutcome,
    *,
    run_id: str,
    profile: str | None,
    mode: ReviewMode = HAZARD_MODE,
) -> dict[str, Any]:
    evidence_by_id = {e["evidence_id"]: e for e in scan.evidence}
    result = outcome.result.model_dump() if outcome.result else None
    findings = build_findings(result["findings"] if result else [], evidence_by_id, mode.standards)
    detector = scan.detector.as_dict()
    return {
        "title": mode.report_title,
        "status": outcome.status,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "video": scan.meta,
        "model": outcome.metadata,
        "request_sha256": outcome.request_sha256,
        "model_error": outcome.error,
        "scene_summary": result["scene_summary"] if result else NO_REVIEW_SUMMARY,
        "findings": findings,
        "zone_reviews": result["zone_reviews"] if result else [],
        "dismissed": result["dismissed"] if result else [],
        "limitations": LIMITATIONS
        + list(mode.extra_limitations)
        + scan.quality_warnings
        + (result["limitations"] if result else []),
        "standards": copy.deepcopy(dict(mode.standards)),
        "zones": scan.zones,
        "evidence": scan.evidence,
        "config": dict(CFG),
        "segmentation_method": scan.segmentation_method,
        "segmentation_weights_sha256": scan.weights_sha256,
        "artifacts": {
            "processed_video": scan.processed_video["name"],
            "zones": "zones.csv",
            "evidence_manifest": "evidence_manifest.json",
            "zones_overview": "zones_overview.jpg",
            "motion_heatmap": "motion_heatmap.png",
        },
        "instructions": {"system_prompt": mode.system_prompt, "audit_prompt": mode.audit_prompt},
        "pipeline": {
            "version": PIPELINE_VERSION,
            "upstream_version": UPSTREAM_VERSION,
            "ported_from_sha256": UPSTREAM_SHA256,
            "ported_from": UPSTREAM_PATH,
            "run_id": run_id,
            "profile": profile,
            "review_mode": mode.name,
            "quality_warnings": scan.quality_warnings,
            "detector": detector,
            "zone_sources": scan.zone_sources,
            "candidate_counts": scan.candidate_counts,
            "processed_video": scan.processed_video,
            "images_sent": outcome.images_sent,
            "payload_bytes": outcome.payload_bytes,
        },
    }


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def write_csv(path: Path, findings: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for f in findings:
            writer.writerow(
                ["; ".join(f[k]) if isinstance(f[k], list) else f[k] for k in CSV_COLUMNS]
            )


def render_markdown(report: Mapping[str, Any]) -> str:
    video, findings = report["video"], report["findings"]
    evidence_by_id = {e["evidence_id"]: e for e in report["evidence"]}
    standards = report["standards"]
    model_name = report["model"].get("name") or "not run"
    lines = [
        f"# {report.get('title') or REPORT_TITLE}",
        f"**Status:** {report['status']}",
        (
            f"**Video:** {video['source_name']} · {video['duration_s']:.2f} s · "
            f"{video['decoded_frames']} frames scanned · {len(report['evidence'])} evidence images"
        ),
        f"**Model:** {model_name} · **Generated (UTC):** {report['generated_at_utc']}",
        "Visual safety screening; observations require qualified safety review.",
        "## Scene",
        report["scene_summary"],
        "## Findings",
    ]
    if report["model_error"]:
        lines += ["**MODEL REVIEW FAILED — NO HAZARD CONCLUSIONS.**", report["model_error"]]
    if not findings:
        lines += [
            "No findings returned in the sampled evidence; this is not a safety clearance."
            if report["status"] == "model_review_complete"
            else "No model findings available."
        ]
    for f in findings:
        lines += [
            f"### {f['finding_id']} · {f['title']}",
            f"**{f['severity'].upper()} priority · {f['status']} · {f['confidence']} confidence**",
            (
                f"Cited observations: {f['first_observed_s']:.2f}–{f['last_observed_s']:.2f} s "
                f"(sampled, not continuous). Location: {f['location']}"
            ),
            "**Observed:** " + f["observation"],
            "**Potential risk:** " + f["risk_interpretation"],
            "**References:** "
            + (
                ", ".join(f"[{s}]({standards[s]['url']})" for s in f["standards"])
                or "No mapped reference"
            ),
            "**Applicability:** " + f["applicability_reason"],
            "**Unknowns:** " + ("; ".join(f["unknowns"]) or "None listed by model"),
            "**Actions:** " + "; ".join(f["recommended_actions"]),
            "**Evidence:** "
            + ", ".join(f"[{eid}]({evidence_by_id[eid]['path']})" for eid in f["evidence_ids"]),
        ]
    lines += ["## Zone review"]
    lines += [
        f"- **{z['zone_id']} — {z['disposition']}**: {z['interpretation']}"
        for z in report["zone_reviews"]
    ]
    lines += ["## Dismissed or unsubstantiated candidates"]
    lines += [f"- **{d['concern']}**: {d['reason']}" for d in report["dismissed"]]
    lines += ["## Limitations"] + ["- " + x for x in report["limitations"]]
    lines += [
        "## Processing evidence",
        f"Segmentation: {report['segmentation_method']}",
        "![Proposed zones](zones_overview.jpg)",
        "![Motion heatmap](motion_heatmap.png)",
        f"[Annotated video]({report['artifacts']['processed_video']})",
        "[Evidence manifest](evidence_manifest.json)",
        "[Full machine-readable report](hazard_report.json)",
        "## Official references",
    ]
    lines += [
        f"- [{s} — {v['title']}]({v['url']}) · checked {v['checked_on']}"
        for (s, v) in standards.items()
    ]
    return "\n\n".join(lines)


def render_html(report: Mapping[str, Any]) -> str:
    video, findings = report["video"], report["findings"]
    evidence_by_id = {e["evidence_id"]: e for e in report["evidence"]}
    standards = report["standards"]
    body = [
        f"<h1>{_esc(report.get('title') or REPORT_TITLE)}</h1>",
        (
            f"<p><b>{_esc(report['status'])}</b> · {_esc(video['source_name'])} · "
            f"{video['duration_s']:.2f} seconds</p>"
        ),
        (
            "<p class='note'>Visual screening for qualified review. This report does not establish "
            "legal compliance.</p>"
        ),
        f"<p>{_esc(report['scene_summary'])}</p>",
        "<h2>Findings</h2>",
    ]
    if not findings:
        body.append(
            "<p>"
            + _esc(
                report["model_error"] or "No findings available; this is not a safety clearance."
            )
            + "</p>"
        )
    for f in findings:
        body += [
            f"<article><h3>{_esc(f['finding_id'])} · {_esc(f['title'])}</h3>",
            (
                f"<p><b>{_esc(f['severity']).upper()}</b> · {_esc(f['status'])} · "
                f"{_esc(f['confidence'])} confidence</p>"
            ),
            (
                f"<p>Cited observations: {f['first_observed_s']:.2f}–{f['last_observed_s']:.2f} s; "
                f"{_esc(f['location'])}</p>"
            ),
        ]
        for label, key in [
            ("Observed", "observation"),
            ("Potential risk", "risk_interpretation"),
            ("Applicability", "applicability_reason"),
        ]:
            body.append(f"<p><b>{label}:</b> {_esc(f[key])}</p>")
        body.append(
            "<p><b>References:</b> "
            + (
                ", ".join(
                    f"<a href='{_esc(standards[s]['url'])}'>{_esc(s)}</a>" for s in f["standards"]
                )
                or "No mapped reference"
            )
            + "</p>"
        )
        body.append(
            "<p><b>Unknowns:</b> " + _esc("; ".join(f["unknowns"]) or "None listed") + "</p>"
        )
        body.append("<p><b>Actions:</b> " + _esc("; ".join(f["recommended_actions"])) + "</p>")
        body.append("<div class='gallery'>")
        for eid in f["evidence_ids"][:4]:
            e = evidence_by_id[eid]
            body.append(
                f"<figure><a href='{_esc(e['path'])}'><img src='{_esc(e['path'])}'></a>"
                f"<figcaption>{_esc(eid)} · {e['timestamp_s']:.2f} s</figcaption></figure>"
            )
        body.append(
            "</div><p>All cited evidence: "
            + ", ".join(
                f"<a href='{_esc(evidence_by_id[eid]['path'])}'>{_esc(eid)}</a>"
                for eid in f["evidence_ids"]
            )
            + "</p></article>"
        )
    body += ["<h2>Zone review</h2>"] + [
        f"<p><b>{_esc(z['zone_id'])} · {_esc(z['disposition'])}:</b> {_esc(z['interpretation'])}</p>"
        for z in report["zone_reviews"]
    ]
    body += ["<h2>Dismissed candidates</h2>"] + [
        f"<p><b>{_esc(d['concern'])}:</b> {_esc(d['reason'])}</p>" for d in report["dismissed"]
    ]
    body += [
        (
            "<h2>Processing evidence</h2><img class='wide' src='zones_overview.jpg'>"
            "<img class='wide' src='motion_heatmap.png'>"
        ),
        f"<video controls width='100%' src='{_esc(report['artifacts']['processed_video'])}'></video>",
        "<h2>Limitations</h2><ul>",
    ]
    body += ["<li>" + _esc(x) + "</li>" for x in report["limitations"]]
    body += ["</ul><h2>Official references</h2><ul>"] + [
        f"<li><a href='{_esc(v['url'])}'>{_esc(s)} · {_esc(v['title'])}</a></li>"
        for (s, v) in standards.items()
    ]
    body += [
        (
            f"</ul><p>Generated {_esc(report['generated_at_utc'])} · Source SHA-256: "
            f"<code>{_esc(video['source_sha256'])}</code></p>"
        ),
        (
            "<p><a href='hazard_report.json'>Full JSON</a> · <a href='hazard_report.csv'>CSV</a> · "
            "<a href='evidence_manifest.json'>Evidence manifest</a></p>"
        ),
    ]
    css = (
        "body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;"
        "padding:0 24px;color:#202630}h1{font-size:36px}h2{margin-top:42px}"
        "article{border-top:1px solid #cdd4dc;padding:20px 0}.note{background:#edf2f6;"
        "padding:14px}.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));"
        "gap:12px}figure{margin:0}img{max-width:100%}.wide{display:block;width:100%;"
        "margin:20px 0}a{color:#235786}code{overflow-wrap:anywhere}"
        "@media(max-width:700px){.gallery{grid-template-columns:1fr}}"
    )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width,initial-scale=1'><title>{_esc(report.get('title') or REPORT_TITLE)}</title><style>"
        + css
        + "</style><body>"
        + "\n".join(body)
        + "</body></html>"
    )


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def final_assertions(out: Path, report: Mapping[str, Any], scan: ScanResult) -> None:
    """Upstream end-of-run assertions (explicit raises so ``python -O`` keeps them)."""
    n, duration, times = scan.n, scan.duration, scan.times
    _check(len(times) == n and bool(np.all(np.diff(times) > 0)), "frame times not increasing")
    _check(
        scan.heatmap.shape == (scan.ah, scan.aw) and bool(np.isfinite(scan.heatmap).all()),
        "motion heatmap shape/finite check failed",
    )
    evidence = report["evidence"]
    _check(len({e["evidence_id"] for e in evidence}) == len(evidence), "duplicate evidence ids")
    for e in evidence:
        _check(
            0 <= e["frame_index"] < n and 0 <= e["timestamp_s"] < duration,
            f"evidence {e['evidence_id']} out of bounds",
        )
        _check(sha256_file(out / e["path"]) == e["sha256"], f"evidence {e['evidence_id']} hash")
    for f in report["findings"]:
        _check(
            0 <= f["first_observed_s"] <= f["last_observed_s"] < duration,
            f"finding {f['finding_id']} times out of bounds",
        )
        _check(
            set(f["standards"]).issubset(report["standards"]), "citation outside the reference set"
        )
    for name in [
        "hazard_report.html",
        "hazard_report.md",
        "hazard_report.json",
        "hazard_report.csv",
        "zones.csv",
        report["artifacts"]["processed_video"],
    ]:
        _check((out / name).stat().st_size > 0, f"{name} is empty")


def package_versions() -> dict[str, str]:
    versions = {}
    for package in _VERSION_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


def write_outputs(
    out: Path,
    output_root: Path,
    report: dict[str, Any],
    scan: ScanResult,
    *,
    run_id: str,
    timings: Mapping[str, float],
) -> None:
    """All report files, the final assertions, run_manifest.json and latest_run.json."""
    save_json(out / "hazard_report.json", report)
    write_csv(out / "hazard_report.csv", report["findings"])
    (out / "hazard_report.md").write_text(render_markdown(report), encoding="utf-8")
    (out / "hazard_report.html").write_text(render_html(report), encoding="utf-8")
    final_assertions(out, report, scan)
    detector = {k: v for k, v in scan.detector.as_dict().items() if k != "objects"}
    save_json(
        out / "run_manifest.json",
        {
            "status": report["status"],
            "run_id": run_id,
            "source": report["video"],
            "config": report["config"],
            "model": report["model"],
            "request_sha256": report["request_sha256"],
            "python": sys.version,
            "platform": platform.platform(),
            "versions": package_versions(),
            "source_sha256": report["video"]["source_sha256"],
            "weights_sha256": scan.weights_sha256,
            "detector": detector,
            "segmentation_method": report["segmentation_method"],
            "quality_warnings": scan.quality_warnings,
            "pipeline_version": PIPELINE_VERSION,
            "ported_from_sha256": UPSTREAM_SHA256,
            "timings_s": dict(timings),
            "validation": VALIDATION_NOTE
            + " Processed video verified as browser H.264 (yuv420p, faststart).",
        },
    )
    (output_root / "latest_run.json").write_text(
        json.dumps(
            {"run_id": run_id, "path": str(out), "status": report["status"], "run_dir": run_id},
            indent=2,
        )
    )

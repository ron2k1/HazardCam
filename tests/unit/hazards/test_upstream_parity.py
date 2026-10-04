"""The port keeps the original script's constants, prompts, schema and wording verbatim.

The upstream file is parsed with ``ast`` (never imported: it needs pandas/matplotlib/
requests, which the app does not have).
"""

from __future__ import annotations

import ast
import random
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from apps.api.schemas import REPO_ROOT
from hazards import pipeline, report, review, scan

UPSTREAM = REPO_ROOT / scan.UPSTREAM_PATH
SOURCE = UPSTREAM.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _assigned(name: str) -> ast.AST:
    for node in ast.walk(TREE):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return node.value
    raise AssertionError(f"{name} not assigned upstream")


def _exec_upstream(names: set[str]) -> dict[str, Any]:
    """Execute selected top-level upstream defs (classes/functions) in a namespace."""
    module = ast.Module(
        body=[
            n
            for n in TREE.body
            if isinstance(n, ast.ClassDef | ast.FunctionDef) and n.name in names
        ],
        type_ignores=[],
    )
    namespace: dict[str, Any] = {
        "BaseModel": BaseModel,
        "ConfigDict": ConfigDict,
        "Field": Field,
        "Literal": Literal,
    }
    # dont_inherit: keep this file's "from __future__ import annotations" out of it
    code = compile(module, str(UPSTREAM), "exec", dont_inherit=True)
    exec(code, namespace)  # noqa: S102 - pinned, sha-checked local file
    return namespace


def test_third_party_copy_is_byte_identical():
    assert scan.sha256_file(UPSTREAM) == scan.UPSTREAM_SHA256


def test_prompts_are_verbatim():
    assert review.SYSTEM_PROMPT == ast.literal_eval(_assigned("SYSTEM_PROMPT"))
    assert review.AUDIT_PROMPT == ast.literal_eval(_assigned("AUDIT_PROMPT"))


def test_standards_table_is_verbatim_with_upstream_url_and_date():
    base = ast.literal_eval(_assigned("STANDARDS"))
    assert list(review.STANDARDS) == list(base)
    for key, item in base.items():
        expected = {
            **item,
            "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/"
            + item["section"],
            "checked_on": "2026-10-03",
        }
        assert review.STANDARDS[key] == expected
    assert '"https://www.osha.gov/laws-regs/regulations/standardnumber/1910/"' in SOURCE
    assert 'item["checked_on"] = "2026-10-03"' in SOURCE


def test_cfg_is_verbatim():
    call = _assigned("CFG")
    assert isinstance(call, ast.Call)
    upstream_cfg = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    assert scan.CFG == upstream_cfg
    assert list(scan.CFG) == list(upstream_cfg)


def test_pydantic_models_produce_the_same_schema():
    ns = _exec_upstream({"StrictModel", "Finding", "ZoneReview", "Dismissed", "ModelReport"})
    assert review.ModelReport.model_json_schema() == ns["ModelReport"].model_json_schema()


def test_build_schema_sets_the_upstream_enums():
    schema = review.build_schema(["E001", "E002"], ["Z01"])
    defs = schema["$defs"]
    assert defs["Finding"]["properties"]["standards"]["items"]["enum"] == list(review.STANDARDS)
    for name in ("Finding", "ZoneReview", "Dismissed"):
        assert defs[name]["properties"]["evidence_ids"]["items"]["enum"] == ["E001", "E002"]
    assert defs["Finding"]["properties"]["zone_ids"]["items"]["enum"] == ["Z01"]
    assert defs["ZoneReview"]["properties"]["zone_id"]["enum"] == ["Z01"]
    no_zones = review.build_schema(["E001"], [])["$defs"]
    assert "enum" not in no_zones["ZoneReview"]["properties"]["zone_id"]


@pytest.mark.parametrize(
    "text",
    [
        scan.WARN_GLOBAL_CHANGE,
        scan.WARN_TRANSLATION,
        scan.WARN_STATIC_FALLBACK,
        scan.WARN_NO_FLOOR,
        *report.LIMITATIONS,
        report.VALIDATION_NOTE,
        report.NO_REVIEW_SUMMARY,
        review.INTRO_PREFIX.rstrip("\n"),
        review.FINAL_INSTRUCTION,
        "Proposal scores are heuristic rankings within each kind, not hazard probabilities.",
        "(sampled, not continuous)",
        "M: movement | S: stationary review candidate",
        "Model response was truncated; increase num_predict",
        "Evidence image budget exceeded; revise sampling settings explicitly",
        "edge-contour fallback",
    ],
)
def test_wording_appears_verbatim_upstream(text):
    assert text in SOURCE.replace('"\n            "', "")


def test_frame_count_warning_matches_the_upstream_fstring():
    assert (
        'f"Container reports {REPORTED_N} frames; decoder read {N}. Check for truncation."'
        in SOURCE
    )
    assert scan.WARN_FRAME_COUNT.format(reported="{REPORTED_N}", decoded="{N}") == (
        "Container reports {REPORTED_N} frames; decoder read {N}. Check for truncation."
    )


def test_repair_message_matches_upstream():
    upstream = (
        'f"Repair the JSON. Validation error: {str(exc)[:1200]}. Preserve evidence grounding '
        'and review all zones exactly once."'
    )
    assert upstream in SOURCE
    assert review.REPAIR_TEMPLATE.format(error="{str(exc)[:1200]}") in upstream


def test_step_messages_are_the_upstream_progress_calls():
    for message in pipeline.STEP_MESSAGES:
        assert f'progress("{message}")' in SOURCE
    assert len(pipeline.STEP_MESSAGES) == pipeline.TOTAL_STEPS == 6


def test_evidence_label_format_matches_upstream():
    assert (
        'label = f"{eid} | t={TIMES[index]:.3f}s | {kind}" + (f" | {zone_id}" if zone_id else "")'
        in SOURCE
    )
    assert scan.evidence_label("E004", 1.23456, "zone crop", "Z03") == (
        "E004 | t=1.235s | zone crop | Z03"
    )
    assert scan.evidence_label("E001", 0.0, "full scene") == "E001 | t=0.000s | full scene"
    assert "cv2.IMWRITE_JPEG_QUALITY, 92" in SOURCE and scan.EVIDENCE_JPEG_QUALITY == 92


def test_select_distinct_and_box_iou_behave_like_upstream():
    ns = _exec_upstream({"box_iou", "select_distinct"})
    rng = random.Random(7)
    for _ in range(50):
        props = []
        for _ in range(rng.randint(0, 25)):
            x0, y0 = rng.randint(0, 700), rng.randint(0, 400)
            box = [x0, y0, x0 + rng.randint(1, 120), y0 + rng.randint(1, 120)]
            props.append({"bbox_analysis": box, "proposal_score": rng.random()})
        limit = rng.randint(1, 6)
        assert scan.select_distinct(props, limit) == ns["select_distinct"](props, limit)
        if len(props) >= 2:
            a, b = props[0]["bbox_analysis"], props[1]["bbox_analysis"]
            assert scan.box_iou(a, b) == ns["box_iou"](a, b)


@pytest.mark.parametrize(
    "fragment",
    [
        "cv2.resize(frame, (AW, AH), interpolation=cv2.INTER_AREA)",
        "TIMES = np.arange(N) / FPS",
        'np.linspace(0, N - 1, min(N, CFG["background_samples"])).astype(int)',
        "np.median(np.stack([frames[i] for i in BG_INDICES]), axis=0)",
        "cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0)",
        "cv2.morphologyEx(moving, cv2.MORPH_OPEN, kernel3)",
        "cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))",
        "(step_fraction > 0.35).any()",
        "if response > 0.2:",
        "np.median(shifts) > 3",
        "cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8)",
        "w * h > 0.6 * AW * AH",
        "max(0.01, float(trace.max()) * 0.15)",
        "cv2.inRange(hsv, (18, 65, 55), (90, 255, 255))",
        "cv2.dilate(paint, np.ones((21, 21), np.uint8))",
        "inside.sum() > 0.04 * AW * AH",
        "mask[-3:].mean() > 0.02",
        "np.median(hsv[:, :, 1][inside]) < 70",
        "(edge_map[inside] > 0).mean() < 0.06",
        "area < 0.002 * AW * AH or area > 0.15 * AW * AH",
        "(0.05 + floor_contact) ** 2",
        "(1 + 2 * proximity)",
        'box_iou(item["bbox_analysis"], old["bbox_analysis"]) < 0.6',
        "abs(i - j) / FPS >= 0.7",
        "pad = max(50, round(max(x1 - x0, y1 - y0) * 0.25))",
        'indices = [z["peak_frame"], N - 1 if z["peak_frame"] < N // 2 else 0]',
        "np.full((frame.shape[0] + 36, max(frame.shape[1], 520), 3), 22, np.uint8)",
        "cv2.Canny(bg_gray, 60, 150)",
    ],
)
def test_ported_algorithm_fragments_exist_upstream(fragment):
    """Guards against misremembering an upstream constant when reading scan.py."""
    assert fragment in SOURCE

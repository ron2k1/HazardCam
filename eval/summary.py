"""Aggregate scenario scores into ``summary.json`` and render it as Markdown.

Headline numbers, baselines and verdict flags follow ``eval/SCORING.md``. A failed run
stays in every denominator.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from apps.api.schemas import UNKNOWN
from eval.scoring import CORRECT_OUTCOMES, ScenarioScore, class_ok
from inference.vocab import HYPOTHESIS_EVENT_TYPES

CATEGORIES = tuple(CORRECT_OUTCOMES)
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n trials; ``None`` when n is 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def proportion(flags: Iterable[bool]) -> dict[str, Any]:
    values = list(flags)
    k, n = sum(values), len(values)
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson95": wilson(k, n)}


def _balanced(by_category: dict[str, dict[str, Any]]) -> float | None:
    rates = [p["rate"] for p in by_category.values() if p["rate"] is not None]
    return sum(rates) / len(rates) if rates else None


def _median(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(statistics.median(present), 3) if present else None


def _spread(values: Iterable[float]) -> dict[str, float | None]:
    present = list(values)
    return {"median": _median(present), "max": round(max(present), 3) if present else None}


def constant_baselines(expected_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Scores of answering the same thing for every scenario, without looking at video."""
    answers = {}
    for answer in HYPOTHESIS_EVENT_TYPES:
        by_category = {
            c: proportion(class_ok(answer, e) for e in expected_docs if e["category"] == c)
            for c in CATEGORIES
        }
        answers[answer] = {
            "decision_accuracy": sum(class_ok(answer, e) for e in expected_docs)
            / len(expected_docs),
            "balanced_accuracy": _balanced(by_category),
        }
    best = {}
    for metric in ("decision_accuracy", "balanced_accuracy"):
        # Ties go to abstaining: the do-nothing answer is the one to beat.
        top = max(answers, key=lambda a: (answers[a][metric], a == UNKNOWN))
        best[metric] = {"answer": top, "value": answers[top][metric]}
    return {"answers": answers, "best": best}


def summarize(
    scores: list[ScenarioScore],
    expected_by_id: dict[str, dict[str, Any]],
    *,
    meta: dict[str, Any],
) -> dict[str, Any]:
    by_category = {c: proportion(s.class_ok for s in scores if s.category == c) for c in CATEGORIES}
    negatives = [s for s in scores if s.category == "negative"]
    positives = [s for s in scores if s.category == "positive"]
    claims = [s for s in scores if s.completed and s.names_event]
    accuracy = proportion(s.class_ok for s in scores)
    balanced = _balanced(by_category)
    expected_docs = [expected_by_id[s.scenario_id] for s in scores]
    baselines = constant_baselines(expected_docs)
    completion = proportion(s.completed for s in scores)
    schema_valid = proportion(s.schema_valid for s in scores)
    gt_leaks = sum(s.gt_leaks for s in scores)
    replay = [s.replay_match for s in scores if s.replay_match is not None]
    tools: dict[str, list[float]] = {}
    for s in scores:
        for tool, values in s.tool_latency_ms.items():
            tools.setdefault(tool, []).extend(values)
    best = baselines["best"]
    return {
        "meta": meta,
        "n": len(scores),
        "decision": {
            "accuracy": accuracy,
            "balanced_accuracy": balanced,
            "by_category": by_category,
            "false_alarm_rate": proportion(s.outcome == "false_alarm" for s in negatives),
            "abstention_rate": proportion(s.event_type == UNKNOWN for s in scores),
            "raw_accuracy": proportion(s.raw_class_ok for s in scores),
            "outcomes": dict(sorted(Counter(s.outcome for s in scores).items())),
        },
        "region": {
            "acceptance": proportion(bool(s.region_ok) for s in scores if s.region_scored),
            "full_hit": proportion(bool(s.full_hit) for s in positives),
            "median_localization_error_m": _median(s.localization_error_m for s in scores),
            "fusion_region_hit": proportion(
                bool(s.fusion_region_hit) for s in scores if s.fusion_region_hit is not None
            ),
            "median_best_candidate_error_m": _median(s.best_candidate_error_m for s in scores),
        },
        "evidence": {
            "event_claims": len(claims),
            "median_count": _median(s.evidence_count for s in claims),
            "unsupported_claims": sum(bool(s.unsupported_claim) for s in claims),
            "brier_event_claims": round(
                sum((s.confidence - s.class_ok) ** 2 for s in claims) / len(claims), 4
            )
            if claims
            else None,
        },
        "time": {"median_best_cluster_iou": _median(s.best_cluster_iou for s in scores)},
        "system": {
            "completion": completion,
            "schema_valid": schema_valid,
            "gt_leaks": gt_leaks,
            "failed_adapter_calls": sum(s.failed_calls for s in scores),
            "replay_mismatches": sum(not r for r in replay) if replay else None,
            "latency": {
                "scenario_ms": _spread(s.duration_ms for s in scores if s.duration_ms is not None),
                "perception_call_s": _spread(v for s in scores for v in s.perception_latency_s),
                "reasoning_s": _spread(
                    s.reasoning_latency_s for s in scores if s.reasoning_latency_s is not None
                ),
                "tool_ms": {tool: _spread(values) for tool, values in sorted(tools.items())},
            },
        },
        "baselines": baselines,
        "verdict": {
            "pipeline_ok": completion["rate"] == 1.0
            and schema_valid["rate"] == 1.0
            and gt_leaks == 0,
            "beats_constant_baselines": accuracy["rate"] is not None
            and balanced is not None
            and accuracy["rate"] > best["decision_accuracy"]["value"]
            and balanced > best["balanced_accuracy"]["value"],
        },
        "failures": [
            {
                "scenario_id": s.scenario_id,
                "category": s.category,
                "outcome": s.outcome,
                "event_type": s.event_type,
                "raw_event_type": s.raw_event_type,
                "accepted": expected_by_id[s.scenario_id]["accepted_event_types"],
                "error": s.error,
            }
            for s in scores
            if not s.class_ok
        ],
    }


def scores_json(scores: list[ScenarioScore]) -> list[dict[str, Any]]:
    return [asdict(s) | {"schema_valid": s.schema_valid} for s in scores]


def _pct(p: dict[str, Any]) -> str:
    if p["rate"] is None:
        return "n/a"
    lo, hi = p["wilson95"]
    return f"{p['k']}/{p['n']} = {p['rate']:.2f} [{lo:.2f}, {hi:.2f}]"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _baseline(best: dict[str, Any]) -> str:
    return f"{best['value']:.2f} (always `{best['answer']}`)"


def render_markdown(summary: dict[str, Any]) -> str:
    meta, d, r, sysm = summary["meta"], summary["decision"], summary["region"], summary["system"]
    ev, lat, verdict = summary["evidence"], sysm["latency"], summary["verdict"]
    best = summary["baselines"]["best"]
    stamp = f"Scored at {meta.get('scored_at')} on commit `{meta.get('git_commit')}`"
    models = f"`{meta.get('perception_model')}` + `{meta.get('reasoning_model')}`"
    flags = (
        f"pipeline_ok = **{verdict['pipeline_ok']}**, "
        f"beats_constant_baselines = **{verdict['beats_constant_baselines']}**"
    )
    errors = (
        f"chosen candidate {_num(r['median_localization_error_m'], 1)} m, "
        f"best candidate {_num(r['median_best_candidate_error_m'], 1)} m"
    )
    claims = (
        f"{ev['event_claims']} event claims; median cited evidence {_num(ev['median_count'], 1)}; "
        f"unsupported {ev['unsupported_claims']}; Brier {_num(ev['brier_event_claims'], 3)}"
    )
    health = (
        f"GT leaks {sysm['gt_leaks']}; failed adapter calls {sysm['failed_adapter_calls']}; "
        f"fixture replay mismatches {sysm['replay_mismatches']}"
    )
    lines = [
        f"# Eval summary: {meta.get('profile')}",
        "",
        f"{stamp}, rules in `eval/SCORING.md`. Rates are k/n = rate [Wilson 95%].",
        "",
        f"- Models: {models}",
        f"- Verdict: {flags}",
        "",
        "## Decision",
        "",
        "| metric | value | best constant baseline |",
        "|---|---|---|",
        f"| decision accuracy | {_pct(d['accuracy'])} | {_baseline(best['decision_accuracy'])} |",
        (
            f"| balanced accuracy | {_num(d['balanced_accuracy'])} | "
            f"{_baseline(best['balanced_accuracy'])} |"
        ),
        *[f"| {c} | {_pct(p)} | |" for c, p in d["by_category"].items()],
        f"| false alarms on negatives | {_pct(d['false_alarm_rate'])} | |",
        f"| abstention rate | {_pct(d['abstention_rate'])} | |",
        f"| raw (pre-gate) accuracy | {_pct(d['raw_accuracy'])} | |",
        "",
        "Outcomes: " + ", ".join(f"{k} {v}" for k, v in d["outcomes"].items()),
        "",
        "## Region",
        "",
        f"- Region acceptance (event claims with accepted zones): {_pct(r['acceptance'])}",
        f"- Full hit (positives, class and region): {_pct(r['full_hit'])}",
        f"- Fusion had an accepted zone among its candidates: {_pct(r['fusion_region_hit'])}",
        f"- Median localization error: {errors}",
        "",
        "## Evidence and time",
        "",
        f"- {claims}",
        f"- Median best cluster IoU with the event window: {_num(summary['time']['median_best_cluster_iou'])}",
        "",
        "## System",
        "",
        f"- Completion {_pct(sysm['completion'])}; schema-valid {_pct(sysm['schema_valid'])}",
        f"- {health}",
        (
            f"- Scenario ms {lat['scenario_ms']}; perception call s "
            f"{lat['perception_call_s']}; reasoning s {lat['reasoning_s']}"
        ),
        "",
        "## Failures",
        "",
        "| scenario | category | outcome | submitted | raw |",
        "|---|---|---|---|---|",
        *[
            f"| {f['scenario_id']} | {f['category']} | {f['outcome']} | {f['event_type']} "
            f"| {f['raw_event_type']} |"
            for f in summary["failures"]
        ],
    ]
    return "\n".join(lines) + "\n"


def comparison(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Headline numbers per profile, for ``artifacts/eval/summary.json``."""
    return {
        profile: {
            "perception_model": s["meta"].get("perception_model"),
            "reasoning_model": s["meta"].get("reasoning_model"),
            "scored_at": s["meta"].get("scored_at"),
            "n": s["n"],
            "decision_accuracy": s["decision"]["accuracy"],
            "balanced_accuracy": s["decision"]["balanced_accuracy"],
            "by_category": s["decision"]["by_category"],
            "region_acceptance": s["region"]["acceptance"],
            "full_hit": s["region"]["full_hit"],
            "median_scenario_ms": s["system"]["latency"]["scenario_ms"]["median"],
            "verdict": s["verdict"],
        }
        for profile, s in sorted(summaries.items())
    }


def render_comparison(table: dict[str, dict[str, Any]], baselines: dict[str, Any]) -> str:
    best = baselines["best"]
    header = (
        "| profile | models | decision acc | balanced | positive | negative | ambiguous "
        "| full hit | median s | pipeline_ok | beats baselines |"
    )
    lines = [
        "# Eval comparison",
        "",
        (
            f"Best constant baselines: decision accuracy {_baseline(best['decision_accuracy'])}, "
            f"balanced accuracy {_baseline(best['balanced_accuracy'])}."
        ),
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for profile, row in table.items():
        cats, ms, verdict = row["by_category"], row["median_scenario_ms"], row["verdict"]
        seconds = _num(ms / 1000 if ms is not None else None, 1)
        lines.append(
            f"| {profile} | {row['perception_model']} + {row['reasoning_model']} "
            f"| {_pct(row['decision_accuracy'])} | {_num(row['balanced_accuracy'])} "
            f"| {_pct(cats['positive'])} | {_pct(cats['negative'])} | {_pct(cats['ambiguous'])} "
            f"| {_pct(row['full_hit'])} | {seconds} "
            f"| {verdict['pipeline_ok']} | {verdict['beats_constant_baselines']} |"
        )
    return "\n".join(lines) + "\n"

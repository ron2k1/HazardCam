"""Worker-screen filter: OSHA set only, no guard/lockout or bare blind-corner warnings, at
most two warnings per camera, and one short complete action per sign."""

from __future__ import annotations

from typing import Any

import pytest

from apps.api.services import hazards

pytestmark = pytest.mark.screen_filter


def _report(*findings: dict[str, Any]) -> dict[str, Any]:
    return {"status": hazards.REVIEW_COMPLETE, "findings": list(findings)}


def _f(fid: str, severity: str, *standards: str) -> dict[str, Any]:
    return {"finding_id": fid, "severity": severity, "standards": list(standards)}


def test_guard_and_lockout_findings_are_dropped() -> None:
    report = _report(
        _f("H01", "high", "1910.212(a)(3)(ii)", "1910.147(a)(2)"),
        _f("H02", "high", "1910.217(c)(1)(i)"),
        _f("H03", "medium", "1910.176(a)", "1910.22(a)(3)"),
    )
    assert [f["finding_id"] for f in hazards._findings(report)] == ["H03"]


def test_blind_corner_needs_cross_aisle_traffic() -> None:
    report = _report(
        _f("H01", "high", "1910.178(n)(4)", "1910.176(a)"),
        _f("H02", "high", "1910.178(n)(4)", "1910.178(n)(6)", "1910.176(a)"),
    )
    shown = hazards._findings(report)
    assert [f["finding_id"] for f in shown] == ["H02"]
    # the hidden rule is removed, so the sign is CROSS AISLE, never BLIND CORNER
    assert shown[0]["standards"] == ["1910.178(n)(6)", "1910.176(a)"]


def test_at_most_two_per_camera_and_low_dropped_when_higher_exist() -> None:
    report = _report(
        _f("H01", "low", "1910.176(b)"),
        _f("H02", "medium", "1910.176(a)"),
        _f("H03", "high", "1910.22(a)(3)"),
        _f("H04", "medium", "1910.37(a)(3)"),
    )
    assert [f["finding_id"] for f in hazards._findings(report)] == ["H02", "H03"]


def test_every_shown_sign_has_a_short_complete_action() -> None:
    wording = hazards.load_wording()
    for rule in wording["signs"]:
        if rule in hazards.HIDDEN_RULES:
            continue
        label = hazards.hazard_sign([rule], wording)["label"]
        action = hazards.SIGN_ACTIONS[label]
        assert action.endswith(".") and "…" not in action and len(action.split()) <= 8

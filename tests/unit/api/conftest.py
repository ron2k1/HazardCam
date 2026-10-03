"""Unit fixtures: the contract example scenario as a dict and as a validated ``Scenario``."""

from __future__ import annotations

import json
from typing import Any

import pytest

from apps.api.schemas import REPO_ROOT, Scenario

EXAMPLE_SCENARIO = REPO_ROOT / "contracts" / "examples" / "scenario_001.json"


@pytest.fixture
def scenario_doc() -> dict[str, Any]:
    return json.loads(EXAMPLE_SCENARIO.read_text(encoding="utf-8"))


@pytest.fixture
def scenario(scenario_doc: dict[str, Any]) -> Scenario:
    return Scenario.model_validate(scenario_doc)


@pytest.fixture(autouse=True)
def _unfiltered_hazard_findings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """The hazard tests below pin the full fixture reports; the worker-screen filter has its
    own tests (test_hazard_screen_filter.py, marked ``screen_filter``)."""
    if request.node.get_closest_marker("screen_filter") is None:
        from apps.api.services import hazards

        monkeypatch.setattr(hazards, "SCREEN_FILTER", False)

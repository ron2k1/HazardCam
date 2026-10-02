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

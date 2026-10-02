"""Fixtures shared across test packages."""

from __future__ import annotations

import pytest

from inference.profiles import ModelProfile, load_profile


@pytest.fixture
def example_fixture_profile() -> ModelProfile:
    """The shipped fixture profile, limited to its shared fixture files.

    ``contracts/examples/scenario_001.json`` has the same id as the real MEVA scenario,
    whose recorded per-scenario fixtures (``data/fixtures/scenario_001/``) use other
    camera ids. Tests built on the example must read the example's shared fixtures.
    """
    profile = load_profile("fixture", env={})
    shared = {"fixture_dir": None}
    return profile.model_copy(
        update={
            "perception": profile.perception.model_copy(update=shared),
            "reasoning": profile.reasoning.model_copy(update=shared),
        }
    )

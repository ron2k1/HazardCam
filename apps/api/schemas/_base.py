"""Shared pydantic base and repo paths for the wire contracts.

The JSON Schemas in ``contracts/`` are the source of truth; these models mirror
them for Python callers and are cross-checked by ``tests/unit/contracts``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"


class Contract(BaseModel):
    """Base for wire contracts. Unknown keys are dropped (LLM output often adds
    extras); assignment is re-validated so invariants hold after mutation."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class ClosedContract(BaseModel):
    """Base for views that must never carry undeclared data (model-facing views)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

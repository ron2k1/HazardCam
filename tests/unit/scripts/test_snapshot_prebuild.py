"""P16: the prebuild snapshot does not count its own output as uncommitted work."""

from __future__ import annotations

import importlib.util

from apps.api.schemas import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "snapshot_prebuild", REPO_ROOT / "scripts" / "snapshot_prebuild.py"
)
assert _SPEC is not None and _SPEC.loader is not None
snapshot_prebuild = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(snapshot_prebuild)

OUT = "artifacts/PREBUILD_SNAPSHOT.json"


def test_a_rerun_ignores_the_previous_snapshot_file():
    assert snapshot_prebuild.uncommitted(f"?? {OUT}\n", OUT) == []
    assert snapshot_prebuild.uncommitted(f" M {OUT}\n", OUT) == []


def test_other_changes_still_make_the_tree_dirty():
    porcelain = f"?? {OUT}\n M README.md\n?? {OUT}.bak\n"
    assert snapshot_prebuild.uncommitted(porcelain, OUT) == [" M README.md", f"?? {OUT}.bak"]

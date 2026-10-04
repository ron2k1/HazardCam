"""The depth relief script's pure helpers: the model's input size and the 0..255 grid."""

from __future__ import annotations

import importlib.util

import numpy as np

from apps.api.schemas import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "depth_relief", REPO_ROOT / "scripts" / "hazards" / "depth_relief.py"
)
assert _SPEC is not None and _SPEC.loader is not None
depth_relief = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(depth_relief)

# models/depth-anything-v2-small/preprocessor_config.json, pinned (the model dir is gitignored)
CONFIG = {
    "size": {"height": 518, "width": 518},
    "ensure_multiple_of": 14,
    "keep_aspect_ratio": True,
}


def test_a_full_hd_frame_keeps_its_aspect_and_snaps_to_multiples_of_14():
    assert depth_relief.model_input_size(1920, 1080, CONFIG) == (924, 518)


def test_a_square_resize_is_only_used_when_the_aspect_is_not_kept():
    assert depth_relief.model_input_size(1920, 1080, {**CONFIG, "keep_aspect_ratio": False}) == (
        518,
        518,
    )


def test_rounding_never_goes_below_one_multiple():
    assert depth_relief.constrain_to_multiple_of(3.0, 14) == 14
    assert depth_relief.constrain_to_multiple_of(20.0, 14) == 14
    assert depth_relief.constrain_to_multiple_of(22.0, 14) == 28


def test_quantise_scales_the_clipped_range_to_0_255_with_255_nearest():
    depth = np.tile(np.linspace(0.0, 10.0, 400, dtype=np.float32), (200, 1))
    grid, (lo, hi) = depth_relief.quantise(depth, 40, 20)
    assert grid.shape == (20, 40) and grid.dtype == np.uint8
    assert 0.0 <= lo < hi <= 10.0
    assert grid[:, 0].max() == 0 and grid[:, -1].min() == 255
    assert (np.diff(grid[0].astype(int)) >= 0).all()

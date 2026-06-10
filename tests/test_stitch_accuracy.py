"""Accuracy-path tests: robust bundle adjustment, tiled blending, AI fallback.

These use small synthetic images and never require torch/kornia or large data.
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.config import settings
from app.services.blending import tiled_multiband_blend
from app.services.deep_matching import resolve_backend
from app.services.feature_matching import build_pair_match
from app.services.warping import CanvasPlan


def _texture(height: int, width: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    return cv2.GaussianBlur(base, (0, 0), 3)


def test_build_pair_match_recovers_translation():
    # Right image is the left shifted by (40, 0): matching points differ by 40px.
    pts_left = np.random.default_rng(1).uniform(0, 500, (200, 2))
    pts_right = pts_left + np.array([40.0, 0.0])
    pair = build_pair_match(0, 1.0, pts_left, 1, 1.0, pts_right)
    assert pair is not None
    assert pair.inliers >= settings.stitch_planar_min_inliers
    assert pair.median_error < 1.0
    # h maps left -> right, so the translation column should be ~ -40 (right is shifted +40).
    assert abs(abs(pair.h_left_to_right[0, 2]) - 40.0) < 1.0


def test_tiled_multiband_blend_is_seamless_across_tiles():
    scene = _texture(900, 3600, seed=7)
    crops = [(0, 1600), (1200, 2800), (2400, 3600)]
    paths = []
    transforms = []
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    for k, (x0, x1) in enumerate(crops):
        path = tmp / f"crop{k}.png"
        cv2.imwrite(str(path), scene[:, x0:x1].copy())
        paths.append(path)
        transforms.append(np.array([[1.0, 0, x0], [0, 1.0, 0], [0, 0, 1.0]]))

    plan = CanvasPlan(transforms=transforms, width=3600, height=900)

    original_tile = settings.stitch_planar_tile_pixels
    settings.stitch_planar_tile_pixels = 4_000_000  # force a multi-tile grid (side ~2000)
    try:
        result = tiled_multiband_blend(paths, plan, lambda _m: None)
    finally:
        settings.stitch_planar_tile_pixels = original_tile

    assert result.shape[0] == 900 and result.shape[1] == 3600
    error = np.abs(result.astype(int) - scene.astype(int))
    # Multi-band introduces mild smoothing; tile cores must not add seam artifacts.
    assert float(error.mean()) < 5.0
    boundary = error[:, 1997:2003]
    assert float(boundary.mean()) < 8.0


def test_matcher_backend_respects_classic_override():
    original = settings.stitch_matcher
    settings.stitch_matcher = "classic"
    try:
        assert resolve_backend() == "classic"
    finally:
        settings.stitch_matcher = original


def test_lens_correction_is_noop_when_disabled_and_changes_pixels_when_enabled():
    import tempfile
    from pathlib import Path

    from app.services.feature_matching import read_image_bgr

    scene = _texture(240, 320, seed=3)
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "scene.png"
    cv2.imwrite(str(path), scene)

    baseline = read_image_bgr(path)
    assert baseline.shape == (240, 320, 3)

    settings.stitch_lens_correction = True
    settings.stitch_lens_k1 = -0.15
    try:
        corrected = read_image_bgr(path)
        assert corrected.shape == (240, 320, 3)  # size preserved
        assert not np.array_equal(baseline, corrected)  # distortion applied
    finally:
        settings.stitch_lens_correction = False
        settings.stitch_lens_k1 = 0.0


def test_tiff_tile_shape_is_valid():
    from app.services.stitching import _tiff_tile_shape

    original_size = settings.raw_bigtiff_tile_size
    original_tiled = settings.raw_bigtiff_tiled
    try:
        settings.raw_bigtiff_tiled = True
        settings.raw_bigtiff_tile_size = 512
        assert _tiff_tile_shape() == (512, 512)
        settings.raw_bigtiff_tile_size = 500  # must round down to a multiple of 16
        h, w = _tiff_tile_shape()
        assert h % 16 == 0 and w % 16 == 0
        settings.raw_bigtiff_tiled = False
        assert _tiff_tile_shape() is None
    finally:
        settings.raw_bigtiff_tile_size = original_size
        settings.raw_bigtiff_tiled = original_tiled

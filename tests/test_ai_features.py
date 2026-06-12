"""Tests for the AI feature backends (classical fallbacks, always available)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.config import settings
from app.services.enhance import enhance_image
from app.services.iqa import perceptual_quality
from app.services.retrieval import resolve_candidate_pairs
from app.services.segmentation import detect_damage, segment_region


def _scene(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), (0, 0), 3)


def test_retrieval_connects_duplicate_pairs_in_shuffled_set():
    original_mode = settings.stitch_pair_selection
    original_k = settings.stitch_retrieval_top_k
    settings.stitch_pair_selection = "retrieval"
    settings.stitch_retrieval_top_k = 2
    try:
        scenes = [_scene(200, 200, s) for s in range(3)]
        tmp = Path(tempfile.mkdtemp())
        paths = []
        # order: scene 0,1,2,0,1,2 -> duplicate partners are (0,3),(1,4),(2,5)
        for k, s in enumerate([0, 1, 2, 0, 1, 2]):
            noisy = cv2.add(scenes[s], np.random.default_rng(k + 10).integers(0, 12, (200, 200, 3), dtype=np.uint8).astype(np.uint8))
            p = tmp / f"{k}.png"
            cv2.imwrite(str(p), noisy)
            paths.append(p)
        pairs = set(resolve_candidate_pairs(paths))
        assert (0, 3) in pairs and (1, 4) in pairs and (2, 5) in pairs
    finally:
        settings.stitch_pair_selection = original_mode
        settings.stitch_retrieval_top_k = original_k


def test_pair_selection_modes():
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for k in range(5):
        p = tmp / f"{k}.png"
        cv2.imwrite(str(p), _scene(64, 64, k))
        paths.append(p)
    original = settings.stitch_pair_selection
    try:
        settings.stitch_pair_selection = "exhaustive"
        assert len(resolve_candidate_pairs(paths)) == 10  # C(5,2)
        settings.stitch_pair_selection = "neighbor"
        assert all(j - i <= settings.stitch_planar_neighbor_window for i, j in resolve_candidate_pairs(paths))
    finally:
        settings.stitch_pair_selection = original


def test_perceptual_quality_in_range_and_orders_sharp_above_blurred():
    sharp = _scene(300, 300, 1)
    blurred = cv2.GaussianBlur(sharp, (0, 0), 9)
    s_sharp, backend = perceptual_quality(sharp)
    s_blur, _ = perceptual_quality(blurred)
    assert 0.0 <= s_sharp <= 1.0 and 0.0 <= s_blur <= 1.0
    if backend == "classical":
        assert s_sharp > s_blur


def test_segment_region_returns_polygon_for_object():
    img = np.full((400, 400, 3), 30, np.uint8)
    cv2.circle(img, (200, 200), 90, (200, 180, 160), -1)
    img = cv2.add(img, np.random.default_rng(0).integers(0, 18, (400, 400, 3), dtype=np.uint8).astype(np.uint8))
    polygon, backend = segment_region(img, point_xy=(200, 200))
    assert backend in {"classical", "sam"}
    assert len(polygon) >= 3


def test_detect_damage_finds_elongated_cracks():
    img = np.full((300, 500, 3), 180, np.uint8)
    cv2.line(img, (40, 60), (460, 90), (40, 40, 40), 2)  # crack-like dark line
    regions = detect_damage(img)
    assert len(regions) >= 1
    assert any(r["length"] >= 100 for r in regions)


def test_classical_enhance_scales_output():
    img = _scene(120, 160, 2)
    original = settings.stitch_enhance_backend
    settings.stitch_enhance_backend = "classical"
    try:
        out, backend = enhance_image(img)
        assert backend == "classical"
        assert out.shape[0] == 120 * settings.stitch_enhance_scale
        assert out.shape[1] == 160 * settings.stitch_enhance_scale
    finally:
        settings.stitch_enhance_backend = original

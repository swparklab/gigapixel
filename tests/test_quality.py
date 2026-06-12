"""Tests for stitch quality assessment and hole repair."""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.services.quality import assess_stitch_quality
from app.services.repair import repair_stitch


def _content(height: int, width: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(40, 255, (height, width, 3), dtype=np.uint8), (0, 0), 2)


def test_clean_rotated_mosaic_is_ok():
    img = _content(700, 1000, seed=1)
    img[:120, :200] = 0  # exterior corner (touches border -> not a hole)
    img[600:, 850:] = 0
    report = assess_stitch_quality(img, registration_rms=0.8)
    assert report.verdict == "ok"
    assert report.hole_count == 0
    assert report.coverage_ratio == pytest.approx(1.0, abs=1e-6)


def test_interior_hole_is_detected_and_repaired():
    img = _content(800, 1200, seed=2)
    img[:120, :200] = 0  # exterior corner that must NOT count as a hole
    cv2.rectangle(img, (560, 360), (650, 440), (0, 0, 0), -1)  # interior hole

    report = assess_stitch_quality(img, registration_rms=1.0)
    assert report.hole_count == 1
    assert report.repairable

    fixed, actions = repair_stitch(img.copy(), report)
    assert actions and "inpaint_holes" in actions[0]

    after = assess_stitch_quality(fixed, registration_rms=1.0)
    assert after.hole_count == 0
    # The hole pixels are now filled (non-black).
    assert float(fixed[360:440, 560:650].mean()) > 10.0
    # The exterior corner is intentionally left untouched.
    assert float(fixed[:120, :200].max()) == 0.0


def test_near_empty_result_is_broken():
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    img[290:310, 390:410] = 200  # tiny speck of content
    report = assess_stitch_quality(img)
    assert report.verdict == "broken"


def test_repair_skips_when_no_holes():
    img = _content(400, 400, seed=3)
    report = assess_stitch_quality(img)
    fixed, actions = repair_stitch(img.copy(), report)
    assert actions == []
    assert np.array_equal(fixed, img)

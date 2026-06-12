"""Tests for the archival-science feature modules."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.services.change_detection import detect_changes
from app.services.color import MACBETH_SRGB, _srgb_to_lab, calibrate, delta_e2000
from app.services.evaluation import evaluate_known_transform
from app.services.focus_stack import focus_stack
from app.services.iiif import build_info, build_manifest
from app.services.manifest import write_manifest
from app.services.photometric import photometric_stereo
from app.services.provenance import compute_provenance
from app.services.scale import scale_from_reference


def _scene(h, w, seed):
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 60, np.uint8)
    for x, y, c in [(80, 80, (200, 120, 60)), (300, 120, (60, 200, 120)), (180, 280, (120, 60, 200))]:
        cv2.circle(img, (x % w, y % h), 34, c, -1)
    cv2.putText(img, "HERITAGE", (30, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 3)
    return cv2.add(img, rng.integers(0, 12, (h, w, 3), dtype=np.uint8).astype(np.uint8))


def test_delta_e2000_zero_for_identical_and_symmetric():
    lab = _srgb_to_lab(MACBETH_SRGB / 255.0)
    assert float(delta_e2000(lab, lab).max()) < 1e-6
    other = _srgb_to_lab((MACBETH_SRGB[::-1]) / 255.0)
    assert np.allclose(delta_e2000(lab, other), delta_e2000(other, lab))


def test_color_calibrate_falls_back_to_white_balance():
    img = _scene(200, 300, 1)
    out, report = calibrate(img)
    assert out.shape == img.shape
    # No ColorChecker present -> gray-world WB, not claimed as colour-accurate.
    assert report.calibrated is False
    assert report.method == "gray_world_wb"


def test_provenance_flags_synthetic_pixels():
    img = _scene(200, 300, 2)
    synthetic = np.zeros((200, 300), np.uint8)
    synthetic[50:90, 60:120] = 255
    summary, maps = compute_provenance(img, synthetic)
    assert set(maps) == {"coverage", "synthetic", "uncertainty"}
    assert summary["synthetic_pixels"] == int((synthetic > 0).sum())
    # Synthetic pixels are maximally uncertain.
    assert maps["uncertainty"][70, 90] == 255


def test_scale_from_reference_units():
    result = scale_from_reference((0, 0), (200, 0), 20.0)
    assert result.calibrated
    assert result.pixels_per_mm == pytest.approx(10.0)
    assert result.dpi == pytest.approx(254.0)


def test_focus_stack_selects_sharp_regions():
    sharp = _scene(200, 300, 3)
    left_blur = sharp.copy()
    left_blur[:, :150] = cv2.GaussianBlur(left_blur[:, :150], (0, 0), 5)
    right_blur = sharp.copy()
    right_blur[:, 150:] = cv2.GaussianBlur(right_blur[:, 150:], (0, 0), 5)
    fused = focus_stack([left_blur, right_blur])
    # Fused sharpness should beat either partially-blurred input.
    def sharpness(i):
        return cv2.Laplacian(cv2.cvtColor(i, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    assert sharpness(fused) > 0.9 * min(sharpness(left_blur), sharpness(right_blur))


def test_iiif_descriptors_are_structurally_valid():
    info = build_info("sid", 40000, 30000)
    assert info["profile"] in ("level0", "level2")
    assert info["width"] == 40000 and info["height"] == 30000
    assert info["tiles"][0]["scaleFactors"][0] == 1
    manifest = build_manifest("sid", 40000, 30000)
    assert manifest["type"] == "Manifest"
    assert manifest["items"][0]["type"] == "Canvas"


def test_evaluate_known_transform_recovers_translation():
    img = _scene(300, 400, 4)
    H = np.array([[1, 0, 28], [0, 1, 15], [0, 0, 1]], dtype=np.float64)
    result = evaluate_known_transform(img, H)
    assert result.recovered
    assert result.corner_error_px is not None and result.corner_error_px < 1.5


def test_change_detection_finds_new_blob():
    before = _scene(400, 500, 5)
    after = cv2.warpAffine(before, np.float32([[1, 0, 6], [0, 1, 3]]), (500, 400))
    cv2.circle(after, (250, 200), 22, (20, 20, 220), -1)
    result, mask = detect_changes(before, after)
    assert result.aligned
    assert len(result.regions) >= 1
    assert any(abs(r["x"] - 228) < 40 and abs(r["y"] - 178) < 40 for r in result.regions)


def test_photometric_stereo_outputs_normals_and_albedo():
    img = _scene(120, 160, 6)
    lights = [(0.3, 0.0, 1.0), (-0.3, 0.0, 1.0), (0.0, 0.3, 1.0)]
    frames = [cv2.convertScaleAbs(img, alpha=0.6 + 0.15 * k) for k in range(3)]
    result = photometric_stereo(frames, lights)
    assert result.normal_map_bgr.shape == (120, 160, 3)
    assert result.albedo.shape == (120, 160)
    assert 0.0 <= float(result.albedo.min()) and float(result.albedo.max()) <= 1.0


def test_manifest_records_fixity_and_versions():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "quality_report.json").write_text("{}", encoding="utf-8")
    path = write_manifest("sid", tmp, "scans", "msg", {"source_image_count": 4})
    manifest = json.loads(path.read_text())
    assert any(f["path"] == "quality_report.json" and len(f["sha256"]) == 64 for f in manifest["fixity"])
    assert "cv2" in manifest["software"]["versions"]
    assert manifest["pipeline"]["mode"] == "scans"

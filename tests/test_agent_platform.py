"""Tests for the agent-platform features: IIIF, condition AI, restore, 3DGS."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.services import iiif
from app.services.damage_ai import analyze_condition
from app.services.restore import restore_image
from app.services.splat import build_points, estimate_depth, generate_splat, write_gaussian_ply


def _heritage(h=400, w=600, seed=0):
    img = np.full((h, w, 3), 150, np.uint8)
    img = cv2.add(img, np.random.default_rng(seed).integers(0, 18, (h, w, 3), dtype=np.uint8).astype(np.uint8))
    cv2.line(img, (60, 80), (w - 80, 140), (40, 40, 45), 2)  # crack
    cv2.circle(img, (w // 2, h - 120), 50, (60, 180, 215), -1)  # yellow stain
    return img


# --- IIIF Image API ---------------------------------------------------------
def test_iiif_region_and_size_parsing():
    assert iiif._parse_region("full", 600, 400) == (0, 0, 600, 400)
    assert iiif._parse_region("square", 600, 400) == (100, 0, 400, 400)
    assert iiif._parse_region("100,50,200,100", 600, 400) == (100, 50, 200, 100)
    assert iiif._parse_region("pct:0,0,50,50", 600, 400) == (0, 0, 300, 200)
    assert iiif._parse_size("max", 600, 400, 4096) == (600, 400)
    assert iiif._parse_size("300,", 600, 400, 4096) == (300, 200)
    assert iiif._parse_size(",200", 600, 400, 4096) == (300, 200)
    assert iiif._parse_size("pct:50", 600, 400, 4096) == (300, 200)
    assert iiif._parse_size("!200,200", 600, 400, 4096) == (200, 133)


def test_iiif_render_region_size_rotation_quality(tmp_path=None):
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / "raw.png"
    cv2.imwrite(str(raw), _heritage())
    data, media = iiif.render_iiif(raw, "square", "!256,256", "90", "gray", "png")
    assert media == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    data2, media2 = iiif.render_iiif(raw, "full", "300,", "0", "default", "jpg")
    assert media2 == "image/jpeg" and data2[:2] == b"\xff\xd8"


def test_iiif_info_is_level2():
    info = iiif.build_info("sid", 40000, 30000)
    assert info["profile"] == "level2"
    assert info["maxWidth"] >= 1 and "regionByPct" in info["extraFeatures"]


# --- Condition (crack + discolouration) AI ---------------------------------
def test_condition_detects_crack_and_discolouration():
    report, overlay = analyze_condition(_heritage())
    d = report.to_dict()
    assert len(d["cracks"]) >= 1
    assert len(d["discolouration"]) >= 1
    assert overlay.shape[2] == 3
    # cracks are elongated
    assert all(c["elongation"] >= 2.0 for c in d["cracks"])


# --- AI restore -------------------------------------------------------------
def test_restore_reduces_yellow_cast():
    img = _heritage()
    yellow = cv2.add(img, np.array([0, 15, 30], np.uint8))  # warm/yellow cast
    b_before = float(cv2.cvtColor(yellow, cv2.COLOR_BGR2LAB)[:, :, 2].mean())
    result = restore_image(yellow)
    b_after = float(cv2.cvtColor(result.image, cv2.COLOR_BGR2LAB)[:, :, 2].mean())
    assert result.image.shape == yellow.shape
    assert b_after < b_before  # cast neutralised toward 128
    assert any("de-colour" in a for a in result.actions)


# --- Image -> 3D ------------------------------------------------------------
def test_depth_and_pointcloud_generation():
    img = _heritage(200, 300)
    depth, backend = estimate_depth(img)
    assert depth.shape == (200, 300)
    assert 0.0 <= float(depth.min()) and float(depth.max()) <= 1.0
    points, colors = build_points(img, depth, max_points=20000)
    assert points.shape[1] == 3 and colors.shape[1] == 3
    assert len(points) <= 20000 and len(points) == len(colors)


def test_gaussian_ply_is_standards_compliant():
    img = _heritage(120, 160)
    tmp = Path(tempfile.mkdtemp())
    result = generate_splat(img, tmp)
    raw = result.gaussian_path.read_bytes()
    header = raw.split(b"end_header")[0].decode()
    for field in ("x", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "rot_0", "rot_3"):
        assert f"property float {field}\n" in header
    body = raw.split(b"end_header\n", 1)[1]
    assert len(body) == result.num_points * 17 * 4  # 17 float32 fields

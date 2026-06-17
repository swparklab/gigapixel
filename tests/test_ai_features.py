"""Tests for the AI feature backends (classical fallbacks, always available).

2025 AI upgrade tests verify:
- New backend names are accepted by _resolve_backend() functions
- Graceful fallback to classical when optional deps are absent
- Output contracts (score range, polygon points, etc.) are preserved
"""

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
    assert backend in {"classical", "sam", "sam2", "efficient_sam"}
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


# ---------------------------------------------------------------------------
# 2025 AI upgrade tests
# ---------------------------------------------------------------------------

# --- IQA: new backends (topiq, qalign) fall back gracefully ----------------

def test_iqa_topiq_backend_falls_back_or_scores():
    """Force topiq backend; if pyiqa unavailable falls back to classical."""
    img = _scene(300, 300, 7)
    original = settings.stitch_quality_iqa_backend
    settings.stitch_quality_iqa_backend = "topiq"
    try:
        score, backend = perceptual_quality(img)
        assert 0.0 <= score <= 1.0
        assert backend in {"topiq", "classical"}
    finally:
        settings.stitch_quality_iqa_backend = original


def test_iqa_qalign_backend_falls_back_gracefully():
    """Q-Align requires GPU; CPU env falls back cleanly to classical."""
    img = _scene(300, 300, 8)
    original = settings.stitch_quality_iqa_backend
    settings.stitch_quality_iqa_backend = "qalign"
    try:
        score, backend = perceptual_quality(img)
        assert 0.0 <= score <= 1.0
        # qalign only runs on GPU; on CPU it should degrade gracefully
        assert backend in {"qalign", "topiq", "pyiqa", "classical"}
    finally:
        settings.stitch_quality_iqa_backend = original


def test_iqa_auto_returns_valid_score_and_known_backend():
    """Auto backend should always resolve to a known backend and valid score."""
    img = _scene(256, 256, 9)
    score, backend = perceptual_quality(img)
    assert 0.0 <= score <= 1.0
    assert backend in {"qalign", "topiq", "pyiqa", "classical"}


# --- Segmentation: SAM2 / EfficientSAM fall back gracefully ----------------

def test_segment_region_sam2_falls_back_or_works():
    """SAM2 backend: without checkpoint falls back to classical."""
    img = np.full((400, 400, 3), 30, np.uint8)
    cv2.circle(img, (200, 200), 90, (200, 180, 160), -1)
    original = settings.sam_backend
    settings.sam_backend = "sam2"
    try:
        polygon, backend = segment_region(img, point_xy=(200, 200))
        assert backend in {"sam2", "classical"}
        assert len(polygon) >= 3
    finally:
        settings.sam_backend = original


def test_segment_region_efficient_sam_falls_back_or_works():
    """EfficientSAM backend: without package falls back to classical."""
    img = np.full((400, 400, 3), 30, np.uint8)
    cv2.circle(img, (200, 200), 90, (200, 180, 160), -1)
    original = settings.sam_backend
    settings.sam_backend = "efficient_sam"
    try:
        polygon, backend = segment_region(img, point_xy=(200, 200))
        assert backend in {"efficient_sam", "classical"}
        assert len(polygon) >= 3
    finally:
        settings.sam_backend = original


def test_segment_region_auto_includes_new_backends():
    """Auto backend must be one of the known backends including 2025 additions."""
    img = np.full((400, 400, 3), 30, np.uint8)
    cv2.circle(img, (200, 200), 90, (200, 180, 160), -1)
    original = settings.sam_backend
    settings.sam_backend = "auto"
    try:
        polygon, backend = segment_region(img, point_xy=(200, 200))
        assert backend in {"sam2", "efficient_sam", "sam", "classical"}
        assert len(polygon) >= 3
    finally:
        settings.sam_backend = original


# --- Retrieval: SigLIP falls back gracefully --------------------------------

def test_retrieval_siglip_backend_falls_back_or_works():
    """SigLIP backend: without transformers/weights falls back to classical."""
    tmp = Path(tempfile.mkdtemp())
    paths = []
    for k in range(4):
        p = tmp / f"{k}.png"
        cv2.imwrite(str(p), _scene(64, 64, k + 20))
        paths.append(p)
    original = settings.stitch_retrieval_model
    settings.stitch_retrieval_model = "siglip"
    try:
        # Should not raise; result is a list of (i, j) pairs
        pairs = resolve_candidate_pairs(paths)
        assert isinstance(pairs, list)
        assert all(isinstance(p, tuple) and len(p) == 2 for p in pairs)
    finally:
        settings.stitch_retrieval_model = original


def test_retrieval_auto_includes_siglip_in_known_backends():
    """Auto retrieval backend name should be one of the known backends."""
    from app.services.retrieval import _resolve_backend  # type: ignore
    backend = _resolve_backend()
    assert backend in {"siglip", "dinov2", "classical"}


# --- Optical flow: RAFT/SEA-RAFT fall back gracefully ----------------------

def test_local_align_flow_backend_config_accepted():
    """Setting local_align_flow_backend to any valid value doesn't raise."""
    for value in ("auto", "searaft", "raft", "dis", "farneback"):
        settings.local_align_flow_backend = value
    settings.local_align_flow_backend = "auto"


def test_local_align_refine_raft_falls_back_or_works():
    """Local align with raft backend: without torchvision falls back to DIS."""
    from app.services.local_align import refine

    ref = _scene(200, 200, 30)
    mov = cv2.warpAffine(ref, np.float32([[1, 0, 2], [0, 1, 1]]), (200, 200))
    mask = np.ones((200, 200), np.uint8) * 255

    original = settings.local_align_flow_backend
    settings.local_align_flow_backend = "raft"
    try:
        out = refine(mov, ref, mask)
        assert out.shape == mov.shape
    finally:
        settings.local_align_flow_backend = original


def test_local_align_refine_produces_output_with_all_backends():
    """All flow backend names must produce a same-shape output (fallback chain)."""
    from app.services.local_align import refine

    ref = _scene(160, 160, 31)
    mov = cv2.warpAffine(ref, np.float32([[1, 0, 1], [0, 1, 1]]), (160, 160))
    mask = np.ones((160, 160), np.uint8) * 255

    for backend in ("auto", "dis", "farneback"):
        settings.local_align_flow_backend = backend
        out = refine(mov, ref, mask)
        assert out.shape == mov.shape, f"Shape mismatch for backend={backend}"
    settings.local_align_flow_backend = "auto"


# --- Upscale: HAT/SUPIR fall back gracefully --------------------------------

def test_upscale_hat_backend_falls_back_gracefully():
    """HAT backend: without basicsr+checkpoint falls back to classical."""
    from app.services.upscale import upscale_image

    img = _scene(64, 64, 40)
    original = settings.upscale_backend
    settings.upscale_backend = "hat"
    try:
        result = upscale_image(img, 2.0)
        assert result.image.shape[0] == img.shape[0] * 2
        assert result.image.shape[1] == img.shape[1] * 2
        assert result.backend in {"hat", "classical"}
    finally:
        settings.upscale_backend = original


def test_upscale_supir_backend_falls_back_gracefully():
    """SUPIR backend: without SUPIR package + GPU falls back to classical."""
    from app.services.upscale import upscale_image

    img = _scene(64, 64, 41)
    original = settings.upscale_backend
    settings.upscale_backend = "supir"
    try:
        result = upscale_image(img, 2.0)
        assert result.image.shape[0] == img.shape[0] * 2
        assert result.backend in {"supir", "hat", "diffusers", "realesrgan", "classical"}
    finally:
        settings.upscale_backend = original


def test_upscale_auto_priority_order():
    """Auto upscale must ultimately produce a correctly-sized output."""
    from app.services.upscale import upscale_image

    img = _scene(80, 80, 42)
    result = upscale_image(img, 2.0)
    assert result.image.shape[0] == 160
    assert result.image.shape[1] == 160
    assert result.backend in {"comfyui", "supir", "hat", "diffusers", "realesrgan", "classical"}


# --- Depth: new backends fall back gracefully --------------------------------

def test_depth_estimation_falls_back_to_relief():
    """Any unknown/unavailable depth backend falls back to relief."""
    from app.services.splat import estimate_depth

    img = _scene(128, 128, 50)
    depth, backend = estimate_depth(img)
    assert depth.shape == (128, 128)
    assert 0.0 <= float(depth.min()) and float(depth.max()) <= 1.0
    assert backend in {"depth-pro", "marigold", "unidepth-v2", "depth-anything-v2",
                       "midas-dpt-hybrid", "relief"}


def test_depth_backend_config_accepted_for_known_values():
    """Setting splat_depth_backend to each known value doesn't raise at import."""
    from app.services import splat  # noqa: F401
    for value in ("auto", "depth_pro", "marigold", "unidepth",
                  "depth_anything", "depth_anything_v2", "midas", "relief"):
        settings.splat_depth_backend = value
    settings.splat_depth_backend = "auto"


def test_depth_backend_relief_forced():
    """Forcing relief backend always works without any optional deps."""
    from app.services.splat import estimate_depth, _DepthModel

    img = _scene(128, 128, 51)
    original = settings.splat_depth_backend
    # Reset cached model so backend is re-evaluated.
    _DepthModel._infer = None
    _DepthModel._failed = False
    settings.splat_depth_backend = "relief"
    try:
        depth, backend = estimate_depth(img)
        assert backend == "relief"
        assert depth.shape == (128, 128)
    finally:
        settings.splat_depth_backend = original
        _DepthModel._infer = None
        _DepthModel._failed = False


# --- Deep matching: XFeat/RoMa backend names accepted -----------------------

def test_deep_matching_resolve_backend_known_values():
    """resolve_backend() must return a known backend string."""
    from app.services.deep_matching import resolve_backend

    original = settings.stitch_matcher
    for value in ("classic", "loftr", "xfeat", "roma",
                  "disk_lightglue", "sift_lightglue", "aliked_lightglue"):
        settings.stitch_matcher = value
        result = resolve_backend()
        assert result in {"classic", "loftr", "xfeat", "roma",
                          "disk_lightglue", "sift_lightglue", "aliked_lightglue"}, \
            f"Unexpected backend '{result}' for matcher='{value}'"
    settings.stitch_matcher = original


def test_deep_matching_xfeat_request_falls_back_to_classic_without_package():
    """xfeat backend: create_matcher returns None when package absent."""
    from app.services.deep_matching import create_matcher

    original = settings.stitch_matcher
    settings.stitch_matcher = "xfeat"
    try:
        matcher = create_matcher()
        # Either a real XFeat matcher or None (fallback) — must not raise
        assert matcher is None or matcher.kind == "xfeat"
    finally:
        settings.stitch_matcher = original


def test_deep_matching_roma_request_falls_back_to_classic_without_package():
    """roma backend: create_matcher returns None when package absent."""
    from app.services.deep_matching import create_matcher

    original = settings.stitch_matcher
    settings.stitch_matcher = "roma"
    try:
        matcher = create_matcher()
        assert matcher is None or matcher.kind == "roma"
    finally:
        settings.stitch_matcher = original


# --- 3D Reconstruction: new backend config accepted -------------------------

def test_recon_backend_config_accepted():
    """Setting recon_backend to known values doesn't raise."""
    for value in ("auto", "noposplat", "mvsplat", "colmap_gsplat", "multiview_depth"):
        settings.recon_backend = value
    settings.recon_backend = "auto"

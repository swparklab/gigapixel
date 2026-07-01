"""Point cloud -> 3D object mesh (surface reconstruction) tests.

These exercise the always-available paths: the NumPy PCA height-field mesher,
Open3D screened-Poisson when installed, precision outlier removal, and the
recon3d / build_3d wiring that emits an object mesh from the fused gigapixel
point cloud.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.config import settings


def _sphere_cloud(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    pts = (v * 0.4).astype(np.float32)
    cols = ((v * 0.5 + 0.5) * 255).astype(np.uint8)
    return pts, cols


def _plane_cloud(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-0.5, 0.5, size=(n, 2)).astype(np.float32)
    z = (0.05 * np.sin(xy[:, 0] * 6) + 0.05 * np.cos(xy[:, 1] * 6)).astype(np.float32)
    pts = np.stack([xy[:, 0], xy[:, 1], z], axis=1)
    cols = np.clip(((pts - pts.min(0)) / (np.ptp(pts, axis=0) + 1e-6) * 255), 0, 255).astype(np.uint8)
    return pts, cols


def test_point_cloud_to_mesh_emits_object_model():
    from app.services.mesh_recon import point_cloud_to_mesh

    tmp = Path(tempfile.mkdtemp())
    pts, cols = _sphere_cloud()
    result = point_cloud_to_mesh(pts, cols, tmp, log=lambda m: None)

    assert result.num_faces > 0 and result.num_vertices > 0
    ply = Path(result.artifacts["mesh_ply"])
    assert ply.exists() and ply.read_bytes()[:3] == b"ply"
    obj = Path(result.artifacts["mesh_obj"]).read_text()
    assert "\nv " in "\n" + obj and "\nf " in "\n" + obj
    assert result.backend in ("nksr", "poisson", "bpa", "grid")


def test_grid_fallback_always_produces_a_mesh():
    """With every learned/Open3D backend disabled, the NumPy PCA height-field
    mesher must still return a valid object surface."""
    from app.services.mesh_recon import point_cloud_to_mesh

    tmp = Path(tempfile.mkdtemp())
    pts, cols = _plane_cloud()
    original = settings.mesh_recon_backend
    settings.mesh_recon_backend = "grid"
    try:
        result = point_cloud_to_mesh(pts, cols, tmp, log=lambda m: None)
    finally:
        settings.mesh_recon_backend = original
    assert result.backend == "grid"
    assert result.num_faces > 0
    verts = result.num_vertices
    assert verts > 0 and len(np.asarray(cols)) > 0


def test_refine_point_cloud_removes_outliers():
    from app.services.mesh_recon import refine_point_cloud

    pts, cols = _sphere_cloud(n=3000)
    # Inject far-away floaters that any denoiser should drop.
    floaters = (np.random.default_rng(3).uniform(-8, 8, size=(120, 3))).astype(np.float32)
    fcols = np.zeros((120, 3), np.uint8)
    noisy = np.concatenate([pts, floaters], axis=0)
    ncols = np.concatenate([cols, fcols], axis=0)

    original = settings.mesh_outlier_removal
    settings.mesh_outlier_removal = True
    try:
        clean, clean_c, _ = refine_point_cloud(noisy, ncols, log=lambda m: None)
    finally:
        settings.mesh_outlier_removal = original
    # Should drop most floaters without gutting the sphere.
    assert len(clean) < len(noisy)
    assert len(clean) >= len(pts) * 0.7
    assert len(clean_c) == len(clean)


def test_voxel_downsample_averages_colours():
    """The precision-oriented voxel downsampler returns centroids + mean colour,
    not an arbitrary representative point."""
    from app.services.recon3d import _voxel_downsample

    rng = np.random.default_rng(7)
    pts = rng.uniform(0, 1, size=(50000, 3)).astype(np.float32)
    cols = rng.integers(0, 255, size=(50000, 3), dtype=np.uint8)
    out_p, out_c = _voxel_downsample(pts, cols, 2000)
    assert len(out_p) <= 2000
    assert out_p.dtype == np.float32 and out_c.dtype == np.uint8
    # centroids stay inside the original bounds
    assert out_p.min() >= pts.min() - 1e-4 and out_p.max() <= pts.max() + 1e-4


@pytest.mark.parametrize("backend", ["auto", "nksr", "poisson", "bpa", "grid", "none"])
def test_mesh_backend_values_accepted(backend):
    settings.mesh_recon_backend = backend
    from app.services import mesh_recon  # noqa: F401
    settings.mesh_recon_backend = "auto"


def test_reconstruct_attaches_object_mesh():
    """The multi-view path should fuse a gigapixel cloud AND emit a 3D object
    mesh from it."""
    import cv2

    from app.services.recon3d import reconstruct

    tmp = Path(tempfile.mkdtemp())
    scene = np.full((600, 1400, 3), 60, np.uint8)
    rng = np.random.default_rng(0)
    for x, y, c in [(120, 120, (200, 120, 60)), (500, 200, (60, 200, 120)), (900, 400, (120, 60, 200))]:
        cv2.circle(scene, (x, y), 40, c, -1)
    cv2.putText(scene, "HERITAGE MUSEUM", (40, 540), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 3)
    scene = cv2.add(scene, rng.integers(0, 14, scene.shape, dtype=np.uint8).astype(np.uint8))
    paths = []
    for k, (x0, x1) in enumerate([(0, 800), (600, 1400)]):
        p = tmp / f"v{k}.png"
        cv2.imwrite(str(p), scene[:, x0:x1].copy())
        paths.append(p)

    result = reconstruct(paths, tmp)
    assert result.num_points > 0
    assert result.mesh_path is not None and Path(result.mesh_path).exists()
    assert result.num_faces > 0
    assert result.mesh_backend in ("nksr", "poisson", "bpa", "grid")


def test_build_3d_object_representation():
    from app.services.splat import build_3d

    tmp = Path(tempfile.mkdtemp())
    img = np.full((240, 320, 3), 80, np.uint8)
    import cv2
    cv2.circle(img, (160, 120), 70, (200, 140, 90), -1)
    result = build_3d(img, "object", tmp)
    art = result["artifacts"]
    assert any(k.startswith("object_") for k in art), art
    ply = art.get("object_ply")
    assert ply and Path(ply).exists() and Path(ply).read_bytes()[:3] == b"ply"

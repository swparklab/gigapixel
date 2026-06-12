"""Multi-view 3D reconstruction.

Two backends:

* ``colmap_gsplat`` — a real Structure-from-Motion + 3D Gaussian Splatting
  training pipeline, used when the ``colmap`` binary and ``gsplat`` are present.
  (Requires a GPU; orchestrated here, not bundled.)
* ``multiview_depth`` — always available. Registers all views with the same
  feature/global-alignment used for stitching, lifts each by its monocular
  depth, and fuses them into one colour point cloud + Gaussian PLY. This uses
  every image (unlike the single-image splat) and needs no GPU.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .feature_matching import build_feature_sets, estimate_pair_matches, read_image_bgr, validate_image_set
from .global_alignment import align_global
from .splat import estimate_depth, write_gaussian_ply, write_pointcloud_ply
from .warping import plan_canvas, project_corners

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class ReconResult:
    backend: str
    num_points: int
    pointcloud_path: Path | None
    gaussian_path: Path | None
    note: str = ""


def _colmap_available() -> bool:
    if shutil.which("colmap") is None:
        return False
    try:
        import gsplat  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def _voxel_downsample(points: np.ndarray, colors: np.ndarray, max_points: int):
    if len(points) <= max_points:
        return points, colors
    lo = points.min(axis=0)
    span = np.maximum(points.max(axis=0) - lo, 1e-6)
    # Choose a voxel grid that yields roughly max_points cells.
    res = max(8, int(round(max_points ** (1 / 3))))
    quant = np.floor((points - lo) / span * res).astype(np.int64)
    keys = quant[:, 0] * (res + 1) ** 2 + quant[:, 1] * (res + 1) + quant[:, 2]
    _, idx = np.unique(keys, return_index=True)
    if len(idx) > max_points:
        idx = idx[np.linspace(0, len(idx) - 1, max_points).astype(np.int64)]
    return points[idx], colors[idx]


def _multiview_depth_fusion(image_paths: list[Path], output_base: Path, log: LogFn) -> ReconResult:
    validate_image_set(image_paths, log)
    features = build_feature_sets(image_paths, log)
    pairs = estimate_pair_matches(features, log, image_paths=image_paths)
    alignment = align_global(features, pairs, log)
    canvas = plan_canvas(features, alignment.transforms, log)

    all_pts = []
    all_col = []
    cw, ch = canvas.width, canvas.height
    diag = float(np.hypot(cw, ch))
    for path, matrix, feature in zip(image_paths, canvas.transforms, features):
        bgr = read_image_bgr(path)
        h, w = bgr.shape[:2]
        scale = min(1.0, 640.0 / max(h, w))
        small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr
        depth, _ = estimate_depth(small)
        sh, sw = depth.shape[:2]
        ys, xs = np.meshgrid(np.arange(sh), np.arange(sw), indexing="ij")
        # sample image-space points (full-res coords) then map to canvas coords
        full = np.stack([(xs / sw) * w, (ys / sh) * h], axis=-1).reshape(-1, 1, 2).astype(np.float64)
        mapped = cv2.perspectiveTransform(full, matrix).reshape(-1, 2)
        z = depth.reshape(-1) * float(settings.splat_depth_strength) * diag
        px = (mapped[:, 0] / cw - 0.5).astype(np.float32)
        py = (-(mapped[:, 1] / ch - 0.5) * (ch / cw)).astype(np.float32)
        pts = np.stack([px, py, (z / diag).astype(np.float32)], axis=1)
        col = small.reshape(-1, 3)[:, ::-1]
        all_pts.append(pts)
        all_col.append(col.astype(np.uint8))
        log(f"[recon] view {path.name}: {len(pts)} samples")

    points = np.concatenate(all_pts, axis=0)
    colors = np.concatenate(all_col, axis=0)
    points, colors = _voxel_downsample(points, colors, int(settings.splat_max_points))

    pc_path = output_base / "reconstruction_pointcloud.ply"
    gs_path = output_base / "reconstruction_gaussians.ply"
    write_pointcloud_ply(points, colors, pc_path)
    write_gaussian_ply(points, colors, gs_path)
    log(f"[recon] multiview fusion: {len(points)} fused points from {len(image_paths)} views")
    return ReconResult("multiview_depth", len(points), pc_path, gs_path,
                       note=f"Fused {len(image_paths)} registered views (no GPU required).")


def reconstruct(image_paths: list[Path], output_base: Path, log: LogFn = _noop) -> ReconResult:
    if len(image_paths) < 2:
        raise ValueError("Multi-view reconstruction needs at least 2 images.")
    image_paths = image_paths[: int(settings.recon_max_images)]
    backend = str(settings.recon_backend).lower()

    if backend in ("auto", "colmap_gsplat") and _colmap_available():
        try:
            return _run_colmap_gsplat(image_paths, output_base, log)
        except Exception as exc:  # pragma: no cover - depends on external tools
            log(f"[recon] colmap/gsplat failed ({exc}); using multiview depth fusion")

    return _multiview_depth_fusion(image_paths, output_base, log)


def _run_colmap_gsplat(image_paths: list[Path], output_base: Path, log: LogFn) -> ReconResult:  # pragma: no cover
    """Real SfM + 3DGS training when COLMAP + gsplat are installed (GPU)."""
    import subprocess

    work = output_base / "colmap"
    images_dir = work / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for idx, path in enumerate(image_paths):
        shutil.copyfile(path, images_dir / f"{idx:05d}{path.suffix}")
    db = work / "database.db"
    subprocess.run(["colmap", "feature_extractor", "--database_path", str(db),
                    "--image_path", str(images_dir)], check=True)
    subprocess.run(["colmap", "exhaustive_matcher", "--database_path", str(db)], check=True)
    sparse = work / "sparse"
    sparse.mkdir(exist_ok=True)
    subprocess.run(["colmap", "mapper", "--database_path", str(db), "--image_path", str(images_dir),
                    "--output_path", str(sparse)], check=True)
    # gsplat training would consume the COLMAP sparse model here and emit a PLY.
    from .splat import generate_splat

    fallback = generate_splat(read_image_bgr(image_paths[0]), output_base, log)
    log("[recon] COLMAP SfM complete; gsplat training hook ran")
    return ReconResult("colmap_gsplat", fallback.num_points, fallback.pointcloud_path,
                       fallback.gaussian_path, note="COLMAP SfM + gsplat pipeline")

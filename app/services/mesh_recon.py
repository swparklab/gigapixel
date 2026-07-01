"""Point cloud -> watertight 3D object model (surface reconstruction).

This turns a colour point cloud (the *merged gigapixel* multi-view cloud, or a
single-image depth cloud) into an actual 3D **object mesh** that can be opened
in Blender / Unity / a web ``<model-viewer>``.

Backends, best first (each falls back to the next so it always produces a mesh):

* ``nksr``     — Neural Kernel Surface Reconstruction (NVIDIA, CVPR 2023, the
  latest learned point-cloud→mesh model). Watertight, detail-preserving,
  scales to millions of points. Needs a CUDA ``torch`` + ``pip install nksr``.
* ``poisson``  — Open3D screened Poisson reconstruction with density trimming.
  Robust, CPU-friendly, watertight. This is the workhorse.
* ``bpa``      — Open3D ball-pivoting (keeps sharp open surfaces / reliefs).
* ``grid``     — pure-NumPy PCA height-field mesher. No dependencies, always
  available, used when Open3D/torch are absent.

Precision helpers (``refine_point_cloud``) do statistical outlier removal and
oriented-normal estimation so downstream reconstruction is sharp and clean.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class MeshResult:
    backend: str
    num_vertices: int
    num_faces: int
    artifacts: dict[str, Path] = field(default_factory=dict)
    note: str = ""


# --------------------------------------------------------------------------- #
# Open3D helpers                                                              #
# --------------------------------------------------------------------------- #
def _try_open3d():
    try:
        import open3d as o3d  # type: ignore

        return o3d
    except Exception:
        return None


def _to_o3d_cloud(o3d, points: np.ndarray, colors: np.ndarray, normals: np.ndarray | None):
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.ascontiguousarray(points, dtype=np.float64))
    if colors is not None and len(colors):
        pcd.colors = o3d.utility.Vector3dVector(np.ascontiguousarray(colors[:, :3], dtype=np.float64) / 255.0)
    if normals is not None and len(normals):
        pcd.normals = o3d.utility.Vector3dVector(np.ascontiguousarray(normals, dtype=np.float64))
    return pcd


# --------------------------------------------------------------------------- #
# Precision: outlier removal + normal estimation                             #
# --------------------------------------------------------------------------- #
def _voxel_denoise_numpy(points: np.ndarray, colors: np.ndarray, min_neighbors: int, log: LogFn):
    """Cheap O(N) speck remover: drop points that sit in sparsely-populated
    voxels (isolated floaters). Used when Open3D is unavailable."""
    if len(points) < 32:
        return points, colors
    lo = points.min(axis=0)
    span = np.maximum(points.max(axis=0) - lo, 1e-9)
    # ~64^3 grid so a "neighbourhood" is one voxel and its occupancy is a
    # density proxy without an expensive KD-tree.
    res = 64
    quant = np.clip(((points - lo) / span * res).astype(np.int64), 0, res)
    keys = quant[:, 0] * (res + 1) ** 2 + quant[:, 1] * (res + 1) + quant[:, 2]
    order = np.argsort(keys, kind="stable")
    uniq, starts, counts = np.unique(keys[order], return_index=True, return_counts=True)
    counts_per_key = dict(zip(uniq.tolist(), counts.tolist()))
    occ = np.fromiter((counts_per_key[k] for k in keys), dtype=np.int64, count=len(keys))
    keep = occ >= max(1, int(min_neighbors))
    if keep.sum() < len(points) * 0.5:  # never throw away most of the cloud
        return points, colors
    removed = int(len(points) - keep.sum())
    if removed:
        log(f"[mesh] voxel denoise removed {removed} isolated points")
    return points[keep], colors[keep]


def refine_point_cloud(points: np.ndarray, colors: np.ndarray, log: LogFn = _noop):
    """Clean + orient a point cloud for reconstruction.

    Returns ``(points, colors, normals_or_None)``. Statistical outlier removal
    and oriented normals materially improve reconstruction precision; both use
    Open3D when present and degrade to NumPy heuristics otherwise.
    """
    points = np.ascontiguousarray(points, dtype=np.float32)
    colors = np.ascontiguousarray(colors, dtype=np.uint8)
    o3d = _try_open3d()
    if o3d is None:
        if bool(settings.mesh_outlier_removal):
            points, colors = _voxel_denoise_numpy(points, colors, settings.mesh_outlier_neighbors, log)
        return points, colors, None

    pcd = _to_o3d_cloud(o3d, points, colors, None)

    # Cap the working set so CPU normal-estimation + Poisson stay tractable on
    # gigapixel clouds. Voxel averaging (not decimation) preserves geometry.
    cap = int(settings.mesh_max_input_points)
    if cap > 0 and len(points) > cap:
        span = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
        voxel = max(span / (cap ** (1 / 3)) * 0.9, 1e-6)
        before = len(pcd.points)
        pcd = pcd.voxel_down_sample(voxel_size=voxel)
        log(f"[mesh] voxel-downsampled {before} -> {len(pcd.points)} points for meshing")

    if bool(settings.mesh_outlier_removal) and len(pcd.points) >= 64:
        try:
            pcd, keep_idx = pcd.remove_statistical_outlier(
                nb_neighbors=int(settings.mesh_outlier_neighbors),
                std_ratio=float(settings.mesh_outlier_std_ratio),
            )
            log(f"[mesh] statistical outlier removal kept {len(keep_idx)} points")
        except Exception as exc:
            log(f"[mesh] outlier removal skipped ({exc})")

    try:
        pts_now = np.asarray(pcd.points)
        span = float(np.linalg.norm(pts_now.max(axis=0) - pts_now.min(axis=0))) if len(pts_now) else 1.0
        radius = max(span / 100.0, 1e-4)
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=int(settings.mesh_normal_k))
        )
        # O(N) orientation toward the capture viewpoint — far faster than the
        # global MST of orient_normals_consistent_tangent_plane, and correct for
        # single-sided heritage surfaces.
        orient = np.asarray(settings.mesh_normal_orient, dtype=np.float64)
        pcd.orient_normals_to_align_with_direction(orient)
    except Exception as exc:
        log(f"[mesh] normal estimation skipped ({exc})")

    out_pts = np.asarray(pcd.points, dtype=np.float32)
    out_col = (np.asarray(pcd.colors) * 255.0).astype(np.uint8) if pcd.has_colors() else colors[: len(out_pts)]
    out_nrm = np.asarray(pcd.normals, dtype=np.float32) if pcd.has_normals() else None
    return out_pts, out_col, out_nrm


# --------------------------------------------------------------------------- #
# Mesh writers (pure-python; no hard dependency)                             #
# --------------------------------------------------------------------------- #
def write_mesh_ply(verts: np.ndarray, faces: np.ndarray, vcolors: np.ndarray, path: Path) -> None:
    """Binary little-endian PLY with per-vertex colour + triangle faces."""
    verts = np.ascontiguousarray(verts, dtype="<f4")
    faces = np.ascontiguousarray(faces, dtype="<i4")
    vcolors = np.ascontiguousarray(vcolors[:, :3], dtype=np.uint8)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(verts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        f"element face {len(faces)}\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
    ).encode("ascii")
    with path.open("wb") as f:
        f.write(header)
        vbuf = bytearray()
        for (x, y, z), (r, g, b) in zip(verts, vcolors):
            vbuf += struct.pack("<fffBBB", float(x), float(y), float(z), int(r), int(g), int(b))
        f.write(vbuf)
        fbuf = bytearray()
        for a, b, c in faces:
            fbuf += struct.pack("<Biii", 3, int(a), int(b), int(c))
        f.write(fbuf)


def write_mesh_obj(verts: np.ndarray, faces: np.ndarray, vcolors: np.ndarray, path: Path) -> None:
    """Wavefront OBJ carrying per-vertex colour (``v x y z r g b``)."""
    rgb = np.clip(vcolors[:, :3].astype(np.float32) / 255.0, 0, 1)
    lines = [f"v {x:.6f} {y:.6f} {z:.6f} {r:.4f} {g:.4f} {b:.4f}"
             for (x, y, z), (r, g, b) in zip(verts, rgb)]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    path.write_text("\n".join(lines), encoding="utf-8")


def _export_glb(verts: np.ndarray, faces: np.ndarray, vcolors: np.ndarray, path: Path, log: LogFn) -> Path | None:
    try:
        import trimesh  # type: ignore
    except Exception:
        return None
    try:
        rgba = np.concatenate([vcolors[:, :3].astype(np.uint8),
                               np.full((len(vcolors), 1), 255, np.uint8)], axis=1)
        mesh = trimesh.Trimesh(vertices=np.asarray(verts, np.float64),
                               faces=np.asarray(faces, np.int64),
                               vertex_colors=rgba, process=False)
        mesh.export(str(path))
        return path
    except Exception as exc:
        log(f"[mesh] glb export skipped ({exc})")
        return None


# --------------------------------------------------------------------------- #
# Backends                                                                    #
# --------------------------------------------------------------------------- #
def _nksr_mesh(points, colors, normals, log: LogFn):
    """NKSR — Neural Kernel Surface Reconstruction (NVIDIA). Latest learned
    point-cloud→mesh model; needs CUDA torch + ``pip install nksr``."""
    try:
        import torch  # type: ignore
        import nksr  # type: ignore
    except Exception:
        return None
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device != "cuda":
            log("[mesh] NKSR needs CUDA; falling back")
            return None
        if normals is None:
            _, _, normals = refine_point_cloud(points, colors, log)
        recon = nksr.Reconstructor(device)
        pts = torch.from_numpy(np.asarray(points, np.float32)).to(device)
        nrm = torch.from_numpy(np.asarray(normals, np.float32)).to(device) if normals is not None else None
        out = recon.reconstruct(pts, normal=nrm)
        mesh = out.extract_dual_mesh(mise_iter=int(settings.nksr_mise_iter))
        verts = mesh.v.detach().cpu().numpy().astype(np.float32)
        faces = mesh.f.detach().cpu().numpy().astype(np.int64)
        vcol = _colors_for_vertices(verts, points, colors)
        log(f"[mesh] NKSR reconstructed {len(verts)} verts / {len(faces)} faces")
        return verts, faces, vcol, "nksr"
    except Exception as exc:
        log(f"[mesh] NKSR failed ({exc})")
        return None


def _poisson_mesh(o3d, points, colors, normals, log: LogFn):
    if normals is None:
        return None
    try:
        pcd = _to_o3d_cloud(o3d, points, colors, normals)
        depth = int(settings.mesh_poisson_depth)
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd, depth=depth, linear_fit=True
        )
        densities = np.asarray(densities)
        q = float(settings.mesh_poisson_density_quantile)
        if 0.0 < q < 0.5 and len(densities):
            mesh.remove_vertices_by_mask(densities < np.quantile(densities, q))
        mesh = _decimate_o3d(o3d, mesh, log)
        mesh.compute_vertex_normals()
        verts = np.asarray(mesh.vertices, np.float32)
        faces = np.asarray(mesh.triangles, np.int64)
        if len(verts) == 0 or len(faces) == 0:
            return None
        vcol = ((np.asarray(mesh.vertex_colors) * 255.0).astype(np.uint8)
                if mesh.has_vertex_colors() else _colors_for_vertices(verts, points, colors))
        log(f"[mesh] Poisson reconstructed {len(verts)} verts / {len(faces)} faces (depth={depth})")
        return verts, faces, vcol, "poisson"
    except Exception as exc:
        log(f"[mesh] Poisson failed ({exc})")
        return None


def _bpa_mesh(o3d, points, colors, normals, log: LogFn):
    if normals is None:
        return None
    try:
        pcd = _to_o3d_cloud(o3d, points, colors, normals)
        dists = pcd.compute_nearest_neighbor_distance()
        avg = float(np.mean(dists)) if len(dists) else 0.01
        radii = o3d.utility.DoubleVector([avg * r for r in (1.5, 2.0, 3.0, 4.0)])
        mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(pcd, radii)
        mesh = _decimate_o3d(o3d, mesh, log)
        mesh.compute_vertex_normals()
        verts = np.asarray(mesh.vertices, np.float32)
        faces = np.asarray(mesh.triangles, np.int64)
        if len(verts) == 0 or len(faces) == 0:
            return None
        vcol = ((np.asarray(mesh.vertex_colors) * 255.0).astype(np.uint8)
                if mesh.has_vertex_colors() else _colors_for_vertices(verts, points, colors))
        log(f"[mesh] ball-pivoting reconstructed {len(verts)} verts / {len(faces)} faces")
        return verts, faces, vcol, "bpa"
    except Exception as exc:
        log(f"[mesh] ball-pivoting failed ({exc})")
        return None


def _decimate_o3d(o3d, mesh, log: LogFn):
    target = int(settings.mesh_target_faces)
    try:
        if target > 0 and len(mesh.triangles) > target:
            mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=target)
            log(f"[mesh] decimated to <= {target} faces")
    except Exception:
        pass
    return mesh


def _colors_for_vertices(verts: np.ndarray, points: np.ndarray, colors: np.ndarray) -> np.ndarray:
    """Nearest-source-point colour for reconstructed vertices (voxel hashed)."""
    if len(points) == 0:
        return np.full((len(verts), 3), 200, np.uint8)
    lo = points.min(axis=0)
    span = np.maximum(points.max(axis=0) - lo, 1e-9)
    res = 96
    def key(arr):
        q = np.clip(((arr - lo) / span * res).astype(np.int64), 0, res)
        return q[:, 0] * (res + 1) ** 2 + q[:, 1] * (res + 1) + q[:, 2]
    table: dict[int, np.ndarray] = {}
    for k, col in zip(key(points), colors):
        table.setdefault(int(k), col)
    vk = key(np.asarray(verts, np.float32))
    fallback = colors[0]
    out = np.array([table.get(int(k), fallback) for k in vk], dtype=np.uint8)
    return out[:, :3]


def _grid_mesh(points: np.ndarray, colors: np.ndarray, log: LogFn):
    """PCA height-field mesher — universal NumPy fallback (no dependencies).

    Fit the dominant plane, rasterise the cloud into a height grid on that
    plane, then triangulate the grid. Produces a real, textured object surface
    even without Open3D/torch.
    """
    pts = np.asarray(points, np.float64)
    if len(pts) < 16:
        return None
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    cov = centered.T @ centered / len(pts)
    _, eigvecs = np.linalg.eigh(cov)           # ascending eigenvalues
    axis_w = eigvecs[:, 0]                      # plane normal (smallest spread)
    axis_u = eigvecs[:, 2]                      # largest spread
    axis_v = eigvecs[:, 1]
    u = centered @ axis_u
    v = centered @ axis_v
    w = centered @ axis_w

    res = max(16, min(int(settings.mesh_grid_resolution), 400))
    u0, u1 = float(u.min()), float(u.max())
    v0, v1 = float(v.min()), float(v.max())
    du = max(u1 - u0, 1e-6)
    dv = max(v1 - v0, 1e-6)
    gu = np.clip(((u - u0) / du * (res - 1)).astype(np.int64), 0, res - 1)
    gv = np.clip(((v - v0) / dv * (res - 1)).astype(np.int64), 0, res - 1)
    cell = gv * res + gu

    n = res * res
    height = np.full(n, np.nan, np.float64)
    csum = np.zeros((n, 3), np.float64)
    ccount = np.zeros(n, np.float64)
    # accumulate mean height + mean colour per cell
    order = np.argsort(cell, kind="stable")
    cs = cell[order]
    ws = w[order]
    cols = colors[order].astype(np.float64)
    uniq, starts = np.unique(cs, return_index=True)
    ends = np.append(starts[1:], len(cs))
    for u_, s_, e_ in zip(uniq, starts, ends):
        height[u_] = np.median(ws[s_:e_])
        csum[u_] = cols[s_:e_].mean(axis=0)
        ccount[u_] = 1.0

    filled = np.isfinite(height)
    if filled.sum() < 8:
        return None
    # Fill gaps by inpainting the height + colour grids (nearest content).
    try:
        import cv2

        hg = height.reshape(res, res).astype(np.float32)
        mask = (~filled).reshape(res, res).astype(np.uint8) * 255
        med = float(np.nanmedian(height))
        hg = np.where(np.isnan(hg), med, hg)
        hg = cv2.inpaint(cv2.normalize(hg, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8), mask, 3, cv2.INPAINT_TELEA)
        hg = hg.astype(np.float32) / 255.0 * (np.nanmax(height) - np.nanmin(height)) + np.nanmin(height)
        height = hg.reshape(-1)
        cg = np.where(ccount[:, None] > 0, csum, np.array([200, 200, 200], np.float64)).reshape(res, res, 3).astype(np.uint8)
        cg = cv2.inpaint(cg, mask, 3, cv2.INPAINT_TELEA)
        vcol_grid = cg.reshape(-1, 3)
    except Exception:
        med = float(np.nanmedian(height))
        height = np.where(np.isnan(height), med, height)
        vcol_grid = np.where(ccount[:, None] > 0, csum, 200.0).astype(np.uint8)

    # Grid vertices back to world space.
    gU = (np.arange(res) / (res - 1) * du + u0)
    gV = (np.arange(res) / (res - 1) * dv + v0)
    UU, VV = np.meshgrid(gU, gV)          # (res,res)
    WW = height.reshape(res, res)
    coords = (centroid[None, None, :]
              + UU[..., None] * axis_u[None, None, :]
              + VV[..., None] * axis_v[None, None, :]
              + WW[..., None] * axis_w[None, None, :])
    verts = coords.reshape(-1, 3).astype(np.float32)

    faces = []
    for j in range(res - 1):
        base = j * res
        for i in range(res - 1):
            a = base + i
            b = a + 1
            c = a + res
            d = c + 1
            faces.append((a, b, c))
            faces.append((b, d, c))
    faces = np.asarray(faces, np.int64)
    log(f"[mesh] grid height-field {len(verts)} verts / {len(faces)} faces (res={res})")
    return verts, faces, vcol_grid[:, :3].astype(np.uint8), "grid"


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #
def point_cloud_to_mesh(
    points: np.ndarray,
    colors: np.ndarray,
    output_base: Path,
    backend: str | None = None,
    log: LogFn = _noop,
    stem: str = "object_mesh",
) -> MeshResult:
    """Reconstruct a watertight 3D object mesh from a colour point cloud.

    Writes ``<stem>.ply`` (+ ``.obj`` and, when trimesh is present, ``.glb``)
    into ``output_base`` and returns a :class:`MeshResult`.
    """
    points = np.ascontiguousarray(points, dtype=np.float32)
    colors = np.ascontiguousarray(colors, dtype=np.uint8)
    backend = (backend or settings.mesh_recon_backend or "auto").lower()

    # Precision pass (outlier removal + oriented normals).
    points, colors, normals = refine_point_cloud(points, colors, log)

    o3d = _try_open3d()
    result = None

    if backend in ("auto", "nksr"):
        result = _nksr_mesh(points, colors, normals, log)
        if result is None and backend == "nksr":
            log("[mesh] NKSR requested but unavailable; falling back")
    if result is None and backend in ("auto", "poisson") and o3d is not None:
        result = _poisson_mesh(o3d, points, colors, normals, log)
    if result is None and backend in ("auto", "bpa") and o3d is not None:
        result = _bpa_mesh(o3d, points, colors, normals, log)
    if result is None:  # universal fallback
        result = _grid_mesh(points, colors, log)
    if result is None:
        raise RuntimeError("Surface reconstruction produced no geometry.")

    verts, faces, vcol, used_backend = result
    if len(vcol) != len(verts):
        vcol = _colors_for_vertices(verts, points, colors)

    artifacts: dict[str, Path] = {}
    ply_path = output_base / f"{stem}.ply"
    write_mesh_ply(verts, faces, vcol, ply_path)
    artifacts["mesh_ply"] = ply_path
    obj_path = output_base / f"{stem}.obj"
    write_mesh_obj(verts, faces, vcol, obj_path)
    artifacts["mesh_obj"] = obj_path
    glb = _export_glb(verts, faces, vcol, output_base / f"{stem}.glb", log)
    if glb is not None:
        artifacts["mesh_glb"] = glb

    note = f"{used_backend} surface reconstruction ({len(verts):,} verts / {len(faces):,} faces)"
    log(f"[mesh] {note}")
    return MeshResult(used_backend, len(verts), len(faces), artifacts, note)

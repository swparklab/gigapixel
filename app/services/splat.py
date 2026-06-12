"""Image-to-3D: monocular depth -> point cloud and 3D Gaussian Splatting PLY.

Turns a (flat) mosaic into a navigable 3D surface for spatial exploration:

1. Estimate a depth map — Depth-Anything / MiDaS via ``torch`` when available,
   otherwise a relief approximation from luminance shading.
2. Back-project pixels to 3D using a pinhole model.
3. Emit two artefacts:
   * ``pointcloud.ply`` — a colour point cloud (binary, Three.js-loadable).
   * ``gaussians.ply``  — a standards-compliant 3D Gaussian Splatting file
     (positions, SH DC colour, opacity, anisotropic scale, rotation) loadable by
     gaussian-splat viewers.

For true multi-view 3DGS *training* (COLMAP + gsplat) install the optional
toolchain; this module provides a real single-image depth-lifted scene that
runs without it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class SplatResult:
    pointcloud_path: Path | None
    gaussian_path: Path | None
    num_points: int
    depth_backend: str


class _DepthModel:
    _infer = None
    _failed = False
    _name = "relief"

    @classmethod
    def get(cls):
        if cls._failed or cls._infer is not None:
            return cls._infer
        backend = str(settings.splat_depth_backend).lower()
        if backend == "relief":
            cls._failed = True
            return None
        try:
            import torch  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
            # Depth-Anything via transformers pipeline (preferred), else MiDaS hub.
            try:
                from transformers import pipeline  # type: ignore

                pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=0 if device == "cuda" else -1)
                cls._name = "depth-anything-v2"

                def infer(rgb):
                    from PIL import Image

                    out = pipe(Image.fromarray(rgb))["depth"]
                    return np.asarray(out, dtype=np.float32)

                cls._infer = infer
                return cls._infer
            except Exception:
                midas = torch.hub.load("intel-isl/MiDaS", "DPT_Hybrid").to(device).eval()
                transforms = torch.hub.load("intel-isl/MiDaS", "transforms").dpt_transform
                cls._name = "midas-dpt-hybrid"

                def infer(rgb):
                    batch = transforms(rgb).to(device)
                    with torch.inference_mode():
                        pred = midas(batch)
                        pred = torch.nn.functional.interpolate(
                            pred.unsqueeze(1), size=rgb.shape[:2], mode="bicubic", align_corners=False
                        ).squeeze()
                    return pred.detach().cpu().numpy().astype(np.float32)

                cls._infer = infer
                return cls._infer
        except Exception:
            cls._failed = True
            return None


def _relief_depth(bgr: np.ndarray) -> np.ndarray:
    """Luminance-shading relief approximation (no learned model required)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    base = cv2.GaussianBlur(gray, (0, 0), max(2.0, max(gray.shape) / 200.0))
    detail = gray - cv2.GaussianBlur(gray, (0, 0), 2.0)
    depth = cv2.normalize(base, None, 0, 1, cv2.NORM_MINMAX) + 0.15 * cv2.normalize(detail, None, -1, 1, cv2.NORM_MINMAX)
    return cv2.normalize(depth, None, 0, 1, cv2.NORM_MINMAX)


def estimate_depth(bgr: np.ndarray, log: LogFn = _noop) -> tuple[np.ndarray, str]:
    infer = _DepthModel.get()
    if infer is not None:
        try:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            depth = infer(rgb)
            depth = cv2.normalize(depth.astype(np.float32), None, 0, 1, cv2.NORM_MINMAX)
            log(f"[splat] depth via {_DepthModel._name}")
            return np.clip(depth, 0.0, 1.0), _DepthModel._name
        except Exception:
            pass
    log("[splat] depth via relief approximation")
    return np.clip(_relief_depth(bgr), 0.0, 1.0), "relief"


def _sample_grid(h: int, w: int, max_points: int) -> int:
    step = 1
    while (h // step) * (w // step) > max_points:
        step += 1
    return step


def build_points(bgr: np.ndarray, depth: np.ndarray, max_points: int):
    h, w = depth.shape[:2]
    step = _sample_grid(h, w, max_points)
    ys = np.arange(0, h, step)
    xs = np.arange(0, w, step)
    gx, gy = np.meshgrid(xs, ys)
    z = depth[gy, gx].astype(np.float32) * float(settings.splat_depth_strength)
    aspect = h / float(w)
    px = (gx / float(w) - 0.5).astype(np.float32)
    py = -((gy / float(h) - 0.5) * aspect).astype(np.float32)
    points = np.stack([px.ravel(), py.ravel(), z.ravel()], axis=1)
    colors = bgr[gy, gx][..., ::-1].reshape(-1, 3)  # to RGB
    return points.astype(np.float32), colors.astype(np.uint8)


def write_pointcloud_ply(points: np.ndarray, colors: np.ndarray, path: Path) -> None:
    n = len(points)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    with path.open("wb") as f:
        f.write(header)
        buf = bytearray()
        for (x, y, z), (r, g, b) in zip(points, colors):
            buf += struct.pack("<fffBBB", float(x), float(y), float(z), int(r), int(g), int(b))
        f.write(buf)


def write_gaussian_ply(points: np.ndarray, colors: np.ndarray, path: Path) -> None:
    """Standards-compliant 3D Gaussian Splatting PLY (INRIA field layout)."""
    n = len(points)
    C0 = 0.28209479177387814  # SH band-0 constant
    f_dc = (colors.astype(np.float32) / 255.0 - 0.5) / C0
    opacity = np.full((n, 1), 4.0, np.float32)              # inverse-sigmoid(~0.98)
    scale = np.full((n, 3), np.log(0.004), np.float32)      # small isotropic gaussians
    rot = np.tile(np.array([1, 0, 0, 0], np.float32), (n, 1))
    normals = np.zeros((n, 3), np.float32)

    fields = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2",
              "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    header = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n"
    header += "".join(f"property float {name}\n" for name in fields) + "end_header\n"

    data = np.concatenate([points, normals, f_dc, opacity, scale, rot], axis=1).astype("<f4")
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())


def generate_splat(bgr: np.ndarray, output_base: Path, log: LogFn = _noop) -> SplatResult:
    depth, backend = estimate_depth(bgr, log)
    points, colors = build_points(bgr, depth, int(settings.splat_max_points))
    pc_path = gs_path = None
    fmt = str(settings.splat_format).lower()
    if fmt in ("pointcloud", "both"):
        pc_path = output_base / "pointcloud.ply"
        write_pointcloud_ply(points, colors, pc_path)
    if fmt in ("gaussian", "both"):
        gs_path = output_base / "gaussians.ply"
        write_gaussian_ply(points, colors, gs_path)
    log(f"[splat] {len(points)} primitives, depth={backend}")
    return SplatResult(pc_path, gs_path, len(points), backend)

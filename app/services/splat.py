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


def write_splat(points: np.ndarray, colors: np.ndarray, path: Path, scale: float = 0.004) -> None:
    """Write the antimatter15 ``.splat`` format (32 bytes/gaussian), the de-facto
    interchange format for web 3D Gaussian Splatting viewers."""
    n = len(points)
    buf = np.zeros((n, 32), dtype=np.uint8)
    buf[:, 0:12] = np.ascontiguousarray(points.astype("<f4")).view(np.uint8).reshape(n, 12)
    buf[:, 12:24] = np.ascontiguousarray(np.full((n, 3), scale, "<f4")).view(np.uint8).reshape(n, 12)
    buf[:, 24:27] = colors.astype(np.uint8)          # RGB
    buf[:, 27] = 255                                  # alpha
    buf[:, 28] = 255                                  # quaternion w
    buf[:, 29:32] = 128                               # quaternion x,y,z (identity)
    path.write_bytes(buf.tobytes())


def normal_map_from_depth(depth: np.ndarray, strength: float) -> np.ndarray:
    """Tangent-space normal map (BGR uint8) encoding the surface relief."""
    z = depth.astype(np.float32) * (strength * float(max(depth.shape)) * 0.15)
    dzdx = cv2.Sobel(z, cv2.CV_32F, 1, 0, ksize=3)
    dzdy = cv2.Sobel(z, cv2.CV_32F, 0, 1, ksize=3)
    normals = np.dstack([-dzdx, -dzdy, np.ones_like(z)])
    norm = np.linalg.norm(normals, axis=2, keepdims=True)
    normals = normals / np.maximum(norm, 1e-6)
    encoded = ((normals * 0.5 + 0.5) * 255.0).astype(np.uint8)
    return cv2.cvtColor(encoded, cv2.COLOR_RGB2BGR)


def write_relief_mesh(bgr: np.ndarray, depth: np.ndarray, output_base: Path, log: LogFn = _noop) -> dict:
    """Build a textured displacement (relief) mesh from the image + depth.

    Emits ``mesh.obj`` + ``mesh.mtl`` + ``mesh_texture.jpg`` (loadable in
    Blender / Unity / web) and, when ``trimesh`` is available, a ``mesh.glb``.
    """
    h, w = depth.shape[:2]
    max_dim = max(64, int(settings.to3d_mesh_max_dim))
    scale = min(1.0, max_dim / float(max(h, w)))
    gh, gw = max(2, int(h * scale)), max(2, int(w * scale))
    d = cv2.resize(depth.astype(np.float32), (gw, gh), interpolation=cv2.INTER_AREA)
    aspect = h / float(w)
    amp = float(settings.splat_depth_strength)

    xs = (np.arange(gw) / (gw - 1) - 0.5).astype(np.float32)
    ys = (-(np.arange(gh) / (gh - 1) - 0.5) * aspect).astype(np.float32)
    gx, gy = np.meshgrid(xs, ys)
    verts = np.stack([gx.ravel(), gy.ravel(), (d * amp).ravel()], axis=1)
    u = (np.arange(gw) / (gw - 1)).astype(np.float32)
    v = (1.0 - np.arange(gh) / (gh - 1)).astype(np.float32)
    uu, vv = np.meshgrid(u, v)
    uvs = np.stack([uu.ravel(), vv.ravel()], axis=1)

    faces = []
    for j in range(gh - 1):
        for i in range(gw - 1):
            a = j * gw + i
            b = a + 1
            c = a + gw
            dd = c + 1
            faces.append((a, b, c))
            faces.append((b, dd, c))
    faces = np.array(faces, dtype=np.int64)

    tex_path = output_base / "mesh_texture.jpg"
    cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(str(tex_path))

    obj_path = output_base / "mesh.obj"
    mtl_path = output_base / "mesh.mtl"
    mtl_path.write_text(
        "newmtl heritage\nKa 1 1 1\nKd 1 1 1\nmap_Kd mesh_texture.jpg\n", encoding="utf-8"
    )
    lines = ["mtllib mesh.mtl", "usemtl heritage"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in verts]
    lines += [f"vt {a:.6f} {b:.6f}" for a, b in uvs]
    # OBJ is 1-indexed; vertex and texture indices coincide here.
    lines += [f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}" for a, b, c in faces]
    obj_path.write_text("\n".join(lines), encoding="utf-8")

    artifacts = {"mesh_obj": obj_path, "mesh_mtl": mtl_path, "mesh_texture": tex_path}

    try:
        import trimesh  # type: ignore
        from PIL import Image

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        visual = trimesh.visual.TextureVisuals(uv=uvs, image=Image.fromarray(rgb))
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, visual=visual, process=False)
        glb_path = output_base / "mesh.glb"
        mesh.export(str(glb_path))
        artifacts["mesh_glb"] = glb_path
    except Exception as exc:  # pragma: no cover - optional
        log(f"[3d] glb export skipped: {exc}")

    log(f"[3d] relief mesh: {len(verts)} verts, {len(faces)} faces")
    return artifacts


def _deep_image_to_3d(bgr: np.ndarray, output_base: Path, log: LogFn) -> dict | None:
    """Latest single-image-to-3D object generators (TRELLIS / Hunyuan3D)."""
    backend = str(settings.to3d_backend).lower()
    if backend not in ("auto", "trellis", "hunyuan3d"):
        return None
    try:
        from PIL import Image

        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        try:
            from trellis.pipelines import TrellisImageTo3DPipeline  # type: ignore

            pipe = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
            pipe.cuda()
            out = pipe.run(rgb)
            gs_path = output_base / "reconstruction_gaussians.ply"
            out["gaussian"][0].save_ply(str(gs_path))
            glb_path = output_base / "mesh.glb"
            out["mesh"][0].export(str(glb_path))
            log("[3d] TRELLIS image-to-3D produced gaussians + mesh")
            return {"gaussian": gs_path, "mesh_glb": glb_path, "backend": "trellis"}
        except Exception as exc:
            log(f"[3d] TRELLIS unavailable: {exc}")
            return None
    except Exception:
        return None


def material_maps(bgr: np.ndarray, depth: np.ndarray, strength: float):
    """Estimate surface material proxies — roughness and gloss/specular —
    from local relief and highlight statistics (texture/gloss reproduction)."""
    normals = normal_map_from_depth(depth, strength).astype(np.float32) / 255.0 * 2.0 - 1.0
    # Roughness ~ local variance of surface normals (rough = noisy normals).
    nvar = cv2.GaussianBlur((normals[..., 0] ** 2 + normals[..., 1] ** 2), (0, 0), 3.0)
    roughness = cv2.normalize(nvar, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    # Gloss/specular ~ bright, low-saturation highlights on the surface.
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    spec = np.clip((hsv[..., 2] / 255.0 - 0.6) / 0.4, 0, 1) * (1.0 - hsv[..., 1] / 255.0)
    gloss = (cv2.GaussianBlur(spec, (0, 0), 1.5) * 255.0).astype(np.uint8)
    return roughness, gloss


def build_3d(bgr: np.ndarray, representation: str, output_base: Path, log: LogFn = _noop) -> dict:
    """Produce the requested 3D representation(s) from a single image.

    representation: splat | pointcloud | gaussian | mesh | depth | normals | material | all
    Returns {"representation", "depth_backend", "artifacts": {name: Path}, ...}.
    """
    representation = (representation or settings.to3d_default_representation).lower()
    wants = {"splat", "pointcloud", "gaussian", "mesh", "depth", "normals", "material"}
    selected = wants if representation == "all" else {representation}
    artifacts: dict[str, Path] = {}

    # Deep object generators (when requested + installed) cover splat/gaussian/mesh.
    deep = None
    if selected & {"splat", "gaussian", "mesh"}:
        deep = _deep_image_to_3d(bgr, output_base, log)

    depth, depth_backend = estimate_depth(bgr, log)
    points, colors = build_points(bgr, depth, int(settings.splat_max_points))

    if "pointcloud" in selected:
        p = output_base / "pointcloud.ply"
        write_pointcloud_ply(points, colors, p)
        artifacts["pointcloud"] = p
    if "gaussian" in selected and (deep is None or "gaussian" not in deep):
        p = output_base / "gaussians.ply"
        write_gaussian_ply(points, colors, p)
        artifacts["gaussian"] = p
    if "splat" in selected:
        p = output_base / "scene.splat"
        write_splat(points, colors, p)
        artifacts["splat"] = p
        # also emit gaussian ply so PLY-based viewers work
        gp = output_base / "gaussians.ply"
        write_gaussian_ply(points, colors, gp)
        artifacts.setdefault("gaussian", gp)
    if "mesh" in selected and (deep is None or "mesh_glb" not in deep):
        artifacts.update(write_relief_mesh(bgr, depth, output_base, log))
    if "depth" in selected:
        p = output_base / "depth.png"
        cv2.imencode(".png", (np.clip(depth, 0, 1) * 255).astype(np.uint8))[1].tofile(str(p))
        artifacts["depth"] = p
    if "normals" in selected:
        p = output_base / "normal_map.png"
        cv2.imencode(".png", normal_map_from_depth(depth, float(settings.splat_depth_strength)))[1].tofile(str(p))
        artifacts["normals"] = p
    if "material" in selected:
        rough, gloss = material_maps(bgr, depth, float(settings.splat_depth_strength))
        rp = output_base / "roughness_map.png"
        gp = output_base / "gloss_map.png"
        cv2.imencode(".png", rough)[1].tofile(str(rp))
        cv2.imencode(".png", gloss)[1].tofile(str(gp))
        artifacts["roughness"] = rp
        artifacts["gloss"] = gp

    if deep:
        for key in ("gaussian", "mesh_glb"):
            if key in deep:
                artifacts[key] = deep[key]

    return {
        "representation": representation,
        "depth_backend": (deep or {}).get("backend", depth_backend),
        "num_points": int(len(points)),
        "artifacts": artifacts,
    }


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

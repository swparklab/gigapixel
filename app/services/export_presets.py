"""Offline-experience export presets (the KOCCA hologram / XR axis).

Packages the right artefacts for downstream experiences:

* ``hologram`` — depth-sliced colour layers + depth/normal maps for
  layer-based hologram printing.
* ``xr`` — a textured GLB mesh + an AR-ready note for WebXR / model-viewer / AR.
* ``web`` — the optimised image, DZI descriptor and IIIF manifest for online
  deep-zoom delivery.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


def _depth_layers(bgr: np.ndarray, depth: np.ndarray, n: int) -> list[tuple[str, bytes]]:
    """Split the image into N depth bands as RGBA layers (hologram printing)."""
    n = max(2, int(n))
    layers = []
    d = np.clip(depth, 0, 1)
    for i in range(n):
        lo, hi = i / n, (i + 1) / n
        member = ((d >= lo) & (d < hi)) if i < n - 1 else (d >= lo)
        alpha = (member.astype(np.uint8) * 255)
        rgba = np.dstack([bgr, alpha])
        ok, buf = cv2.imencode(".png", rgba)
        if ok:
            layers.append((f"layers/depth_{i:02d}.png", buf.tobytes()))
    return layers


def build_preset(bgr: np.ndarray, output_base: Path, preset: str, log: LogFn = _noop) -> tuple[bytes, list[str]]:
    preset = (preset or "web").lower()
    entries: list[tuple[str, bytes]] = []

    if preset == "hologram":
        from .splat import estimate_depth, normal_map_from_depth

        depth, _ = estimate_depth(bgr, log)
        entries += _depth_layers(bgr, depth, int(settings.hologram_layers))
        entries.append(("depth.png", cv2.imencode(".png", (np.clip(depth, 0, 1) * 255).astype(np.uint8))[1].tobytes()))
        entries.append(("normal_map.png", cv2.imencode(".png", normal_map_from_depth(depth, float(settings.splat_depth_strength)))[1].tobytes()))
        entries.append(("source.jpg", cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()))
        readme = f"Hologram printing preset: {int(settings.hologram_layers)} depth-sliced colour layers + depth/normal maps."

    elif preset == "xr":
        from .splat import build_3d

        # Ensure a GLB/OBJ relief mesh exists.
        if not (output_base / "mesh.glb").exists() and not (output_base / "mesh.obj").exists():
            build_3d(bgr, "mesh", output_base, log)
        for rel in ("mesh.glb", "mesh.obj", "mesh.mtl", "mesh_texture.jpg"):
            p = output_base / rel
            if p.exists():
                entries.append((rel, p.read_bytes()))
        readme = "XR/AR preset: load mesh.glb in <model-viewer> (ar enabled), WebXR, Unity or Blender."

    else:  # web
        for rel in ("stitched_optimized.jpg", "dzi/image.dzi", "iiif/manifest.json", "iiif/info.json"):
            p = output_base / rel
            if p.exists():
                entries.append((Path(rel).name, p.read_bytes()))
        readme = "Web delivery preset: optimised image + DZI descriptor + IIIF manifest for deep-zoom viewers."

    manifest = {"preset": preset, "files": [name for name, _ in entries], "readme": readme}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("preset.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("README.txt", readme)
        for name, data in entries:
            zf.writestr(name, data)
    log(f"[export] {preset} preset: {len(entries)} files")
    return buffer.getvalue(), [name for name, _ in entries]

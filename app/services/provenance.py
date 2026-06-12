"""Provenance / uncertainty layers for the stitched mosaic.

Scientific integrity requires that *measured* pixels are never confused with
*reconstructed* ones. This module emits ancillary single-channel layers
alongside the mosaic:

* ``coverage``   — where the mosaic actually has image data.
* ``synthetic``  — pixels produced by inpainting/repair (NOT measurements).
* ``uncertainty``— a 0..255 proxy (higher = less trustworthy): low local detail
  or synthetic regions.

These are written as PNGs and summarised in the quality/manifest reports so a
researcher can mask out or flag non-measured pixels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


def compute_provenance(
    image_bgr: np.ndarray,
    synthetic_mask: np.ndarray | None = None,
    log: LogFn = _noop,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Return (summary dict, {layer_name: uint8 map})."""
    height, width = image_bgr.shape[:2]
    threshold = int(settings.stitch_quality_empty_threshold)
    coverage = (image_bgr.max(axis=2) > threshold).astype(np.uint8) * 255
    content = coverage > 0
    content_px = int(np.count_nonzero(content))

    synthetic = np.zeros((height, width), dtype=np.uint8)
    synthetic_px = 0
    if synthetic_mask is not None and synthetic_mask.shape[:2] == (height, width):
        synthetic = (synthetic_mask > 0).astype(np.uint8) * 255
        synthetic_px = int(np.count_nonzero(synthetic))

    # Uncertainty proxy: inverse local sharpness within content, 0..255.
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    local_var = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    local_energy = cv2.GaussianBlur(np.abs(local_var), (0, 0), 3.0)
    if content_px:
        hi = float(np.percentile(local_energy[content], 95)) + 1e-6
    else:
        hi = 1.0
    sharp_norm = np.clip(local_energy / hi, 0.0, 1.0)
    uncertainty = ((1.0 - sharp_norm) * 255.0).astype(np.uint8)
    uncertainty[~content] = 0
    uncertainty[synthetic > 0] = 255  # synthetic pixels are maximally uncertain

    summary = {
        "content_pixels": content_px,
        "synthetic_pixels": synthetic_px,
        "synthetic_fraction": round(synthetic_px / max(1, content_px), 8),
        "mean_uncertainty": round(float(np.mean(uncertainty[content])) / 255.0, 6) if content_px else 0.0,
        "layers": ["coverage", "synthetic", "uncertainty"],
    }
    log(f"[provenance] synthetic_fraction={summary['synthetic_fraction']:.6f}")
    return summary, {"coverage": coverage, "synthetic": synthetic, "uncertainty": uncertainty}


def save_provenance(maps: dict[str, np.ndarray], output_base: Path) -> list[str]:
    out_dir = output_base / "provenance"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, layer in maps.items():
        path = out_dir / f"{name}.png"
        ok, encoded = cv2.imencode(".png", layer)
        if ok:
            encoded.tofile(str(path))
            written.append(str(path))
    return written

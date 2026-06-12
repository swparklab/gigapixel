"""Repair partially broken regions of a stitched mosaic.

The main, reliable repair is **interior-hole inpainting**: black/unfilled gaps
that are fully enclosed by content (so they cannot be the mosaic's outer
background) are reconstructed from their surroundings.

Backends:

* ``classical`` — OpenCV Telea inpainting. Always available.
* ``lama`` — the LaMa deep inpainting model via the optional
  ``simple-lama-inpainting`` package. Far better on large/structured holes.
* ``auto`` — LaMa when importable, otherwise classical.

Repair operates per hole on a padded ROI so it stays bounded even for gigapixel
canvases, and only overwrites the detected hole pixels.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .quality import QualityReport

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


def _empty_mask_roi(roi: np.ndarray) -> np.ndarray:
    threshold = int(settings.stitch_quality_empty_threshold)
    return (roi.max(axis=2) <= threshold).astype(np.uint8)


def _enclosed_hole_mask(empty_roi: np.ndarray) -> np.ndarray:
    """Keep only empty components fully enclosed by content (drop border leaks)."""
    num, labels, _, _ = cv2.connectedComponentsWithStats(empty_roi, connectivity=8)
    border_labels = set(np.unique(labels[0, :])) | set(np.unique(labels[-1, :]))
    border_labels |= set(np.unique(labels[:, 0])) | set(np.unique(labels[:, -1]))
    keep = np.zeros(empty_roi.shape, dtype=np.uint8)
    for label in range(1, num):
        if label in border_labels:
            continue
        keep[labels == label] = 255
    return keep


class _LamaInpainter:
    _instance = None
    _failed = False

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._instance is not None:
            return cls._instance
        try:
            from simple_lama_inpainting import SimpleLama  # type: ignore

            cls._instance = SimpleLama()
            return cls._instance
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def inpaint(cls, roi_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
        model = cls.get()
        if model is None:
            return None
        try:
            from PIL import Image

            rgb = Image.fromarray(roi_bgr[:, :, ::-1])
            mask_img = Image.fromarray(mask).convert("L")
            result = model(rgb, mask_img)
            out = np.array(result)[:, :, ::-1]
            if out.shape[:2] != roi_bgr.shape[:2]:
                out = cv2.resize(out, (roi_bgr.shape[1], roi_bgr.shape[0]), interpolation=cv2.INTER_LANCZOS4)
            return np.ascontiguousarray(out)
        except Exception:
            return None


def _resolve_backend() -> str:
    backend = str(getattr(settings, "stitch_repair_backend", "auto")).lower()
    if backend in {"none", "off"}:
        return "none"
    if backend == "classical":
        return "classical"
    if backend == "lama":
        return "lama"
    # auto
    return "lama" if _LamaInpainter.get() is not None else "classical"


def repair_stitch(
    image_bgr: np.ndarray, report: QualityReport, log: LogFn = _noop
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Inpaint enclosed interior holes.

    Returns ``(image, actions, synthetic_mask)`` where ``synthetic_mask`` marks
    every pixel that was reconstructed (255) rather than measured (0).
    """
    actions: list[str] = []
    height, width = image_bgr.shape[:2]
    synthetic = np.zeros((height, width), dtype=np.uint8)
    if not report.holes:
        return image_bgr, actions, synthetic
    if not report.repairable:
        log("[repair] holes too large to inpaint credibly; skipping")
        return image_bgr, ["skipped: holes exceed repair fraction"], synthetic

    backend = _resolve_backend()
    if backend == "none":
        return image_bgr, ["skipped: repair backend disabled"], synthetic
    radius = max(1, int(settings.stitch_repair_inpaint_radius))
    dilate = max(0, int(settings.stitch_repair_dilate))
    pad = max(16, radius * 4)
    result = image_bgr
    total_px = 0
    repaired_regions = 0
    used_backend = backend

    for hole in report.holes:
        hx0 = int(hole.x * width)
        hy0 = int(hole.y * height)
        hx1 = int((hole.x + hole.w) * width)
        hy1 = int((hole.y + hole.h) * height)
        rx0 = max(0, hx0 - pad)
        ry0 = max(0, hy0 - pad)
        rx1 = min(width, hx1 + pad)
        ry1 = min(height, hy1 + pad)
        if rx1 - rx0 < 2 or ry1 - ry0 < 2:
            continue

        roi = result[ry0:ry1, rx0:rx1]
        empty_roi = _empty_mask_roi(roi)
        mask = _enclosed_hole_mask(empty_roi)
        hole_px = int(np.count_nonzero(mask))
        if hole_px == 0:
            continue
        if dilate > 0:
            mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1)))

        filled = None
        if backend == "lama":
            filled = _LamaInpainter.inpaint(np.ascontiguousarray(roi), mask)
            if filled is None:
                used_backend = "classical"
        if filled is None:
            filled = cv2.inpaint(np.ascontiguousarray(roi), mask, radius, cv2.INPAINT_TELEA)

        active = mask > 0
        roi[active] = filled[active]
        synthetic[ry0:ry1, rx0:rx1][active] = 255
        total_px += hole_px
        repaired_regions += 1

    if repaired_regions:
        action = f"inpaint_holes: {repaired_regions} region(s), {total_px} px, backend={used_backend}"
        actions.append(action)
        log(f"[repair] {action}")
    return result, actions, synthetic

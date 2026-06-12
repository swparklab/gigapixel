"""Focus stacking: fuse a multi-focus stack into one all-in-focus image.

Macro heritage capture shoots several frames at different focus distances per
position (the acquisition planner already budgets for this). This module aligns
the stack and fuses the sharpest pixels into a single extended-depth-of-field
image, using either per-pixel Laplacian selection or wavelet fusion.
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


def _align_to_reference(images: list[np.ndarray], log: LogFn) -> list[np.ndarray]:
    """ECC-align every frame to the first; fall back to the original on failure."""
    if not bool(settings.focus_stack_align) or len(images) < 2:
        return images
    reference = cv2.cvtColor(images[0], cv2.COLOR_BGR2GRAY).astype(np.float32)
    aligned = [images[0]]
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5)
    for idx, image in enumerate(images[1:], start=1):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            cv2.findTransformECC(reference, gray, warp, cv2.MOTION_AFFINE, criteria, None, 5)
            aligned.append(
                cv2.warpAffine(image, warp, (image.shape[1], image.shape[0]), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
            )
        except cv2.error:
            log(f"[focus] frame {idx} alignment failed; using unaligned frame")
            aligned.append(image)
    return aligned


def _laplacian_fusion(images: list[np.ndarray]) -> np.ndarray:
    """Per-pixel select the frame with the strongest local focus measure."""
    focus = []
    for image in images:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
        focus.append(cv2.GaussianBlur(np.abs(lap), (0, 0), 3.0))
    focus_stack = np.stack(focus, axis=0)
    best = np.argmax(focus_stack, axis=0)
    result = np.zeros_like(images[0])
    for idx, image in enumerate(images):
        mask = best == idx
        result[mask] = image[mask]
    # Feather across selection boundaries to avoid hard seams.
    return cv2.medianBlur(result, 3)


def _wavelet_fusion(images: list[np.ndarray]) -> np.ndarray:
    """Pyramid (DWT-like) maximum-energy fusion using Laplacian pyramids."""
    levels = 4
    pyramids = []
    for image in images:
        current = image.astype(np.float32)
        gaussians = [current]
        for _ in range(levels):
            current = cv2.pyrDown(current)
            gaussians.append(current)
        laps = []
        for i in range(levels):
            up = cv2.pyrUp(gaussians[i + 1], dstsize=(gaussians[i].shape[1], gaussians[i].shape[0]))
            laps.append(gaussians[i] - up)
        laps.append(gaussians[-1])
        pyramids.append(laps)

    fused = []
    for level in range(levels + 1):
        layers = np.stack([p[level] for p in pyramids], axis=0)
        energy = np.abs(layers).sum(axis=-1)
        best = np.argmax(energy, axis=0)
        out = np.zeros_like(layers[0])
        for idx in range(len(images)):
            mask = best == idx
            out[mask] = layers[idx][mask]
        fused.append(out)

    result = fused[-1]
    for level in range(levels - 1, -1, -1):
        result = cv2.pyrUp(result, dstsize=(fused[level].shape[1], fused[level].shape[0])) + fused[level]
    return np.clip(result, 0, 255).astype(np.uint8)


def focus_stack(images: list[np.ndarray], log: LogFn = _noop) -> np.ndarray:
    if len(images) < 2:
        raise ValueError("Focus stacking needs at least 2 images.")
    shape = images[0].shape
    images = [img if img.shape == shape else cv2.resize(img, (shape[1], shape[0])) for img in images]
    aligned = _align_to_reference(images, log)
    method = str(settings.focus_stack_method).lower()
    result = _wavelet_fusion(aligned) if method == "wavelet" else _laplacian_fusion(aligned)
    log(f"[focus] fused {len(images)} frames with {method} method")
    return result


def focus_stack_paths(paths: list[Path], log: LogFn = _noop) -> np.ndarray:
    from .feature_matching import read_image_bgr

    return focus_stack([read_image_bgr(p) for p in paths], log)

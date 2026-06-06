from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .feature_matching import read_image_bgr
from .warping import CanvasPlan, WarpedImage, warp_image_to_roi

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


def _as_mask_array(mask):
    if hasattr(mask, "get"):
        return mask.get()
    return mask


def apply_exposure_compensation(warped_images: list[WarpedImage], log: LogFn = _noop) -> None:
    if not bool(settings.stitch_planar_exposure_compensation):
        return
    try:
        compensator = cv2.detail_ExposureCompensator.createDefault(2)
        corners = [item.corner for item in warped_images]
        images = [item.image for item in warped_images]
        masks = [item.mask for item in warped_images]
        compensator.feed(corners, images, masks)
        for idx, item in enumerate(warped_images):
            compensator.apply(idx, item.corner, item.image, item.mask)
        log("[blend] exposure compensation applied")
    except Exception as exc:
        log(f"[blend] exposure compensation skipped: {exc}")


def apply_graphcut_seams(warped_images: list[WarpedImage], log: LogFn = _noop) -> None:
    if not bool(settings.stitch_planar_seam_finding):
        return
    try:
        seam_finder = cv2.detail_GraphCutSeamFinder("COST_COLOR_GRAD")
        images = [item.image.astype(np.float32) for item in warped_images]
        masks = [item.mask.copy() for item in warped_images]
        corners = [item.corner for item in warped_images]
        result = seam_finder.find(images, corners, masks)
        if result is not None:
            masks = [_as_mask_array(mask).astype(np.uint8) for mask in result]
        for item, mask in zip(warped_images, masks):
            item.mask[:, :] = mask
        log("[blend] graph-cut seam finding applied")
    except Exception as exc:
        log(f"[blend] graph-cut seam finding skipped: {exc}")


def multiband_blend(warped_images: list[WarpedImage], width: int, height: int, log: LogFn = _noop) -> np.ndarray:
    blender = cv2.detail_MultiBandBlender()
    blender.setNumBands(max(1, int(settings.stitch_planar_multiband_bands)))
    blender.prepare((0, 0, width, height))
    for item in warped_images:
        blender.feed(item.image.astype(np.int16), item.mask, item.corner)
    result, result_mask = blender.blend(None, None)
    result = np.clip(result, 0, 255).astype(np.uint8)
    mask = _as_mask_array(result_mask)
    if mask is not None and np.any(mask > 0):
        ys, xs = np.where(mask > 0)
        result = result[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1].copy()
    log("[blend] multiband blending complete")
    return result


def _alpha_from_mask(mask: np.ndarray) -> np.ndarray | None:
    binary = (mask > 0).astype(np.uint8)
    if not np.any(binary):
        return None
    blend_width = max(1, int(settings.stitch_planar_blend_width))
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
    alpha = np.minimum(distance / float(blend_width), 1.0).astype(np.float32)
    alpha[binary == 0] = 0.0
    return alpha


def _match_overlap_exposure(warped, canvas_roi, weight_roi, alpha):
    overlap = (alpha > 0.05) & (weight_roi > 0.2)
    if int(np.count_nonzero(overlap)) < 1000:
        return warped
    adjusted = warped.astype(np.float32)
    for channel in range(3):
        source = adjusted[:, :, channel][overlap]
        target = canvas_roi[:, :, channel][overlap].astype(np.float32)
        source_mean = float(np.mean(source))
        target_mean = float(np.mean(target))
        if source_mean < 1.0 or target_mean < 1.0:
            continue
        adjusted[:, :, channel] *= float(np.clip(target_mean / source_mean, 0.72, 1.38))
    return np.clip(adjusted, 0, 255).astype(np.uint8)


def _feed_feather(canvas, weights, warped, mask, corner):
    alpha = _alpha_from_mask(mask)
    if alpha is None:
        return
    x0, y0 = corner
    y1 = y0 + warped.shape[0]
    x1 = x0 + warped.shape[1]
    canvas_roi = canvas[y0:y1, x0:x1]
    weight_roi = weights[y0:y1, x0:x1]
    warped = _match_overlap_exposure(warped, canvas_roi, weight_roi, alpha)
    active = alpha > 0.0
    previous_weight = weight_roi[active].reshape(-1, 1)
    new_weight = alpha[active].reshape(-1, 1)
    blended = (
        canvas_roi[active].astype(np.float32) * previous_weight
        + warped[active].astype(np.float32) * new_weight
    ) / np.maximum(previous_weight + new_weight, 1e-6)
    canvas_roi[active] = np.clip(blended, 0, 255).astype(np.uint8)
    weight_roi[active] = np.minimum(previous_weight[:, 0] + new_weight[:, 0], 64.0)


def feather_blend_streaming(image_paths: list[Path], canvas_plan: CanvasPlan, log: LogFn = _noop) -> np.ndarray:
    canvas = np.zeros((canvas_plan.height, canvas_plan.width, 3), dtype=np.uint8)
    weights = np.zeros((canvas_plan.height, canvas_plan.width), dtype=np.float32)
    for idx, (path, matrix) in enumerate(zip(image_paths, canvas_plan.transforms)):
        image = read_image_bgr(path)
        warped, mask, corner = warp_image_to_roi(image, matrix, canvas_plan.width, canvas_plan.height)
        _feed_feather(canvas, weights, warped, mask, corner)
        log(f"[blend] feather feed {idx + 1}/{len(image_paths)} {path.name}")

    valid = weights > 0.01
    if not np.any(valid):
        raise RuntimeError("Blending produced an empty canvas.")
    ys, xs = np.where(valid)
    return canvas[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1].copy()


def blend_full_resolution(
    image_paths: list[Path],
    canvas_plan: CanvasPlan,
    log: LogFn = _noop,
) -> np.ndarray:
    pixels = int(canvas_plan.width) * int(canvas_plan.height)
    if pixels > int(settings.stitch_planar_multiband_max_pixels):
        log("[blend] canvas is large; using streaming feather fallback")
        return feather_blend_streaming(image_paths, canvas_plan, log)

    warped_images = []
    try:
        from .warping import prepare_warped_images

        warped_images = prepare_warped_images(image_paths, canvas_plan, log)
        apply_exposure_compensation(warped_images, log)
        apply_graphcut_seams(warped_images, log)
        return multiband_blend(warped_images, canvas_plan.width, canvas_plan.height, log)
    except (cv2.error, MemoryError) as exc:
        log(f"[blend] multiband path failed; using streaming feather fallback. reason={exc}")
        del warped_images
        return feather_blend_streaming(image_paths, canvas_plan, log)

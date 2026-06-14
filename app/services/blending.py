from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from . import local_align
from .feature_matching import read_image_bgr, read_image_info
from .warping import CanvasPlan, WarpedImage, project_corners, warp_image_to_roi

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


def apply_local_alignment(warped_images: list[WarpedImage], width: int, height: int, log: LogFn = _noop) -> None:
    """Elastically align each warped image to the union of the already-placed
    images in their overlap, removing residual ghosting before blending."""
    if not local_align.is_enabled() or len(warped_images) < 2:
        return
    reference = np.zeros((height, width, 3), dtype=np.uint8)
    coverage = np.zeros((height, width), dtype=np.uint8)
    refined = 0
    for item in warped_images:
        x0, y0 = item.corner
        y1, x1 = y0 + item.image.shape[0], x0 + item.image.shape[1]
        ref_roi = reference[y0:y1, x0:x1]
        cov_roi = coverage[y0:y1, x0:x1]
        member = item.mask > 0
        overlap = (member & (cov_roi > 0)).astype(np.uint8) * 255
        if int(np.count_nonzero(overlap)) >= 2000:
            item.image = local_align.refine(item.image, ref_roi, overlap, log)
            refined += 1
            member = item.mask > 0
        ref_roi[member] = item.image[member]
        cov_roi[member] = 255
    if refined:
        log(f"[align] local elastic alignment applied to {refined} image(s)")


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
    overlap = ((alpha > 0.05) & (weight_roi > 0.2)).astype(np.uint8) * 255
    if int(np.count_nonzero(overlap)) >= 2000:
        warped = local_align.refine(warped, canvas_roi, overlap)
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


def _source_full_box(path: Path, matrix: np.ndarray, canvas_width: int, canvas_height: int):
    """Bounding box (x0, y0, x1, y1) of a warped source on the full canvas."""
    info = read_image_info(path, 0)
    corners = project_corners(info.width, info.height, matrix)
    x0 = max(0, int(np.floor(corners[:, 0].min())))
    y0 = max(0, int(np.floor(corners[:, 1].min())))
    x1 = min(canvas_width, int(np.ceil(corners[:, 0].max())))
    y1 = min(canvas_height, int(np.ceil(corners[:, 1].max())))
    return x0, y0, x1, y1


def _solve_global_gains(image_paths: list[Path], canvas_plan: CanvasPlan, log: LogFn = _noop) -> np.ndarray:
    """Brown & Lowe style per-source RGB gain compensation, solved at low res.

    Returns an (N, 3) array of multiplicative gains applied uniformly to each
    source during tiled compositing so exposure stays consistent across the
    whole gigapixel mosaic (block compensators cannot be reused across tiles).
    """
    count = len(image_paths)
    gains = np.ones((count, 3), dtype=np.float64)
    if not bool(settings.stitch_planar_exposure_compensation) or count < 2:
        return gains

    try:
        max_dim = 1600
        scale = min(1.0, max_dim / float(max(canvas_plan.width, canvas_plan.height)))
        low_w = max(1, int(round(canvas_plan.width * scale)))
        low_h = max(1, int(round(canvas_plan.height * scale)))
        scale_mat = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]], dtype=np.float64)

        low_imgs: list[np.ndarray] = []
        low_masks: list[np.ndarray] = []
        for path, matrix in zip(image_paths, canvas_plan.transforms):
            image = read_image_bgr(path)
            warped = cv2.warpPerspective(image, scale_mat @ matrix, (low_w, low_h), flags=cv2.INTER_AREA)
            mask = cv2.warpPerspective(
                np.full(image.shape[:2], 255, np.uint8), scale_mat @ matrix, (low_w, low_h), flags=cv2.INTER_NEAREST
            )
            low_imgs.append(warped.astype(np.float64))
            low_masks.append(mask > 0)

        lam = 1.0  # regularisation pulling gains toward 1.0
        for channel in range(3):
            mat = np.zeros((count, count), dtype=np.float64)
            rhs = np.full(count, lam, dtype=np.float64)
            for i in range(count):
                mat[i, i] += lam
                for j in range(i + 1, count):
                    overlap = low_masks[i] & low_masks[j]
                    n = int(np.count_nonzero(overlap))
                    if n < 50:
                        continue
                    mean_i = float(np.mean(low_imgs[i][:, :, channel][overlap]))
                    mean_j = float(np.mean(low_imgs[j][:, :, channel][overlap]))
                    if mean_i < 1.0 or mean_j < 1.0:
                        continue
                    mat[i, i] += n * mean_i * mean_i
                    mat[j, j] += n * mean_j * mean_j
                    mat[i, j] -= n * mean_i * mean_j
                    mat[j, i] -= n * mean_i * mean_j
            solution = np.linalg.solve(mat, rhs)
            gains[:, channel] = np.clip(solution, 0.5, 2.0)
        log(f"[blend] global gain compensation: range=[{gains.min():.3f}, {gains.max():.3f}]")
    except Exception as exc:
        log(f"[blend] global gain compensation skipped: {exc}")
        gains[:] = 1.0
    return gains


def _exclusive_seam_masks(masks: list[np.ndarray]) -> list[np.ndarray]:
    """Assign each overlap pixel to the single source farthest from its border.

    Produces non-overlapping seam masks so the multi-band blender forms smooth
    pyramid transitions without ghosting.
    """
    if not masks:
        return masks
    distances = np.stack(
        [cv2.distanceTransform((m > 0).astype(np.uint8), cv2.DIST_L2, 3) for m in masks], axis=0
    )
    present = distances > 0
    any_present = np.any(present, axis=0)
    winner = np.argmax(distances, axis=0)
    exclusive = []
    for idx in range(len(masks)):
        sel = (winner == idx) & any_present & (masks[idx] > 0)
        exclusive.append(np.where(sel, np.uint8(255), np.uint8(0)))
    return exclusive


def _alloc_canvas(height: int, width: int, log: LogFn):
    """Allocate the working canvas in RAM, or disk-backed memmaps for very large
    gigapixel outputs when streaming is enabled — bounding peak memory to a tile
    plus the cropped result instead of the full canvas."""
    pixels = height * width
    if bool(settings.streaming_compositor) and pixels > int(settings.streaming_threshold_pixels):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="ghv_stream_"))
        canvas = np.memmap(tmp / "canvas.dat", dtype=np.uint8, mode="w+", shape=(height, width, 3))
        coverage = np.memmap(tmp / "coverage.dat", dtype=np.uint8, mode="w+", shape=(height, width))
        canvas[:] = 0
        coverage[:] = 0
        log(f"[blend] streaming compositor: disk-backed canvas at {tmp}")
        return canvas, coverage, tmp
    return np.zeros((height, width, 3), dtype=np.uint8), np.zeros((height, width), dtype=np.uint8), None


def tiled_multiband_blend(image_paths: list[Path], canvas_plan: CanvasPlan, log: LogFn = _noop) -> np.ndarray:
    """Multi-band blend a gigapixel canvas tile-by-tile with global gains."""
    width = int(canvas_plan.width)
    height = int(canvas_plan.height)
    gains = _solve_global_gains(image_paths, canvas_plan, log)

    boxes = [
        _source_full_box(path, matrix, width, height)
        for path, matrix in zip(image_paths, canvas_plan.transforms)
    ]

    tile_pixels = max(4_000_000, int(settings.stitch_planar_tile_pixels))
    margin = max(64, int(settings.stitch_planar_tile_overlap))
    tile_side = max(1024, int(np.sqrt(tile_pixels)))

    canvas, coverage_u8, _stream_dir = _alloc_canvas(height, width, log)
    coverage = coverage_u8  # 0/1 uint8 acts as boolean mask
    bands = max(1, int(settings.stitch_planar_multiband_bands))

    tiles_x = int(np.ceil(width / tile_side))
    tiles_y = int(np.ceil(height / tile_side))
    log(f"[blend] tiled multiband: {tiles_x}x{tiles_y} tiles, side={tile_side}, margin={margin}")

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            core_x0 = tx * tile_side
            core_y0 = ty * tile_side
            core_x1 = min(width, core_x0 + tile_side)
            core_y1 = min(height, core_y0 + tile_side)
            tx0 = max(0, core_x0 - margin)
            ty0 = max(0, core_y0 - margin)
            tx1 = min(width, core_x1 + margin)
            ty1 = min(height, core_y1 + margin)
            tw = tx1 - tx0
            th = ty1 - ty0
            if tw <= 0 or th <= 0:
                continue

            members = []
            for idx, (bx0, by0, bx1, by1) in enumerate(boxes):
                if bx1 <= tx0 or bx0 >= tx1 or by1 <= ty0 or by0 >= ty1:
                    continue
                members.append(idx)
            if not members:
                continue

            tile_shift = np.array([[1.0, 0, -tx0], [0, 1.0, -ty0], [0, 0, 1.0]], dtype=np.float64)
            warped_imgs = []
            warped_masks = []
            for idx in members:
                image = read_image_bgr(image_paths[idx])
                matrix = tile_shift @ canvas_plan.transforms[idx]
                warped = cv2.warpPerspective(image, matrix, (tw, th), flags=cv2.INTER_LANCZOS4)
                mask = cv2.warpPerspective(
                    np.full(image.shape[:2], 255, np.uint8), matrix, (tw, th), flags=cv2.INTER_NEAREST
                )
                gain = gains[idx]
                if not np.allclose(gain, 1.0):
                    warped = np.clip(warped.astype(np.float64) * gain, 0, 255).astype(np.uint8)
                warped_imgs.append(warped)
                warped_masks.append(mask)

            seam_masks = _exclusive_seam_masks(warped_masks)
            try:
                blender = cv2.detail_MultiBandBlender()
                blender.setNumBands(bands)
                blender.prepare((0, 0, tw, th))
                for img, msk in zip(warped_imgs, seam_masks):
                    blender.feed(img.astype(np.int16), msk, (0, 0))
                result, result_mask = blender.blend(None, None)
                tile_result = np.clip(result, 0, 255).astype(np.uint8)
                tile_mask = _as_mask_array(result_mask) > 0
            except cv2.error:
                tile_result, tile_mask = _feather_compose_tile(warped_imgs, seam_masks, tw, th)

            # Copy only the non-overlapping core region back to the canvas.
            cx0, cy0 = core_x0 - tx0, core_y0 - ty0
            cx1, cy1 = core_x1 - tx0, core_y1 - ty0
            sub = tile_result[cy0:cy1, cx0:cx1]
            sub_mask = tile_mask[cy0:cy1, cx0:cx1]
            target = canvas[core_y0:core_y1, core_x0:core_x1]
            target[sub_mask] = sub[sub_mask]
            coverage[core_y0:core_y1, core_x0:core_x1] |= sub_mask

    if not np.any(coverage):
        raise RuntimeError("Tiled multiband blending produced an empty canvas.")
    ys, xs = np.where(coverage)
    # np.array(...) forces a real in-RAM copy, independent of the memmap file.
    result = np.array(canvas[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1])

    if _stream_dir is not None:
        import shutil

        del canvas, coverage
        shutil.rmtree(_stream_dir, ignore_errors=True)
    return result


def _feather_compose_tile(imgs, masks, tw, th):
    """Distance-weighted fallback compositing for a single tile."""
    canvas = np.zeros((th, tw, 3), dtype=np.float64)
    weights = np.zeros((th, tw), dtype=np.float64)
    for img, msk in zip(imgs, masks):
        alpha = cv2.distanceTransform((msk > 0).astype(np.uint8), cv2.DIST_L2, 3)
        canvas += img.astype(np.float64) * alpha[:, :, None]
        weights += alpha
    valid = weights > 1e-6
    out = np.zeros((th, tw, 3), dtype=np.uint8)
    for channel in range(3):
        ch = canvas[:, :, channel]
        ch[valid] /= weights[valid]
        out[:, :, channel] = np.clip(ch, 0, 255).astype(np.uint8)
    return out, valid


def blend_full_resolution(
    image_paths: list[Path],
    canvas_plan: CanvasPlan,
    log: LogFn = _noop,
) -> np.ndarray:
    pixels = int(canvas_plan.width) * int(canvas_plan.height)
    if pixels <= int(settings.stitch_planar_multiband_max_pixels):
        warped_images = []
        try:
            from .warping import prepare_warped_images

            warped_images = prepare_warped_images(image_paths, canvas_plan, log)
            apply_local_alignment(warped_images, canvas_plan.width, canvas_plan.height, log)
            apply_exposure_compensation(warped_images, log)
            apply_graphcut_seams(warped_images, log)
            return multiband_blend(warped_images, canvas_plan.width, canvas_plan.height, log)
        except (cv2.error, MemoryError) as exc:
            log(f"[blend] in-memory multiband failed; trying tiled multiband. reason={exc}")
            del warped_images

    if bool(settings.stitch_planar_tiled_multiband):
        try:
            log("[blend] canvas is large; using tiled multiband blending")
            return tiled_multiband_blend(image_paths, canvas_plan, log)
        except (cv2.error, MemoryError, RuntimeError) as exc:
            log(f"[blend] tiled multiband failed; using streaming feather fallback. reason={exc}")

    log("[blend] using streaming feather fallback")
    return feather_blend_streaming(image_paths, canvas_plan, log)

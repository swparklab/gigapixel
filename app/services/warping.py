from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .feature_matching import FeatureSet, read_image_bgr
from .tiling import assert_canvas_size

LogFn = Callable[[str], None]


@dataclass(slots=True)
class CanvasPlan:
    transforms: list[np.ndarray]
    width: int
    height: int


@dataclass(slots=True)
class WarpedImage:
    image: np.ndarray
    mask: np.ndarray
    corner: tuple[int, int]
    path: Path


def _noop(_: str) -> None:
    return


def project_corners(width: int, height: int, matrix: np.ndarray) -> np.ndarray:
    corners = np.array(
        [
            [[0.0, 0.0]],
            [[float(width), 0.0]],
            [[float(width), float(height)]],
            [[0.0, float(height)]],
        ],
        dtype=np.float64,
    )
    return cv2.perspectiveTransform(corners, matrix).reshape(-1, 2)


def plan_canvas(features: list[FeatureSet], transforms: list[np.ndarray], log: LogFn = _noop) -> CanvasPlan:
    all_corners = []
    for feature, matrix in zip(features, transforms):
        all_corners.append(project_corners(feature.width, feature.height, matrix))

    stacked = np.vstack(all_corners)
    min_xy = np.floor(stacked.min(axis=0))
    max_xy = np.ceil(stacked.max(axis=0))
    pad = max(16, int(settings.stitch_planar_blend_width) * 2)
    shift = np.array(
        [
            [1.0, 0.0, -min_xy[0] + pad],
            [0.0, 1.0, -min_xy[1] + pad],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    shifted = [shift @ matrix for matrix in transforms]
    width = int(max(1, np.ceil(max_xy[0] - min_xy[0] + pad * 2)))
    height = int(max(1, np.ceil(max_xy[1] - min_xy[1] + pad * 2)))
    assert_canvas_size(width, height, settings.max_source_pixels)
    log(f"[warp] canvas={width}x{height}, pixels={width * height}")
    return CanvasPlan(transforms=shifted, width=width, height=height)


def warp_image_to_roi(image: np.ndarray, matrix: np.ndarray, canvas_width: int, canvas_height: int) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    height, width = image.shape[:2]
    corners = project_corners(width, height, matrix)
    x0 = max(0, int(np.floor(corners[:, 0].min())))
    y0 = max(0, int(np.floor(corners[:, 1].min())))
    x1 = min(canvas_width, int(np.ceil(corners[:, 0].max())))
    y1 = min(canvas_height, int(np.ceil(corners[:, 1].max())))
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("Warped image falls outside the canvas.")

    roi_width = x1 - x0
    roi_height = y1 - y0
    roi_shift = np.array([[1.0, 0.0, -float(x0)], [0.0, 1.0, -float(y0)], [0.0, 0.0, 1.0]], dtype=np.float64)
    roi_matrix = roi_shift @ matrix

    warped = cv2.warpPerspective(
        image,
        roi_matrix,
        (roi_width, roi_height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
    )
    source_mask = np.full((height, width), 255, dtype=np.uint8)
    mask = cv2.warpPerspective(
        source_mask,
        roi_matrix,
        (roi_width, roi_height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )
    return warped, mask, (x0, y0)


def prepare_warped_images(
    image_paths: list[Path],
    canvas_plan: CanvasPlan,
    log: LogFn = _noop,
) -> list[WarpedImage]:
    warped_images: list[WarpedImage] = []
    for idx, (path, matrix) in enumerate(zip(image_paths, canvas_plan.transforms)):
        image = read_image_bgr(path)
        warped, mask, corner = warp_image_to_roi(image, matrix, canvas_plan.width, canvas_plan.height)
        warped_images.append(WarpedImage(image=warped, mask=mask, corner=corner, path=path))
        log(f"[warp] {idx + 1}/{len(image_paths)} {path.name}: roi={warped.shape[1]}x{warped.shape[0]} at {corner}")
    return warped_images

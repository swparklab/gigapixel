"""Local (elastic) overlap alignment to remove stitching ghosting.

Global affine/homography alignment is rigid: when input captures differ in
focus, have slight parallax, or yield inconsistent detected points, a residual
sub-pixel-to-several-pixel misalignment remains in the overlaps and shows up as
"breaking"/ghosting after blending.

This module computes a dense optical-flow field between an image and the
already-composited reference *inside the overlap*, then remaps the image to
match — a constrained elastic warp. The flow is clamped to a small displacement
and feathered to zero outside the overlap so non-overlapping content is never
torn.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


def is_enabled() -> bool:
    return bool(getattr(settings, "stitch_planar_local_align", True))


def _dense_flow(ref_gray: np.ndarray, mov_gray: np.ndarray) -> np.ndarray:
    """Displacement that maps reference coordinates onto the moving image."""
    try:
        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        return dis.calc(ref_gray, mov_gray, None)
    except Exception:
        return cv2.calcOpticalFlowFarneback(ref_gray, mov_gray, None, 0.5, 4, 25, 3, 5, 1.2, 0)


def refine(moving_bgr: np.ndarray, reference_bgr: np.ndarray, overlap_mask: np.ndarray, log: LogFn = _noop) -> np.ndarray:
    """Return ``moving_bgr`` elastically warped to align with ``reference_bgr``
    inside ``overlap_mask`` (uint8). Shapes must match."""
    if not is_enabled():
        return moving_bgr
    overlap = overlap_mask > 0
    overlap_px = int(np.count_nonzero(overlap))
    if overlap_px < 2000:
        return moving_bgr

    ref_gray = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
    mov_gray = cv2.cvtColor(moving_bgr, cv2.COLOR_BGR2GRAY)
    flow = _dense_flow(ref_gray, mov_gray)

    max_disp = float(max(2, int(settings.stitch_local_align_max_disp)))
    flow = np.clip(flow, -max_disp, max_disp)

    # Feather the correction: full strength deep inside the overlap, decaying to
    # zero at (and beyond) the overlap boundary so non-overlap content is fixed.
    dist = cv2.distanceTransform(overlap.astype(np.uint8), cv2.DIST_L2, 3)
    weight = np.clip(dist / 12.0, 0.0, 1.0).astype(np.float32)
    weight = cv2.GaussianBlur(weight, (0, 0), 4.0)
    flow[..., 0] *= weight
    flow[..., 1] *= weight

    h, w = mov_gray.shape[:2]
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = grid_x + flow[..., 0]
    map_y = grid_y + flow[..., 1]
    aligned = cv2.remap(moving_bgr, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    residual = float(np.mean(np.abs(flow[overlap])))
    log(f"[align] local elastic refine: overlap={overlap_px}px, mean_disp={residual:.2f}")
    return aligned

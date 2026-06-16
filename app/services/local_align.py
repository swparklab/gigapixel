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


def _flow_raft(ref_gray: np.ndarray, mov_gray: np.ndarray) -> np.ndarray | None:
    """RAFT (2020, torchvision): recurrent all-pairs field transform.

    State-of-the-art optical flow, available in torchvision >= 0.13.
    pip install torchvision
    """
    try:
        import torch  # type: ignore
        from torchvision.models.optical_flow import raft_large, Raft_Large_Weights  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = raft_large(weights=Raft_Large_Weights.DEFAULT).to(device).eval()

        def _to_rgb_tensor(gray: np.ndarray) -> "torch.Tensor":
            rgb = np.stack([gray, gray, gray], axis=2).astype(np.float32)
            t = torch.from_numpy(rgb.transpose(2, 0, 1))[None].to(device)
            return t * 255.0

        t_ref = _to_rgb_tensor(ref_gray)
        t_mov = _to_rgb_tensor(mov_gray)
        with torch.inference_mode():
            flow_list = model(t_ref, t_mov)
        flow = flow_list[-1].squeeze().permute(1, 2, 0).cpu().numpy()
        return flow.astype(np.float32)
    except Exception:
        return None


def _flow_searaft(ref_gray: np.ndarray, mov_gray: np.ndarray) -> np.ndarray | None:
    """SEA-RAFT (2024): simplified, faster RAFT variant, fewer parameters.

    Achieves RAFT accuracy at ~2x the speed. pip install sea-raft
    (or: github.com/princeton-vl/SEA-RAFT)
    """
    try:
        import torch  # type: ignore
        from sea_raft.raft import RAFT as SeaRaft  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
        checkpoint = str(getattr(settings, "searaft_checkpoint", "") or "").strip()
        model = SeaRaft(mixed_precision=False, iters=12).to(device).eval()
        if checkpoint:
            state = torch.load(checkpoint, map_location=device, weights_only=True)
            model.load_state_dict(state, strict=False)

        def _gray_to_tensor(gray: np.ndarray) -> "torch.Tensor":
            rgb = np.stack([gray, gray, gray], axis=2).astype(np.float32)
            return torch.from_numpy(rgb.transpose(2, 0, 1))[None].to(device) * 255.0

        t_ref = _gray_to_tensor(ref_gray)
        t_mov = _gray_to_tensor(mov_gray)
        with torch.inference_mode():
            _, flow = model(t_ref, t_mov, iters=12)
        return flow.squeeze().permute(1, 2, 0).cpu().numpy().astype(np.float32)
    except Exception:
        return None


def _dense_flow(ref_gray: np.ndarray, mov_gray: np.ndarray) -> np.ndarray:
    """Displacement that maps reference coordinates onto the moving image.

    Backend selection via LOCAL_ALIGN_FLOW_BACKEND:
      auto      — DISOpticalFlow (default, preserves existing behavior)
      searaft   — SEA-RAFT (2024) with DIS fallback
      raft      — RAFT (torchvision) with DIS fallback
      dis       — DISOpticalFlow (OpenCV, fast classical)
      farneback — classic Farneback pyramid flow

    Note: 'auto' deliberately stays on DIS to preserve verified behavior.
    Set LOCAL_ALIGN_FLOW_BACKEND=searaft or raft to opt-in to learned flow.
    """
    flow_backend = str(getattr(settings, "local_align_flow_backend", "auto")).lower()

    if flow_backend == "searaft":
        result = _flow_searaft(ref_gray, mov_gray)
        if result is not None:
            return result

    if flow_backend == "raft":
        result = _flow_raft(ref_gray, mov_gray)
        if result is not None:
            return result

    if flow_backend == "farneback":
        return cv2.calcOpticalFlowFarneback(ref_gray, mov_gray, None, 0.5, 4, 25, 3, 5, 1.2, 0)

    # auto / dis / any unrecognised → DIS (original default behavior)
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

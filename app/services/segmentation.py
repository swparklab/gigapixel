"""Smart annotation: click-to-segment and damage detection for the viewer.

Given a click point (and optional box) inside the mosaic, returns a polygon
outline of the object/region under the cursor, which the viewer turns into an
annotation. Also offers automatic detection of crack/damage-like structures.

Backends (``sam_backend``):

* ``sam`` — Segment Anything (``segment_anything`` package + a checkpoint at
  ``sam_checkpoint``). Best, prompt-driven segmentation.
* ``classical`` — GrabCut seeded from the point/box. Always available, so
  click-segmentation works without any model weights.
* ``auto`` — SAM when a checkpoint is loadable, otherwise classical.

Damage detection is classical (CLAHE + ridge/edge morphology) and always
available; it can be swapped for a trained model later behind the same call.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


class _Sam:
    _predictor = None
    _failed = False

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._predictor is not None:
            return cls._predictor
        checkpoint = str(getattr(settings, "sam_checkpoint", "") or "").strip()
        if not checkpoint:
            cls._failed = True
            return None
        try:
            import torch  # type: ignore
            from segment_anything import SamPredictor, sam_model_registry  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = sam_model_registry[str(settings.sam_model_type)](checkpoint=checkpoint).to(device)
            cls._predictor = SamPredictor(model)
            return cls._predictor
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def segment(cls, rgb: np.ndarray, point_xy, box) -> np.ndarray | None:
        predictor = cls.get()
        if predictor is None:
            return None
        try:
            predictor.set_image(rgb)
            kwargs = {}
            if point_xy is not None:
                kwargs["point_coords"] = np.array([point_xy], dtype=np.float32)
                kwargs["point_labels"] = np.array([1], dtype=np.int64)
            if box is not None:
                kwargs["box"] = np.array(box, dtype=np.float32)
            masks, scores, _ = predictor.predict(multimask_output=True, **kwargs)
            best = int(np.argmax(scores))
            return masks[best].astype(np.uint8)
        except Exception:
            return None


def backend_available() -> bool:
    return bool(getattr(settings, "sam_enabled", True))


def _resolve_backend() -> str:
    requested = str(getattr(settings, "sam_backend", "auto")).lower()
    if requested == "classical":
        return "classical"
    if requested == "sam":
        return "sam"
    return "sam" if _Sam.get() is not None else "classical"


def _grabcut_mask(bgr: np.ndarray, point_xy, box) -> np.ndarray:
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    if box is None:
        cx, cy = (point_xy if point_xy is not None else (w / 2, h / 2))
        half = max(16, int(0.25 * min(h, w)))
        x0 = int(max(1, cx - half))
        y0 = int(max(1, cy - half))
        x1 = int(min(w - 1, cx + half))
        y1 = int(min(h - 1, cy + half))
    else:
        x0, y0, x1, y1 = [int(v) for v in box]
        x0 = max(1, min(x0, w - 2)); y0 = max(1, min(y0, h - 2))
        x1 = max(x0 + 1, min(x1, w - 1)); y1 = max(y0 + 1, min(y1, h - 1))
    rect = (x0, y0, x1 - x0, y1 - y0)
    try:
        cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
        result = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    except cv2.error:
        result = np.zeros((h, w), np.uint8)
    # If GrabCut found no coherent foreground (e.g. a tight box around the
    # object), fall back to the prompt rectangle so the caller always gets a
    # usable region.
    if int(np.count_nonzero(result)) < 16:
        result = np.zeros((h, w), np.uint8)
        result[y0:y1, x0:x1] = 1
    return result


def _mask_to_polygon(mask: np.ndarray, simplify: float = 2.0) -> list[list[float]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    approx = cv2.approxPolyDP(largest, simplify, True)
    return [[float(p[0][0]), float(p[0][1])] for p in approx]


def segment_region(
    bgr: np.ndarray,
    point_xy: tuple[float, float] | None = None,
    box: tuple[float, float, float, float] | None = None,
    log: LogFn = _noop,
) -> tuple[list[list[float]], str]:
    """Return (polygon points in crop coords, backend used)."""
    backend = _resolve_backend()
    mask = None
    if backend == "sam":
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        mask = _Sam.segment(rgb, point_xy, box)
        if mask is None:
            backend = "classical"
    if mask is None:
        mask = _grabcut_mask(bgr, point_xy, box)
    polygon = _mask_to_polygon(mask)
    log(f"[segment] backend={backend}, points={len(polygon)}")
    return polygon, backend


def detect_damage(bgr: np.ndarray, max_regions: int = 50, log: LogFn = _noop) -> list[dict]:
    """Detect crack/damage-like thin dark ridges. Returns bounding boxes."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    # Black-hat highlights thin dark structures (cracks) against the surface.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    _, mask = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape[:2]
    min_len = max(20, int(0.03 * max(h, w)))
    regions: list[dict] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, bw, bh = cv2.boundingRect(contour)
        if max(bw, bh) < min_len:
            continue
        elongation = max(bw, bh) / max(1, min(bw, bh))
        if elongation < 2.5:  # cracks are elongated, not blobby
            continue
        regions.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh), "length": int(max(bw, bh))})
        if len(regions) >= max_regions:
            break
    log(f"[segment] damage regions detected: {len(regions)}")
    return regions

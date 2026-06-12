"""Multi-temporal change detection for conservation monitoring.

Registers two captures of the same object (e.g. taken years apart), then
highlights what changed — cracks that grew, paint loss, biological growth. The
"before" image is aligned to "after" with a homography from matched features,
and a perceptual difference is thresholded into change regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass(slots=True)
class ChangeResult:
    aligned: bool
    change_fraction: float
    regions: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "aligned": self.aligned,
            "change_fraction": round(self.change_fraction, 6),
            "regions": self.regions,
            "note": self.note,
        }


def _align(before: np.ndarray, after: np.ndarray) -> tuple[np.ndarray | None, bool]:
    g1 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    detector = cv2.SIFT_create() if hasattr(cv2, "SIFT_create") else cv2.ORB_create(4000)
    k1, d1 = detector.detectAndCompute(g1, None)
    k2, d2 = detector.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None, False
    norm = cv2.NORM_L2 if d1.dtype != np.uint8 else cv2.NORM_HAMMING
    knn = cv2.BFMatcher(norm).knnMatch(d1, d2, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 12:
        return None, False
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return None, False
    warped = cv2.warpPerspective(before, H, (after.shape[1], after.shape[0]))
    return warped, True


def detect_changes(before: np.ndarray, after: np.ndarray, sensitivity: float = 0.12) -> tuple[ChangeResult, np.ndarray]:
    """Return (ChangeResult, change_mask uint8). ``sensitivity`` in [0,1]."""
    aligned_before, ok = _align(before, after)
    if not ok:
        return ChangeResult(False, 0.0, note="alignment failed; images may not overlap"), np.zeros(after.shape[:2], np.uint8)

    a = cv2.GaussianBlur(aligned_before, (0, 0), 1.5).astype(np.float32)
    b = cv2.GaussianBlur(after, (0, 0), 1.5).astype(np.float32)
    diff = np.linalg.norm(a - b, axis=2)
    valid = cv2.cvtColor(aligned_before, cv2.COLOR_BGR2GRAY) > 2
    thresh = float(np.clip(sensitivity, 0.02, 0.9)) * 255.0 * np.sqrt(3)
    mask = ((diff > thresh) & valid).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = mask.shape
    min_area = max(25, int(0.0001 * h * w))
    regions = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:100]:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        regions.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh), "area": int(area)})

    change_fraction = float(np.count_nonzero(mask)) / max(1, int(np.count_nonzero(valid)))
    return ChangeResult(True, change_fraction, regions), mask

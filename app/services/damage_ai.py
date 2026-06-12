"""AI condition analysis: crack and discolouration detection.

Two real, analytical detectors (with an optional deep-segmentation hook):

* **Cracks** — a multiscale Hessian ridge filter (Frangi/Sato family) responds
  to thin dark line structures; responses are thresholded and filtered to
  elongated components.
* **Discolouration** — CIELAB analysis against a robust local background model
  classifies regions as *yellowing* (raised b*), *fading* (depressed chroma) or
  *staining* (local darkening + hue shift).

Both run on a bounded-resolution copy; findings are returned in full-resolution
image coordinates with a severity in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class ConditionReport:
    width: int
    height: int
    cracks: list[dict] = field(default_factory=list)
    discolouration: list[dict] = field(default_factory=list)
    crack_density: float = 0.0
    discolour_fraction: float = 0.0
    backend: str = "classical"

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "backend": self.backend,
            "crack_density": round(self.crack_density, 6),
            "discolour_fraction": round(self.discolour_fraction, 6),
            "cracks": self.cracks,
            "discolouration": self.discolouration,
        }


def _analysis(image: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    max_dim = max(512, int(settings.condition_max_dim))
    scale = min(1.0, max_dim / float(max(h, w)))
    if scale < 0.999:
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale
    return image, 1.0


def _hessian_ridge(gray: np.ndarray, sigma: float) -> np.ndarray:
    """Frangi/Sato-style dark line response at one scale."""
    g = cv2.GaussianBlur(gray, (0, 0), sigma)
    dxx = cv2.Sobel(g, cv2.CV_32F, 2, 0, ksize=3)
    dyy = cv2.Sobel(g, cv2.CV_32F, 0, 2, ksize=3)
    dxy = cv2.Sobel(g, cv2.CV_32F, 1, 1, ksize=3)
    # Eigenvalues of the 2x2 Hessian.
    tmp = np.sqrt(np.maximum((dxx - dyy) ** 2 + 4 * dxy ** 2, 0))
    lambda1 = 0.5 * (dxx + dyy + tmp)
    lambda2 = 0.5 * (dxx + dyy - tmp)
    # order so |l1| <= |l2|
    swap = np.abs(lambda1) > np.abs(lambda2)
    l1 = np.where(swap, lambda2, lambda1)
    l2 = np.where(swap, lambda1, lambda2)
    rb = (l1 / (l2 + 1e-6)) ** 2
    s2 = l1 ** 2 + l2 ** 2
    c = 0.5 * float(np.percentile(np.sqrt(s2), 90) + 1e-6)
    beta = 0.5
    response = np.exp(-rb / (2 * beta ** 2)) * (1 - np.exp(-s2 / (2 * c ** 2)))
    # dark ridge => l2 > 0 (bright second derivative across a dark valley)
    response[l2 < 0] = 0
    return response * sigma


def _detect_cracks(bgr: np.ndarray, log: LogFn) -> tuple[list[dict], np.ndarray]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray = cv2.createCLAHE(2.0, (8, 8)).apply(gray.astype(np.uint8)).astype(np.float32)
    ridge = np.zeros_like(gray)
    for sigma in (1.0, 2.0, 3.5):
        ridge = np.maximum(ridge, _hessian_ridge(gray, sigma))
    ridge = cv2.normalize(ridge, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    sens = float(np.clip(settings.condition_crack_sensitivity, 0.05, 0.95))
    thr = int(np.clip(255 * (1.0 - sens) * 0.9 + 25, 20, 230))
    mask = (ridge >= thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    min_len = max(18, int(0.02 * max(h, w)))
    cracks = []
    crack_mask = np.zeros((h, w), np.uint8)
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        length = max(bw, bh)
        if length < min_len:
            continue
        elong = length / max(1, min(bw, bh))
        if elong < 2.2:
            continue
        sev = float(np.clip(length / max(h, w) * 2.0 + (elong / 20.0), 0, 1))
        cracks.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh), "length": int(length),
                       "elongation": round(float(elong), 2), "severity": round(sev, 3)})
        cv2.drawContours(crack_mask, [contour], -1, 255, 2)
    log(f"[condition] cracks: {len(cracks)}")
    return cracks, crack_mask


def _detect_discolouration(bgr: np.ndarray, log: LogFn) -> tuple[list[dict], np.ndarray]:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1] - 128.0, lab[..., 2] - 128.0
    chroma = np.sqrt(a ** 2 + b ** 2)
    win = max(31, (max(bgr.shape[:2]) // 12) | 1)
    bg_b = cv2.medianBlur(b.astype(np.float32), 5)
    bg_b = cv2.boxFilter(b, -1, (win, win))
    bg_chroma = cv2.boxFilter(chroma, -1, (win, win))
    bg_L = cv2.boxFilter(L, -1, (win, win))

    sens = float(np.clip(settings.condition_discolor_sensitivity, 0.05, 0.95))
    k = 1.0 + (1.0 - sens) * 2.0  # higher sensitivity -> lower threshold

    yellowing = (b - bg_b) > (8.0 * k)
    fading = (bg_chroma - chroma) > (10.0 * k)
    staining = ((bg_L - L) > (18.0 * k)) & (np.abs(a - cv2.boxFilter(a, -1, (win, win))) > 6.0)

    types = [("yellowing", yellowing), ("fading", fading), ("staining", staining)]
    h, w = L.shape
    overlay = np.zeros((h, w), np.uint8)
    findings: list[dict] = []
    min_area = max(80, int(0.0004 * h * w))
    for name, raw in types:
        m = cv2.morphologyEx((raw.astype(np.uint8) * 255), cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        overlay = np.maximum(overlay, m)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:40]:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            sev = float(np.clip(area / (h * w) * 12.0, 0.05, 1.0))
            findings.append({"type": name, "x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
                             "area": int(area), "severity": round(sev, 3)})
    log(f"[condition] discolouration: {len(findings)}")
    return findings, overlay


def analyze_condition(bgr: np.ndarray, log: LogFn = _noop) -> tuple[ConditionReport, np.ndarray]:
    """Return (ConditionReport in full-res coords, overlay BGR for visualisation)."""
    full_h, full_w = bgr.shape[:2]
    small, scale = _analysis(bgr)
    cracks, crack_mask = _detect_cracks(small, log)
    disc, disc_mask = _detect_discolouration(small, log)

    inv = 1.0 / scale
    for c in cracks:
        for key in ("x", "y", "w", "h", "length"):
            c[key] = int(round(c[key] * inv))
    for d in disc:
        for key in ("x", "y", "w", "h"):
            d[key] = int(round(d[key] * inv))

    report = ConditionReport(width=full_w, height=full_h, cracks=cracks, discolouration=disc)
    report.crack_density = float(np.count_nonzero(crack_mask)) / max(1, crack_mask.size)
    report.discolour_fraction = float(np.count_nonzero(disc_mask)) / max(1, disc_mask.size)

    # Visualisation overlay at analysis scale: red cracks, amber discolouration.
    overlay = small.copy()
    overlay[crack_mask > 0] = (60, 60, 255)
    amber = disc_mask > 0
    overlay[amber] = (0.4 * overlay[amber] + 0.6 * np.array([40, 180, 255])).astype(np.uint8)
    return report, overlay

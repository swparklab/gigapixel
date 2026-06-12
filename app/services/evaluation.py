"""Quantitative registration evaluation against synthetic ground truth.

Reprojection RMS alone cannot prove a pipeline is accurate. This harness warps
an image by a *known* transform, runs the registration estimator, and reports
the residual error between the recovered and ground-truth transforms — a
controlled, repeatable accuracy benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .feature_matching import (
    build_feature_sets,
    detect_features,
    make_preview,
    build_pair_match,
)


@dataclass(slots=True)
class EvalResult:
    recovered: bool
    inliers: int
    corner_error_px: float | None
    note: str = ""


def _corner_error(h_true: np.ndarray, h_est: np.ndarray, width: int, height: int) -> float:
    corners = np.array(
        [[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float64
    ).reshape(-1, 1, 2)
    a = cv2.perspectiveTransform(corners, h_true).reshape(-1, 2)
    b = cv2.perspectiveTransform(corners, h_est).reshape(-1, 2)
    return float(np.mean(np.linalg.norm(a - b, axis=1)))


def evaluate_known_transform(image_bgr: np.ndarray, h_true: np.ndarray) -> EvalResult:
    """Register ``image`` against ``H_true @ image`` and compare to ground truth."""
    height, width = image_bgr.shape[:2]
    warped = cv2.warpPerspective(image_bgr, h_true, (width, height))

    prev_a, scale_a = make_preview(image_bgr)
    prev_b, scale_b = make_preview(warped)
    kp_a, desc_a, det_a = detect_features(prev_a)
    kp_b, desc_b, det_b = detect_features(prev_b)
    if desc_a is None or desc_b is None:
        return EvalResult(False, 0, None, "insufficient features")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(desc_a, desc_b, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 12:
        return EvalResult(False, len(good), None, "too few matches")

    pts_a = np.float32([kp_a[m.queryIdx].pt for m in good])
    pts_b = np.float32([kp_b[m.trainIdx].pt for m in good])
    pair = build_pair_match(0, scale_a, pts_a, 1, scale_b, pts_b)
    if pair is None:
        return EvalResult(False, 0, None, "estimation failed")

    error = _corner_error(h_true, pair.h_left_to_right, width, height)
    return EvalResult(True, pair.inliers, error)

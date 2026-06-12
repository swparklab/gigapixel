"""Dimensional scale calibration: recover real-world units from the image.

Conservation and measurement need physical units, not pixels. Given a fiducial
ArUco marker of known side length (``scale_marker_length_mm``) the module
recovers pixels-per-millimetre and the effective DPI, or it can compute the same
from a user-supplied reference: two points a known distance apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..config import settings


@dataclass(slots=True)
class ScaleResult:
    calibrated: bool
    method: str
    pixels_per_mm: float | None = None
    dpi: float | None = None
    marker_id: int | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "calibrated": self.calibrated,
            "method": self.method,
            "pixels_per_mm": None if self.pixels_per_mm is None else round(self.pixels_per_mm, 5),
            "dpi": None if self.dpi is None else round(self.dpi, 2),
            "marker_id": self.marker_id,
            "note": self.note,
        }


def _aruco_dictionary():
    name = str(settings.scale_marker_dict)
    const = getattr(cv2.aruco, name, cv2.aruco.DICT_4X4_50)
    return cv2.aruco.getPredefinedDictionary(const)


def scale_from_reference(point_a, point_b, length_mm: float) -> ScaleResult:
    """Calibrate from two points a known physical distance apart."""
    if length_mm <= 0:
        return ScaleResult(False, "reference", note="reference length must be > 0")
    px = float(np.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1]))
    if px <= 0:
        return ScaleResult(False, "reference", note="reference points coincide")
    ppm = px / length_mm
    return ScaleResult(True, "reference", pixels_per_mm=ppm, dpi=ppm * 25.4)


def scale_from_marker(bgr: np.ndarray, length_mm: float | None = None) -> ScaleResult:
    """Calibrate from a detected ArUco marker of known side length."""
    length_mm = float(settings.scale_marker_length_mm if length_mm is None else length_mm)
    if length_mm <= 0:
        return ScaleResult(False, "marker", note="set scale_marker_length_mm to the marker side length")
    try:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        try:
            detector = cv2.aruco.ArucoDetector(_aruco_dictionary(), cv2.aruco.DetectorParameters())
            corners, ids, _ = detector.detectMarkers(gray)
        except AttributeError:  # older OpenCV API
            corners, ids, _ = cv2.aruco.detectMarkers(gray, _aruco_dictionary())
    except Exception as exc:
        return ScaleResult(False, "marker", note=f"ArUco unavailable: {exc}")

    if ids is None or len(corners) == 0:
        return ScaleResult(False, "marker", note="no ArUco marker detected")

    pts = corners[0].reshape(4, 2)
    sides = [np.hypot(*(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
    px = float(np.mean(sides))
    ppm = px / length_mm
    return ScaleResult(True, "marker", pixels_per_mm=ppm, dpi=ppm * 25.4, marker_id=int(ids.flatten()[0]))

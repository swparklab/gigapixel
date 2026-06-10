"""Optional lens-distortion correction applied before registration.

Residual radial/tangential lens distortion cannot be modelled by the affine or
homography transforms used for planar alignment, so it shows up as a "bow" in
the seams of large mosaics. Undistorting every source image up front — with the
*same* model for all of them — removes that error before features are even
detected.

Two ways to supply a model:

* Manual coefficients (``stitch_lens_k1`` ... ``stitch_lens_p2``). The intrinsic
  matrix is synthesised from the image size and ``stitch_lens_focal_ratio``.
* Automatic EXIF lookup via the optional ``lensfunpy`` package
  (``stitch_lens_auto``). When the package or a matching lens profile is not
  available, the manual coefficients are used instead.

Correction is disabled by default; a wrong model hurts more than it helps.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..config import settings

try:
    import lensfunpy  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    lensfunpy = None


def is_enabled() -> bool:
    return bool(getattr(settings, "stitch_lens_correction", False))


def _intrinsics(width: int, height: int) -> np.ndarray:
    focal = max(width, height) * float(settings.stitch_lens_focal_ratio)
    return np.array(
        [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _manual_coefficients() -> np.ndarray:
    return np.array(
        [
            float(settings.stitch_lens_k1),
            float(settings.stitch_lens_k2),
            float(settings.stitch_lens_p1),
            float(settings.stitch_lens_p2),
            0.0,
        ],
        dtype=np.float64,
    )


def _auto_correct(bgr: np.ndarray, path: Path) -> np.ndarray | None:
    """Undistort using EXIF + lensfunpy. Returns None when unavailable."""
    if lensfunpy is None or not bool(getattr(settings, "stitch_lens_auto", False)):
        return None
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(path) as image:
            exif = {TAGS.get(k, k): v for k, v in (image.getexif() or {}).items()}
        maker = str(exif.get("Make", "")).strip()
        model = str(exif.get("Model", "")).strip()
        focal = float(exif.get("FocalLength", 0) or 0)
        if not maker or not model or focal <= 0:
            return None

        db = lensfunpy.Database()
        cam = db.find_cameras(maker, model)
        if not cam:
            return None
        lenses = db.find_lenses(cam[0])
        if not lenses:
            return None

        height, width = bgr.shape[:2]
        modifier = lensfunpy.Modifier(lenses[0], cam[0].crop_factor, width, height)
        aperture = float(exif.get("FNumber", 8.0) or 8.0)
        modifier.initialize(focal, aperture, 1000.0)
        coords = modifier.apply_geometry_distortion()
        if coords is None:
            return None
        return cv2.remap(bgr, coords, None, cv2.INTER_LANCZOS4)
    except Exception:
        return None


def correct_image(bgr: np.ndarray, path: Path) -> np.ndarray:
    """Return an undistorted copy of ``bgr`` (or the input when disabled)."""
    if not is_enabled():
        return bgr

    auto = _auto_correct(bgr, path)
    if auto is not None:
        return auto

    coeffs = _manual_coefficients()
    if not np.any(coeffs):
        return bgr

    height, width = bgr.shape[:2]
    camera_matrix = _intrinsics(width, height)
    new_matrix, _ = cv2.getOptimalNewCameraMatrix(
        camera_matrix, coeffs, (width, height), 0.0, (width, height)
    )
    return cv2.undistort(bgr, camera_matrix, coeffs, None, new_matrix)

"""Colour / radiometric calibration for archival-grade accuracy.

Heritage digitisation standards (FADGI, Metamorfoze, ISO 19264-1) judge a
capture on colorimetric accuracy, not just resolution. This module:

* detects a 24-patch ColorChecker-style target (OpenCV ``mcc`` module when the
  contrib build is present),
* derives a white balance and a 3x3 colour-correction matrix (CCM) from the
  neutral/colour patches,
* reports CIE dE2000 error against the reference patch values, and
* grades the result against FADGI / Metamorfoze dE tolerances.

When no target is found it falls back to a gray-world white balance and reports
``calibrated=False`` so nothing is silently assumed to be colour-accurate.
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


# Standard 24-patch ColorChecker reference values in sRGB (8-bit), row-major.
MACBETH_SRGB = np.array(
    [
        [115, 82, 68], [194, 150, 130], [98, 122, 157], [87, 108, 67],
        [133, 128, 177], [103, 189, 170], [214, 126, 44], [80, 91, 166],
        [193, 90, 99], [94, 60, 108], [157, 188, 64], [224, 163, 46],
        [56, 61, 150], [70, 148, 73], [175, 54, 60], [231, 199, 31],
        [187, 86, 149], [8, 133, 161], [243, 243, 242], [200, 200, 200],
        [160, 160, 160], [122, 122, 121], [85, 85, 85], [52, 52, 52],
    ],
    dtype=np.float64,
)


@dataclass(slots=True)
class ColorReport:
    calibrated: bool = False
    method: str = "none"
    patches_found: int = 0
    delta_e_mean: float | None = None
    delta_e_max: float | None = None
    white_balance: list[float] = field(default_factory=list)
    conformance_target: str = "fadgi"
    conformance_pass: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "calibrated": self.calibrated,
            "method": self.method,
            "patches_found": self.patches_found,
            "delta_e_mean": None if self.delta_e_mean is None else round(self.delta_e_mean, 4),
            "delta_e_max": None if self.delta_e_max is None else round(self.delta_e_max, 4),
            "white_balance": [round(v, 5) for v in self.white_balance],
            "conformance_target": self.conformance_target,
            "conformance_pass": self.conformance_pass,
            "notes": self.notes,
        }


# --- colour-space helpers --------------------------------------------------
def _srgb_to_linear(rgb01: np.ndarray) -> np.ndarray:
    a = 0.055
    return np.where(rgb01 <= 0.04045, rgb01 / 12.92, ((rgb01 + a) / (1 + a)) ** 2.4)


def _srgb_to_lab(rgb01: np.ndarray) -> np.ndarray:
    linear = _srgb_to_linear(np.clip(rgb01, 0.0, 1.0))
    m = np.array(
        [[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]],
        dtype=np.float64,
    )
    xyz = linear @ m.T
    white = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    xyz = xyz / white
    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 colour difference for arrays of Lab values."""
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    avg_Lp = (L1 + L2) / 2.0
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    avg_C = (C1 + C2) / 2.0
    G = 0.5 * (1 - np.sqrt(avg_C ** 7 / (avg_C ** 7 + 25.0 ** 7 + 1e-12)))
    a1p = (1 + G) * a1
    a2p = (1 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)
    avg_Cp = (C1p + C2p) / 2.0
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2.0)
    avg_hp = np.where(np.abs(h1p - h2p) > 180, (h1p + h2p + 360) / 2.0, (h1p + h2p) / 2.0)
    T = (
        1
        - 0.17 * np.cos(np.radians(avg_hp - 30))
        + 0.24 * np.cos(np.radians(2 * avg_hp))
        + 0.32 * np.cos(np.radians(3 * avg_hp + 6))
        - 0.20 * np.cos(np.radians(4 * avg_hp - 63))
    )
    Sl = 1 + (0.015 * (avg_Lp - 50) ** 2) / np.sqrt(20 + (avg_Lp - 50) ** 2)
    Sc = 1 + 0.045 * avg_Cp
    Sh = 1 + 0.015 * avg_Cp * T
    d_ro = 30 * np.exp(-(((avg_hp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(avg_Cp ** 7 / (avg_Cp ** 7 + 25.0 ** 7 + 1e-12))
    Rt = -np.sin(np.radians(2 * d_ro)) * Rc
    return np.sqrt(
        (dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)
    )


# --- target detection ------------------------------------------------------
def _detect_checker_patches(bgr: np.ndarray) -> np.ndarray | None:
    """Return (24, 3) measured sRGB patch means, or None if no target found."""
    if not bool(settings.color_target_auto):
        return None
    try:
        detector = cv2.mcc.CCheckerDetector_create()
        if not detector.process(bgr, cv2.mcc.MCC24):
            return None
        checker = detector.getBestColorChecker()
        charts = checker.getChartsRGB()
        values = charts[:, 1].reshape(-1, 3)  # mean column
        if values.shape[0] < 24:
            return None
        # OpenCV mcc returns RGB in 0..255.
        return values[:24].astype(np.float64)
    except Exception:
        return None


def _gray_world_wb(bgr: np.ndarray) -> np.ndarray:
    means = bgr.reshape(-1, 3).mean(axis=0) + 1e-6
    gain = means.mean() / means
    return np.clip(gain, 0.5, 2.0)


def _fit_ccm(measured_rgb: np.ndarray, reference_rgb: np.ndarray) -> np.ndarray:
    """Least-squares 3x3 CCM in linear-RGB mapping measured -> reference."""
    src = _srgb_to_linear(measured_rgb / 255.0)
    dst = _srgb_to_linear(reference_rgb / 255.0)
    ccm, _, _, _ = np.linalg.lstsq(src, dst, rcond=None)
    return ccm  # (3,3), apply as linear_out = linear_in @ ccm


def calibrate(bgr: np.ndarray, log: LogFn = _noop) -> tuple[np.ndarray, ColorReport]:
    """Return (calibrated BGR, ColorReport)."""
    report = ColorReport(conformance_target=str(settings.color_conformance_target))
    if not bool(settings.color_management):
        return bgr, report

    measured = _detect_checker_patches(bgr)
    if measured is None:
        gain_bgr = _gray_world_wb(bgr)  # gain in BGR channel order
        out = np.clip(bgr.astype(np.float64) * gain_bgr, 0, 255).astype(np.uint8)
        report.method = "gray_world_wb"
        report.white_balance = gain_bgr[::-1].tolist()  # report in RGB order
        report.notes.append("No colour target detected; applied gray-world white balance only.")
        log("[color] no target; gray-world white balance applied")
        return out, report

    report.patches_found = int(measured.shape[0])
    ccm = _fit_ccm(measured, MACBETH_SRGB)

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0
    linear = _srgb_to_linear(rgb)
    corrected_linear = np.clip(linear @ ccm, 0.0, 1.0)
    # linear -> sRGB
    a = 0.055
    srgb = np.where(
        corrected_linear <= 0.0031308,
        12.92 * corrected_linear,
        (1 + a) * np.power(corrected_linear, 1 / 2.4) - a,
    )
    out_rgb = np.clip(srgb * 255.0, 0, 255).astype(np.uint8)
    out = cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)

    # Residual dE2000 after correction.
    corrected_patches_linear = np.clip(_srgb_to_linear(measured / 255.0) @ ccm, 0.0, 1.0)
    corrected_patches_srgb = np.where(
        corrected_patches_linear <= 0.0031308,
        12.92 * corrected_patches_linear,
        (1 + a) * np.power(corrected_patches_linear, 1 / 2.4) - a,
    )
    de = delta_e2000(_srgb_to_lab(corrected_patches_srgb), _srgb_to_lab(MACBETH_SRGB / 255.0))
    report.calibrated = True
    report.method = "colorchecker_ccm"
    report.delta_e_mean = float(np.mean(de))
    report.delta_e_max = float(np.max(de))
    report.white_balance = [1.0, 1.0, 1.0]
    _grade_conformance(report)
    log(f"[color] CCM calibrated: dE2000 mean={report.delta_e_mean:.2f} max={report.delta_e_max:.2f}")
    return out, report


def _grade_conformance(report: ColorReport) -> None:
    # FADGI 4-star / Metamorfoze full: mean dE2000 <= ~3-4, max <= ~6-10.
    target = report.conformance_target.lower()
    if target == "metamorfoze":
        mean_tol, max_tol = 4.0, 10.0
    else:  # fadgi
        mean_tol, max_tol = 3.0, 6.0
    if report.delta_e_mean is None:
        report.conformance_pass = None
        return
    report.conformance_pass = bool(report.delta_e_mean <= mean_tol and (report.delta_e_max or 0) <= max_tol)
    report.notes.append(
        f"{target} tolerance: mean dE<= {mean_tol}, max dE<= {max_tol} -> "
        f"{'PASS' if report.conformance_pass else 'FAIL'}"
    )

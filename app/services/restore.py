"""AI restoration: virtually undo discolouration, cracks and noise.

Produces a restored variant for side-by-side Before/After inspection. The raw
archival image is never modified; restoration is a separate, clearly-labelled
output.

Steps (each toggleable):

* **De-colour** — neutralise a global colour cast (illuminant estimate from the
  near-neutral highlights), reduce yellowing (Lab b* bias), and adaptively
  revive faded chroma where structure exists.
* **De-crack** — inpaint detected crack pixels (LaMa when available, else Telea).
* **De-noise** — edge-preserving denoise.
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
class RestoreResult:
    image: np.ndarray
    actions: list[str] = field(default_factory=list)
    backend: str = "classical"


def _estimate_illuminant(bgr: np.ndarray) -> np.ndarray:
    """Gray-world on near-neutral highlight pixels -> per-channel gain (BGR)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bright = gray > np.percentile(gray, 75)
    sat = bgr.max(axis=2).astype(np.int16) - bgr.min(axis=2).astype(np.int16)
    neutral = bright & (sat < 40)
    if int(np.count_nonzero(neutral)) < 500:
        neutral = bright
    means = bgr[neutral].reshape(-1, 3).mean(axis=0) + 1e-6
    gain = means.mean() / means
    return np.clip(gain, 0.6, 1.6)


def _decolour(bgr: np.ndarray, log: LogFn) -> np.ndarray:
    gain = _estimate_illuminant(bgr)
    out = np.clip(bgr.astype(np.float32) * gain, 0, 255).astype(np.uint8)

    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    # Reduce residual yellow/blue cast: pull mean a*/b* toward neutral (128).
    a -= 0.6 * (float(np.median(a)) - 128.0)
    b -= 0.6 * (float(np.median(b)) - 128.0)
    # Revive faded chroma: boost where chroma is low but local detail exists.
    chroma = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    detail = cv2.Laplacian(L, cv2.CV_32F, ksize=3)
    structured = cv2.GaussianBlur(np.abs(detail), (0, 0), 2.0) > 2.0
    faded = (chroma < 18.0) & structured
    boost = np.where(faded, 1.28, 1.0).astype(np.float32)
    a = 128 + (a - 128) * boost
    b = 128 + (b - 128) * boost
    lab[..., 1] = np.clip(a, 0, 255)
    lab[..., 2] = np.clip(b, 0, 255)
    log("[restore] de-colour: illuminant + cast correction + chroma revival")
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _scale_for(bgr: np.ndarray) -> float:
    max_dim = max(512, int(settings.condition_max_dim))
    return min(1.0, max_dim / float(max(bgr.shape[:2])))


def _decrack(bgr: np.ndarray, log: LogFn) -> np.ndarray:
    from .damage_ai import _detect_cracks

    scale = _scale_for(bgr)
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    _cracks, mask_small = _detect_cracks(small, _noop)
    mask = (
        cv2.resize(mask_small, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        if scale < 1
        else mask_small
    )
    if int(np.count_nonzero(mask)) == 0:
        return bgr
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    result = None
    if str(settings.restore_backend).lower() in ("auto", "deep"):
        try:
            from .repair import _LamaInpainter

            result = _LamaInpainter.inpaint(np.ascontiguousarray(bgr), mask)
        except Exception:
            result = None
    if result is None:
        result = cv2.inpaint(np.ascontiguousarray(bgr), mask, 4, cv2.INPAINT_TELEA)
    log(f"[restore] de-crack: inpainted {int(np.count_nonzero(mask))} px")
    return result


def restore_image(bgr: np.ndarray, log: LogFn = _noop) -> RestoreResult:
    work = bgr
    if int(settings.restore_max_dim) > 0:
        s = min(1.0, int(settings.restore_max_dim) / float(max(bgr.shape[:2])))
        if s < 1.0:
            work = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)

    actions: list[str] = []
    if bool(settings.restore_decolor):
        work = _decolour(work, lambda m: actions.append(m))
    if bool(settings.restore_decrack):
        work = _decrack(work, lambda m: actions.append(m))
    if bool(settings.restore_denoise):
        work = cv2.fastNlMeansDenoisingColored(work, None, 3, 3, 7, 21)
        actions.append("[restore] de-noise: edge-preserving NLM")
    backend = "deep+classical" if str(settings.restore_backend).lower() in ("auto", "deep") else "classical"
    return RestoreResult(image=work, actions=actions, backend=backend)

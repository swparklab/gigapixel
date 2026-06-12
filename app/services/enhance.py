"""Optional AI enhancement of the mosaic (super-resolution / denoise).

Produces a separate, clearly non-archival "enhanced" variant for web viewing.
This is generative and therefore OFF by default and never overwrites the raw
archival BigTIFF.

Backends (``stitch_enhance_backend``):

* ``realesrgan`` — Real-ESRGAN super-resolution via the optional ``realesrgan``
  package. Best perceptual detail.
* ``classical`` — Lanczos upscaling plus edge-preserving denoise and a mild
  unsharp mask. Always available.
* ``auto`` — Real-ESRGAN when importable, otherwise classical.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


class _RealEsrgan:
    _engine = None
    _failed = False
    _scale = None

    @classmethod
    def get(cls, scale: int):
        if cls._failed:
            return None
        if cls._engine is not None and cls._scale == scale:
            return cls._engine
        try:
            import torch  # type: ignore
            from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
            from realesrgan import RealESRGANer  # type: ignore

            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            cls._engine = RealESRGANer(
                scale=4,
                model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                model=model,
                half=torch.cuda.is_available(),
                device="cuda" if torch.cuda.is_available() else "cpu",
            )
            cls._scale = scale
            return cls._engine
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def enhance(cls, bgr: np.ndarray, scale: int) -> np.ndarray | None:
        engine = cls.get(scale)
        if engine is None:
            return None
        try:
            output, _ = engine.enhance(bgr, outscale=scale)
            return output
        except Exception:
            return None


def _classical_enhance(bgr: np.ndarray, scale: int, denoise: bool) -> np.ndarray:
    work = bgr
    if denoise:
        work = cv2.fastNlMeansDenoisingColored(work, None, 3, 3, 7, 21)
    if scale > 1:
        work = cv2.resize(work, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(work, (0, 0), 1.0)
    sharp = cv2.addWeighted(work, 1.4, blur, -0.4, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


def _resolve_backend() -> str:
    requested = str(getattr(settings, "stitch_enhance_backend", "auto")).lower()
    if requested == "classical":
        return "classical"
    if requested == "realesrgan":
        return "realesrgan"
    return "realesrgan" if not _RealEsrgan._failed else "classical"


def enhance_image(bgr: np.ndarray, log: LogFn = _noop) -> tuple[np.ndarray, str] | None:
    """Return (enhanced image, backend) or None when skipped."""
    scale = max(1, int(settings.stitch_enhance_scale))
    height, width = bgr.shape[:2]
    if width * height * (scale ** 2) > int(settings.stitch_enhance_max_pixels):
        log("[enhance] skipped: enhanced size would exceed configured pixel limit")
        return None

    backend = _resolve_backend()
    if backend == "realesrgan":
        out = _RealEsrgan.enhance(bgr, scale)
        if out is not None:
            log(f"[enhance] realesrgan x{scale} -> {out.shape[1]}x{out.shape[0]}")
            return out, "realesrgan"
        backend = "classical"

    out = _classical_enhance(bgr, scale, bool(settings.stitch_enhance_denoise))
    log(f"[enhance] classical x{scale} -> {out.shape[1]}x{out.shape[0]}")
    return out, "classical"

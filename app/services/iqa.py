"""No-reference (blind) image quality assessment for the QC stage.

Adds a perceptual quality score in ``[0, 1]`` (higher is better) on top of the
geometric/coverage checks in :mod:`app.services.quality`.

Backends (``stitch_quality_iqa_backend``):

* ``pyiqa`` — learned CLIP-IQA via the optional ``pyiqa`` package. Best
  correlation with human judgement of blur/artefacts.
* ``classical`` — a heuristic from sharpness, contrast and colourfulness.
  Always available; coarse but useful as a relative signal.
* ``auto`` — pyiqa when installed, otherwise classical.

Assessment runs on a bounded-resolution copy of a representative crop so it is
cheap even for gigapixel mosaics.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


class _ClipIqa:
    _metric = None
    _failed = False
    _device = "cpu"

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._metric is not None:
            return cls._metric
        try:
            import pyiqa  # type: ignore
            import torch  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            cls._torch = torch
            cls._metric = pyiqa.create_metric("clipiqa").to(cls._device).eval()
            return cls._metric
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def score(cls, rgb: np.ndarray) -> float | None:
        metric = cls.get()
        if metric is None:
            return None
        try:
            torch = cls._torch
            tensor = torch.from_numpy(rgb.astype(np.float32).transpose(2, 0, 1) / 255.0)[None].to(cls._device)
            with torch.inference_mode():
                value = float(metric(tensor).item())
            return float(np.clip(value, 0.0, 1.0))
        except Exception:
            return None


class _TopIqa:
    """TOPIQ (2024): Top-down perceptual IQA via pyiqa.

    Higher Pearson correlation with human MOS than CLIP-IQA on KADID-10k.
    pip install pyiqa (>=0.1.12)
    metric name: "topiq_nr" (no-reference) or "topiq_fr" (full-reference)
    """
    _metric = None
    _failed = False
    _device = "cpu"

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._metric is not None:
            return cls._metric
        try:
            import pyiqa  # type: ignore
            import torch  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            cls._torch = torch
            cls._metric = pyiqa.create_metric("topiq_nr").to(cls._device).eval()
            return cls._metric
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def score(cls, rgb: np.ndarray) -> float | None:
        metric = cls.get()
        if metric is None:
            return None
        try:
            torch = cls._torch
            tensor = torch.from_numpy(rgb.astype(np.float32).transpose(2, 0, 1) / 255.0)[None].to(cls._device)
            with torch.inference_mode():
                value = float(metric(tensor).item())
            return float(np.clip(value, 0.0, 1.0))
        except Exception:
            return None


class _QAlign:
    """Q-Align (2024): LLM-based IQA, highest human correlation on LIVE/KADID.

    Uses a vision-language model fine-tuned on MOS datasets. Requires ~7 GB GPU.
    pip install q-align  (or: transformers + mPLUG-Owl2 weights)
    HuggingFace: q-future/one-align
    """
    _model = None
    _processor = None
    _failed = False
    _device = "cpu"

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._model is not None:
            return cls._model
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            if cls._device == "cpu":
                cls._failed = True
                return None  # Q-Align is impractical on CPU.
            cls._torch = torch
            model_id = str(getattr(settings, "qalign_model", "q-future/one-align") or "q-future/one-align")
            cls._tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            cls._model = AutoModelForCausalLM.from_pretrained(
                model_id,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                device_map="auto",
            ).eval()
            return cls._model
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def score(cls, rgb: np.ndarray) -> float | None:
        if cls.get() is None:
            return None
        try:
            from PIL import Image as _PIL  # type: ignore
            img = _PIL.fromarray(rgb)
            # Q-Align returns quality level: bad(0.2)/poor(0.4)/fair(0.6)/good(0.8)/excellent(1.0)
            score = cls._model.score([img], task_="quality", input_="image")
            return float(np.clip(float(score[0]), 0.0, 1.0))
        except Exception:
            return None


def _representative_crop(image_bgr: np.ndarray, max_dim: int = 1024) -> np.ndarray:
    """Center-weighted crop avoiding empty borders, capped to max_dim."""
    threshold = int(settings.stitch_quality_empty_threshold)
    content = image_bgr.max(axis=2) > threshold
    ys, xs = np.where(content)
    if ys.size:
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        image_bgr = image_bgr[y0:y1, x0:x1]
    h, w = image_bgr.shape[:2]
    scale = min(1.0, max_dim / float(max(h, w)))
    if scale < 0.999:
        image_bgr = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image_bgr


def _classical_score(bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    b, g, r = bgr[:, :, 0].astype(np.float32), bgr[:, :, 1].astype(np.float32), bgr[:, :, 2].astype(np.float32)
    rg = r - g
    yb = 0.5 * (r + g) - b
    colourfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    # Soft saturating mapping into [0, 1]; tuned so a crisp, well-exposed crop
    # lands around 0.6-0.8 and a flat/blurred one near 0.1-0.3.
    s = 1.0 - np.exp(-sharpness / 400.0)
    c = 1.0 - np.exp(-contrast / 60.0)
    col = 1.0 - np.exp(-colourfulness / 40.0)
    return float(np.clip(0.55 * s + 0.30 * c + 0.15 * col, 0.0, 1.0))


def _resolve_backend() -> str:
    """Select IQA backend.

    Priority for auto: qalign > topiq > clipiqa (pyiqa) > classical
    qalign  — LLM-based, highest human correlation (requires GPU ~7 GB)
    topiq   — SOTA transformer IQA, better than CLIP-IQA on benchmarks
    clipiqa — reliable CLIP-based, good all-rounder
    classical — heuristic (sharpness/contrast/colourfulness), no deps
    """
    requested = str(getattr(settings, "stitch_quality_iqa_backend", "auto")).lower()
    if requested == "classical":
        return "classical"
    if requested in ("pyiqa", "clipiqa"):
        return "pyiqa"
    if requested == "topiq":
        return "topiq"
    if requested == "qalign":
        return "qalign"
    # auto: pick the best available.
    if _QAlign.get() is not None:
        return "qalign"
    if _TopIqa.get() is not None:
        return "topiq"
    if _ClipIqa.get() is not None:
        return "pyiqa"
    return "classical"


def perceptual_quality(image_bgr: np.ndarray, log: LogFn = _noop) -> tuple[float, str]:
    """Return (score in [0,1], backend used)."""
    crop = _representative_crop(image_bgr)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    backend = _resolve_backend()

    if backend == "qalign":
        value = _QAlign.score(rgb)
        if value is not None:
            log(f"[iqa] perceptual quality={value:.3f} (q-align)")
            return value, "qalign"
        backend = "topiq"

    if backend == "topiq":
        value = _TopIqa.score(rgb)
        if value is not None:
            log(f"[iqa] perceptual quality={value:.3f} (topiq)")
            return value, "topiq"
        backend = "pyiqa"

    if backend == "pyiqa":
        value = _ClipIqa.score(rgb)
        if value is not None:
            log(f"[iqa] perceptual quality={value:.3f} (clipiqa)")
            return value, "pyiqa"

    value = _classical_score(crop)
    log(f"[iqa] perceptual quality={value:.3f} (classical)")
    return value, "classical"

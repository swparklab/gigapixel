"""Image-retrieval based overlap-graph construction.

For large, *unordered* heritage sets the classical "match every image to its
sequential neighbours" heuristic fails: the correct overlaps are unknown. This
module computes a global descriptor per image and retrieves, for each image,
its top-K most similar partners. Those become the candidate pairs fed into
feature matching, so the overlap graph is correct regardless of capture order.

Backends (selected by ``stitch_retrieval_model``):

* ``dinov2`` — learned DINOv2 embeddings (via ``torch`` + ``transformers`` or
  ``torch.hub``). State-of-the-art place/instance recognition.
* ``classical`` — a thumbnail color + gradient embedding. Always available and
  still far better than a fixed neighbour window for unordered sets.
* ``auto`` — DINOv2 when importable, otherwise classical.

Everything degrades gracefully: any failure falls back to classical, and the
caller falls back to exhaustive/neighbour candidates if retrieval is disabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .feature_matching import read_image_bgr

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def _classical_embedding(bgr: np.ndarray) -> np.ndarray:
    """Thumbnail color + gradient descriptor, L2-normalised."""
    thumb = cv2.resize(bgr, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.resize(cv2.magnitude(gx, gy), (16, 16), interpolation=cv2.INTER_AREA).ravel()
    hist = []
    for ch in range(3):
        h = cv2.calcHist([bgr], [ch], None, [16], [0, 256]).ravel()
        hist.append(h)
    vector = np.concatenate([thumb.ravel(), mag / (mag.max() + 1e-6), np.concatenate(hist)])
    norm = np.linalg.norm(vector)
    return (vector / norm) if norm > 1e-9 else vector


class _SigLIPEmbedder:
    """SigLIP (Google, 2024): superior image-level retrieval vs DINOv2.

    Uses sigmoid loss training that better separates visually similar crops
    — useful for large heritage sets with repetitive patterns.
    Model: google/siglip-so400m-patch14-384 (~400M params, ~1.5 GB).
    pip: pip install transformers (>=4.38)
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
            return cls
        try:
            import torch  # type: ignore
            from transformers import AutoProcessor, AutoModel  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            name = str(getattr(settings, "stitch_retrieval_siglip_model", "google/siglip-so400m-patch14-384"))
            cls._processor = AutoProcessor.from_pretrained(name)
            cls._model = AutoModel.from_pretrained(name, torch_dtype=torch.float16 if cls._device == "cuda" else torch.float32).to(cls._device).eval()
            cls._torch = torch
            return cls
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def embed(cls, bgr: np.ndarray) -> np.ndarray | None:
        if cls.get() is None:
            return None
        try:
            torch = cls._torch
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            from PIL import Image as _PIL  # type: ignore
            inputs = cls._processor(images=_PIL.fromarray(rgb), return_tensors="pt").to(cls._device)
            with torch.inference_mode():
                out = cls._model.get_image_features(**inputs)
            vector = out[0].detach().cpu().float().numpy()
            norm = np.linalg.norm(vector)
            return (vector / norm) if norm > 1e-9 else vector
        except Exception:
            return None


class _DinoV2Embedder:
    _model = None
    _processor = None
    _failed = False
    _device = "cpu"

    @classmethod
    def get(cls):
        if cls._failed:
            return None
        if cls._model is not None:
            return cls
        try:
            import torch  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                from transformers import AutoImageProcessor, AutoModel  # type: ignore

                name = "facebook/dinov2-small"
                cls._processor = AutoImageProcessor.from_pretrained(name)
                cls._model = AutoModel.from_pretrained(name).to(cls._device).eval()
                cls._kind = "transformers"
            except Exception:
                cls._model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14").to(cls._device).eval()
                cls._kind = "hub"
            cls._torch = torch
            return cls
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def embed(cls, bgr: np.ndarray) -> np.ndarray | None:
        if cls.get() is None:
            return None
        try:
            torch = cls._torch
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            with torch.inference_mode():
                if cls._kind == "transformers":
                    inputs = cls._processor(images=rgb, return_tensors="pt").to(cls._device)
                    out = cls._model(**inputs)
                    feat = out.last_hidden_state[:, 0]  # CLS token
                else:
                    small = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
                    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
                    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
                    small = (small - mean) / std
                    tensor = torch.from_numpy(small.transpose(2, 0, 1))[None].to(cls._device)
                    feat = cls._model(tensor)
            vector = feat[0].detach().cpu().numpy().astype(np.float32)
            norm = np.linalg.norm(vector)
            return (vector / norm) if norm > 1e-9 else vector
        except Exception:
            return None


def _resolve_backend() -> str:
    """Select retrieval backend.

    Priority for auto: siglip > dinov2 > classical
    siglip  — best recall for repetitive heritage patterns (Google 2024, ~1.5 GB)
    dinov2  — proven, lightweight (85 MB small), well-tested
    classical — thumbnail color+gradient, no GPU needed
    """
    requested = str(getattr(settings, "stitch_retrieval_model", "auto")).lower()
    if requested == "classical":
        return "classical"
    if requested == "dinov2":
        return "dinov2"
    if requested == "siglip":
        return "siglip"
    # auto: prefer SigLIP, then DINOv2, then classical.
    if _SigLIPEmbedder.get() is not None:
        return "siglip"
    if _DinoV2Embedder.get() is not None:
        return "dinov2"
    return "classical"


def compute_embeddings(image_paths: list[Path], log: LogFn = _noop) -> tuple[np.ndarray, str]:
    backend = _resolve_backend()
    vectors: list[np.ndarray] = []
    used = backend
    for path in image_paths:
        bgr = read_image_bgr(path)
        vector: np.ndarray | None = None
        if backend == "siglip":
            vector = _SigLIPEmbedder.embed(bgr)
        elif backend == "dinov2":
            vector = _DinoV2Embedder.embed(bgr)
        if vector is None:
            vector = _classical_embedding(bgr)
            if backend != "classical":
                used = "classical"
        vectors.append(vector)
    # Pad to a common length (classical/dino/siglip dims differ only if mixed;
    # we keep one backend per run, so lengths match).
    matrix = np.vstack(vectors)
    log(f"[retrieval] embeddings computed: backend={used}, dim={matrix.shape[1]}")
    return matrix, used


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------
def _neighbor_pairs(count: int, window: int) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for left in range(count):
        for right in range(left + 1, min(count, left + window + 1)):
            pairs.add((left, right))
    return pairs


def retrieval_candidate_pairs(image_paths: list[Path], log: LogFn = _noop) -> list[tuple[int, int]]:
    """Top-K similarity pairs, unioned with a small neighbour window for safety."""
    count = len(image_paths)
    if count < 2:
        return []
    embeddings, _ = compute_embeddings(image_paths, log)
    similarity = embeddings @ embeddings.T
    np.fill_diagonal(similarity, -np.inf)

    top_k = max(1, int(settings.stitch_retrieval_top_k))
    pairs: set[tuple[int, int]] = set()
    for i in range(count):
        order = np.argsort(similarity[i])[::-1][:top_k]
        for j in order:
            a, b = (i, int(j)) if i < j else (int(j), i)
            if a != b:
                pairs.add((a, b))

    # Guarantee chain connectivity for ordered captures.
    pairs |= _neighbor_pairs(count, window=2)
    result = sorted(pairs)
    log(f"[retrieval] candidate pairs: {len(result)} (top_k={top_k})")
    return result


def resolve_candidate_pairs(image_paths: list[Path], log: LogFn = _noop) -> list[tuple[int, int]]:
    """Decide candidate pairs from the configured strategy.

    Returns an explicit pair list. The caller uses this instead of the legacy
    ``pair_candidates(count)`` generator when a list is returned.
    """
    count = len(image_paths)
    mode = str(getattr(settings, "stitch_pair_selection", "auto")).lower()
    exhaustive_limit = int(settings.stitch_planar_exhaustive_limit)
    window = max(1, int(settings.stitch_planar_neighbor_window))

    def exhaustive() -> list[tuple[int, int]]:
        return [(i, j) for i in range(count) for j in range(i + 1, count)]

    def neighbor() -> list[tuple[int, int]]:
        return sorted(_neighbor_pairs(count, window))

    if mode == "exhaustive":
        return exhaustive()
    if mode == "neighbor":
        return neighbor()
    if mode == "retrieval":
        try:
            return retrieval_candidate_pairs(image_paths, log)
        except Exception as exc:
            log(f"[retrieval] failed ({exc}); using neighbour window")
            return neighbor()

    # auto
    if count <= exhaustive_limit:
        return exhaustive()
    if count >= int(settings.stitch_retrieval_min_images):
        try:
            return retrieval_candidate_pairs(image_paths, log)
        except Exception as exc:
            log(f"[retrieval] failed ({exc}); using neighbour window")
    return neighbor()

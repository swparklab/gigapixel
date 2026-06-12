"""Corpus-level semantic search and automatic tagging.

* **Tagging** — zero-shot CLIP scores an image against a heritage label set
  (yellowing, cracks, textile, ceramic, painting, manuscript, …). Without CLIP a
  classical descriptor produces coarse colour/texture tags.
* **Search** — ranks ready sessions by similarity to a text query (CLIP text
  encoder) or to a reference image (image embedding). Without CLIP, text search
  falls back to matching the stored auto-tags.

Embeddings are cached per image path so repeat queries are cheap.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..config import settings
from .feature_matching import read_image_bgr
from .retrieval import _classical_embedding

HERITAGE_LABELS = [
    "a painting", "a manuscript page", "a textile", "a ceramic vessel",
    "a stone sculpture", "a metal artefact", "a wooden object", "calligraphy",
    "a mural", "an architectural surface", "yellowed and discoloured", "cracked and damaged",
    "faded colours", "high surface detail", "monochrome", "vivid colours",
]
_TAG_NAMES = {
    "a painting": "painting", "a manuscript page": "manuscript", "a textile": "textile",
    "a ceramic vessel": "ceramic", "a stone sculpture": "stone", "a metal artefact": "metal",
    "a wooden object": "wood", "calligraphy": "calligraphy", "a mural": "mural",
    "an architectural surface": "architecture", "yellowed and discoloured": "discoloured",
    "cracked and damaged": "cracked", "faded colours": "faded", "high surface detail": "detailed",
    "monochrome": "monochrome", "vivid colours": "vivid",
}


class _Clip:
    _model = None
    _failed = False
    _device = "cpu"

    @classmethod
    def get(cls):
        if cls._failed or cls._model is not None:
            return cls._model
        if str(settings.semantic_backend).lower() == "classical":
            cls._failed = True
            return None
        try:
            import open_clip  # type: ignore
            import torch  # type: ignore

            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
            cls._model = model.to(cls._device).eval()
            cls._preprocess = preprocess
            cls._tokenizer = open_clip.get_tokenizer("ViT-B-32")
            cls._torch = torch
            return cls._model
        except Exception:
            cls._failed = True
            return None

    @classmethod
    def image_embed(cls, bgr):
        if cls.get() is None:
            return None
        from PIL import Image

        torch = cls._torch
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        tensor = cls._preprocess(rgb).unsqueeze(0).to(cls._device)
        with torch.inference_mode():
            feat = cls._model.encode_image(tensor)
        v = feat[0].detach().cpu().numpy().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    @classmethod
    def text_embed(cls, texts):
        if cls.get() is None:
            return None
        torch = cls._torch
        tokens = cls._tokenizer(texts).to(cls._device)
        with torch.inference_mode():
            feat = cls._model.encode_text(tokens)
        v = feat.detach().cpu().numpy().astype(np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def backend() -> str:
    return "clip" if _Clip.get() is not None else "classical"


def image_embedding(bgr: np.ndarray) -> np.ndarray:
    v = _Clip.image_embed(bgr)
    if v is not None:
        return v
    return _classical_embedding(bgr)


def _classical_tags(bgr: np.ndarray) -> list[tuple[str, float]]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = float(hsv[..., 1].mean()) / 255.0
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    detail = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    lab_b = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 2].mean()) - 128.0
    tags = []
    tags.append(("vivid" if sat > 0.4 else "monochrome", round(abs(sat - 0.4) + 0.3, 3)))
    if detail > 200:
        tags.append(("detailed", round(min(1.0, detail / 1000), 3)))
    if lab_b > 12:
        tags.append(("discoloured", round(min(1.0, lab_b / 40), 3)))
    return tags


def auto_tags(bgr: np.ndarray, top_k: int = 5) -> list[dict]:
    if _Clip.get() is not None:
        img = image_embedding(bgr)
        txt = _Clip.text_embed(HERITAGE_LABELS)
        sims = txt @ img
        order = np.argsort(sims)[::-1][:top_k]
        thr = float(settings.semantic_tag_threshold)
        out = []
        for i in order:
            if float(sims[i]) >= thr:
                out.append({"tag": _TAG_NAMES[HERITAGE_LABELS[i]], "score": round(float(sims[i]), 4)})
        return out or [{"tag": _TAG_NAMES[HERITAGE_LABELS[int(order[0])]], "score": round(float(sims[order[0]]), 4)}]
    return [{"tag": t, "score": s} for t, s in _classical_tags(bgr)]


def rank_sessions(query: str, items: list[tuple[str, Path, str | None]], limit: int = 20) -> list[dict]:
    """items: (session_id, image_path, tags_csv). Returns ranked [{session_id, score}]."""
    txt = _Clip.text_embed([query])
    results = []
    if txt is not None:
        q = txt[0]
        for sid, path, _tags in items:
            try:
                emb = image_embedding(read_image_bgr(path))
            except Exception:
                continue
            results.append({"session_id": sid, "score": round(float(q @ emb), 4)})
    else:
        # classical: keyword match against stored tags.
        terms = [t for t in query.lower().split() if t]
        for sid, _path, tags in items:
            tagset = (tags or "").lower()
            score = sum(1 for t in terms if t in tagset) / max(1, len(terms))
            results.append({"session_id": sid, "score": round(float(score), 4)})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]

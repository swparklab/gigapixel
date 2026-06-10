"""Learned (AI) feature matching backends for high-accuracy registration.

This module is an *optional accuracy upgrade*. It uses learned matchers
(LoFTR, or a keypoint extractor combined with LightGlue) from ``kornia`` to
produce dense, robust correspondences between image pairs. These matchers are
dramatically more reliable than classical SIFT/ORB on the low-texture,
self-similar surfaces typical of cultural-heritage captures (paintings,
textiles, ceramics, stone).

The whole module degrades gracefully:

* If ``torch``/``kornia`` are not installed, :func:`create_matcher` returns
  ``None`` and the caller keeps using the classical pipeline.
* Any runtime failure raises a normal exception that the caller is expected to
  catch and fall back from. Nothing here is required for the project to run.

Correspondences are returned in *preview* coordinates together with the
preview->source scale, exactly mirroring the classical ``FeatureSet``
convention (``source = preview / scale``), so both paths can share the same
geometric verification and global alignment code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from .feature_matching import read_image_bgr

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


# Backends that rely on a learned matcher. "classic" is handled outside this module.
_LEARNED_BACKENDS = {"loftr", "disk_lightglue", "sift_lightglue", "aliked_lightglue"}


def _torch_available() -> tuple[object | None, object | None]:
    try:
        import torch  # type: ignore
        import kornia  # type: ignore

        return torch, kornia
    except Exception:
        return None, None


def _resolve_device(torch, requested: str) -> str:
    requested = (requested or "auto").lower()
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    # auto
    return "cuda" if torch.cuda.is_available() else "cpu"


def _round_to_multiple(value: int, multiple: int) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


@dataclass(slots=True)
class DeepImage:
    """A source image prepared for learned matching."""

    index: int
    path: Path
    width: int          # full-resolution width
    height: int         # full-resolution height
    scale: float        # preview/source factor (source = preview / scale)
    gray: np.ndarray    # preview grayscale, float32 in [0, 1]


@dataclass(slots=True)
class DeepCorrespondence:
    """Matched points in preview coordinates plus per-image preview scales."""

    points_left: np.ndarray   # (N, 2) preview coords in the left image
    points_right: np.ndarray  # (N, 2) preview coords in the right image
    left_scale: float
    right_scale: float
    confidence: np.ndarray    # (N,)


class DeepMatcher:
    """Wraps a learned matcher and exposes a uniform pairwise ``match`` API."""

    def __init__(self, kind: str, device: str, torch, kornia) -> None:
        self.kind = kind
        self.device = device
        self._torch = torch
        self._kornia = kornia
        self.input_dim = max(512, int(settings.stitch_matcher_input_dim))
        self.min_confidence = float(settings.stitch_matcher_min_confidence)
        self.max_matches = max(100, int(settings.stitch_matcher_max_matches))
        self._model = None
        self._extractor = None
        self._lightglue = None
        self._build()

    # -- model construction ------------------------------------------------
    def _build(self) -> None:
        K = self._kornia
        torch = self._torch
        if self.kind == "loftr":
            self._model = K.feature.LoFTR(pretrained="outdoor").to(self.device).eval()
            return

        # LightGlue-based backends: extractor + LightGlue graph matcher.
        feature_name = {
            "disk_lightglue": "disk",
            "aliked_lightglue": "aliked",
            "sift_lightglue": "sift",
        }[self.kind]

        if feature_name == "disk":
            self._extractor = K.feature.DISK.from_pretrained("depth").to(self.device).eval()
        elif feature_name == "aliked":
            self._extractor = K.feature.ALIKED().to(self.device).eval()
        else:  # sift
            self._extractor = K.feature.SIFTFeature(num_features=4096).to(self.device).eval()

        self._lightglue = K.feature.LightGlueMatcher(feature_name).to(self.device).eval()
        self._feature_name = feature_name

    # -- image preparation -------------------------------------------------
    def prepare(self, path: Path) -> DeepImage:
        bgr = read_image_bgr(path)
        height, width = bgr.shape[:2]
        long_edge = max(width, height)
        scale = min(1.0, self.input_dim / float(long_edge))
        if scale < 0.999:
            gray = cv2.cvtColor(
                cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            )
        else:
            scale = 1.0
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = gray.astype(np.float32) / 255.0
        return DeepImage(index=-1, path=path, width=width, height=height, scale=scale, gray=gray)

    # -- tensor helpers ----------------------------------------------------
    def _to_tensor(self, gray: np.ndarray, multiple: int = 8):
        torch = self._torch
        h, w = gray.shape[:2]
        new_h = _round_to_multiple(h, multiple)
        new_w = _round_to_multiple(w, multiple)
        if (new_h, new_w) != (h, w):
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        tensor = torch.from_numpy(gray)[None, None].to(self.device)
        sx = w / float(new_w)
        sy = h / float(new_h)
        return tensor, sx, sy

    # -- matching ----------------------------------------------------------
    def match(self, left: DeepImage, right: DeepImage) -> DeepCorrespondence | None:
        if self.kind == "loftr":
            return self._match_loftr(left, right)
        return self._match_lightglue(left, right)

    def _match_loftr(self, left: DeepImage, right: DeepImage) -> DeepCorrespondence | None:
        torch = self._torch
        t0, sx0, sy0 = self._to_tensor(left.gray)
        t1, sx1, sy1 = self._to_tensor(right.gray)
        with torch.inference_mode():
            out = self._model({"image0": t0, "image1": t1})
        pts0 = out["keypoints0"].detach().cpu().numpy()
        pts1 = out["keypoints1"].detach().cpu().numpy()
        conf = out["confidence"].detach().cpu().numpy()
        if pts0.shape[0] == 0:
            return None
        keep = conf >= self.min_confidence
        pts0, pts1, conf = pts0[keep], pts1[keep], conf[keep]
        if pts0.shape[0] == 0:
            return None
        # Undo the divisible-by-8 resize so points are in preview coordinates.
        pts0 = pts0 * np.array([sx0, sy0], dtype=np.float32)
        pts1 = pts1 * np.array([sx1, sy1], dtype=np.float32)
        return self._cap(pts0, pts1, conf, left.scale, right.scale)

    def _match_lightglue(self, left: DeepImage, right: DeepImage) -> DeepCorrespondence | None:
        torch = self._torch
        K = self._kornia
        t0, sx0, sy0 = self._to_tensor(left.gray, multiple=16)
        t1, sx1, sy1 = self._to_tensor(right.gray, multiple=16)
        with torch.inference_mode():
            feats0 = self._extract(t0)
            feats1 = self._extract(t1)
            lafs0, _, desc0 = feats0
            lafs1, _, desc1 = feats1
            hw0 = torch.tensor(t0.shape[2:], device=self.device)
            hw1 = torch.tensor(t1.shape[2:], device=self.device)
            _, idxs = self._lightglue(desc0, desc1, lafs0, lafs1, hw1=hw1, hw2=hw0)
        if idxs is None or idxs.shape[0] == 0:
            return None
        kpts0 = K.feature.get_laf_center(lafs0).reshape(-1, 2)
        kpts1 = K.feature.get_laf_center(lafs1).reshape(-1, 2)
        i0 = idxs[:, 0].detach().cpu().numpy()
        i1 = idxs[:, 1].detach().cpu().numpy()
        pts0 = kpts0.detach().cpu().numpy()[i0] * np.array([sx0, sy0], dtype=np.float32)
        pts1 = kpts1.detach().cpu().numpy()[i1] * np.array([sx1, sy1], dtype=np.float32)
        conf = np.ones(pts0.shape[0], dtype=np.float32)
        return self._cap(pts0, pts1, conf, left.scale, right.scale)

    def _extract(self, tensor):
        K = self._kornia
        torch = self._torch
        if self._feature_name == "disk":
            features = self._extractor(tensor, n=4096, pad_if_not_divisible=True)[0]
            kpts = features.keypoints[None]
            desc = features.descriptors[None]
            lafs = K.feature.laf_from_center_scale_ori(
                kpts, torch.ones(1, kpts.shape[1], 1, 1, device=self.device)
            )
            return lafs, None, desc
        # SIFTFeature / ALIKED return (lafs, responses, descriptors)
        lafs, resp, desc = self._extractor(tensor)
        return lafs, resp, desc

    def _cap(self, pts0, pts1, conf, left_scale, right_scale) -> DeepCorrespondence:
        if pts0.shape[0] > self.max_matches:
            order = np.argsort(conf)[::-1][: self.max_matches]
            pts0, pts1, conf = pts0[order], pts1[order], conf[order]
        return DeepCorrespondence(
            points_left=pts0.astype(np.float64),
            points_right=pts1.astype(np.float64),
            left_scale=float(left_scale),
            right_scale=float(right_scale),
            confidence=conf.astype(np.float64),
        )


def resolve_backend() -> str:
    """Return the effective learned backend, or "classic" if none applies."""
    requested = str(getattr(settings, "stitch_matcher", "auto")).lower()
    if requested in {"classic", "none", "off", "sift", "orb"}:
        return "classic"
    if requested in _LEARNED_BACKENDS:
        return requested
    # auto: prefer LoFTR when torch+kornia are present.
    torch, kornia = _torch_available()
    if torch is None:
        return "classic"
    return "loftr"


def create_matcher(log: LogFn = _noop) -> DeepMatcher | None:
    """Instantiate the configured learned matcher, or return None to fall back."""
    backend = resolve_backend()
    if backend == "classic":
        return None

    torch, kornia = _torch_available()
    if torch is None:
        log("[deep] torch/kornia not installed; using classical matcher")
        return None

    try:
        device = _resolve_device(torch, settings.stitch_matcher_device)
        matcher = DeepMatcher(backend, device, torch, kornia)
        log(f"[deep] learned matcher ready: backend={backend}, device={device}, input_dim={matcher.input_dim}")
        return matcher
    except Exception as exc:  # pragma: no cover - depends on optional weights
        log(f"[deep] learned matcher init failed ({exc}); using classical matcher")
        return None

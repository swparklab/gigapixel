"""Photometric stereo: recover surface normals and albedo from a light stack.

Heritage surfaces carry information in their relief — brushstrokes, tool marks,
inscriptions — that a flat mosaic loses. Given several images of a static object
under different known light directions, classical Lambertian photometric stereo
recovers a per-pixel surface normal map and albedo, the basis of RTI-style
relief visualisation.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(slots=True)
class PhotometricResult:
    normals: np.ndarray  # HxWx3 float, unit vectors
    albedo: np.ndarray   # HxW float 0..1
    normal_map_bgr: np.ndarray  # HxWx3 uint8, tangent-space normal map


def _normalize_light_dirs(light_dirs) -> np.ndarray:
    L = np.asarray(light_dirs, dtype=np.float64)
    norm = np.linalg.norm(L, axis=1, keepdims=True)
    return L / np.maximum(norm, 1e-9)


def photometric_stereo(images: list[np.ndarray], light_dirs) -> PhotometricResult:
    """images: N grayscale-or-BGR frames; light_dirs: N x 3 unit vectors."""
    if len(images) < 3:
        raise ValueError("Photometric stereo needs at least 3 lit images.")
    if len(images) != len(light_dirs):
        raise ValueError("images and light_dirs must have the same length.")

    grays = []
    shape = images[0].shape[:2]
    for image in images:
        g = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if g.shape[:2] != shape:
            g = cv2.resize(g, (shape[1], shape[0]))
        grays.append(g.astype(np.float64) / 255.0)

    L = _normalize_light_dirs(light_dirs)            # (N,3)
    I = np.stack([g.reshape(-1) for g in grays], axis=0)  # (N, P)

    # Solve L g = I for g (= albedo * normal) per pixel via least squares.
    L_pinv = np.linalg.pinv(L)                        # (3,N)
    G = L_pinv @ I                                    # (3, P)
    albedo = np.linalg.norm(G, axis=0)               # (P,)
    normals = G / np.maximum(albedo, 1e-6)           # (3, P)

    h, w = shape
    normals_img = normals.T.reshape(h, w, 3)
    albedo_img = np.clip(albedo.reshape(h, w), 0.0, 1.0)

    # Encode tangent-space normal map: (n+1)/2 -> 0..255, channels X,Y,Z -> B? use RGB.
    encoded = np.clip((normals_img * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
    normal_map_bgr = cv2.cvtColor(encoded, cv2.COLOR_RGB2BGR)
    return PhotometricResult(normals=normals_img, albedo=albedo_img, normal_map_bgr=normal_map_bgr)

"""Rights protection & tamper authentication for heritage content.

Implements the KOCCA platform's copyright-protection pillar:

* **Invisible watermark** — a blind DCT quantisation-index-modulation (QIM)
  watermark embeds a per-recipient identifier into the luminance channel,
  redundantly across 8x8 blocks, surviving mild recompression while remaining
  visually imperceptible. The same identifier can later be *extracted* to prove
  provenance / trace the recipient ("사용자별 고유 식별자 부여 및 삽입").
* **Tamper authentication** — a perceptual hash (pHash) plus a SHA-256 of the
  issued file detect modification / forgery ("위·변조 방지").

All classical and dependency-free.
"""

from __future__ import annotations

import hashlib

import cv2
import numpy as np

from ..config import settings


def payload_bits(payload: str, n_bits: int) -> np.ndarray:
    """Deterministic bit-string for an identifier (SHA-256 expanded to n_bits)."""
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    bits = np.unpackbits(np.frombuffer(digest, dtype=np.uint8))
    if n_bits <= len(bits):
        return bits[:n_bits].astype(np.int32)
    reps = int(np.ceil(n_bits / len(bits)))
    return np.tile(bits, reps)[:n_bits].astype(np.int32)


# Mid-frequency DCT coefficient used to carry one bit per 8x8 block.
_COEFF = (4, 3)


def embed_watermark(bgr: np.ndarray, payload: str) -> np.ndarray:
    """Return a copy of ``bgr`` with ``payload`` invisibly embedded."""
    n = max(8, int(settings.watermark_bits))
    step = float(settings.watermark_strength)
    bits = payload_bits(payload, n)

    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    y = ycrcb[:, :, 0]
    h, w = y.shape
    bh, bw = h // 8, w // 8
    u, v = _COEFF
    k = 0
    for by in range(bh):
        for bx in range(bw):
            block = y[by * 8 : by * 8 + 8, bx * 8 : bx * 8 + 8]
            dct = cv2.dct(block)
            bit = int(bits[k % n])
            q = np.round(dct[u, v] / step)
            if (int(q) & 1) != bit:
                q += 1.0  # set parity to carry the bit
            dct[u, v] = q * step
            y[by * 8 : by * 8 + 8, bx * 8 : bx * 8 + 8] = cv2.idct(dct)
            k += 1
    ycrcb[:, :, 0] = np.clip(y, 0, 255)
    return cv2.cvtColor(ycrcb.astype(np.uint8), cv2.COLOR_YCrCb2BGR)


def extract_bits(bgr: np.ndarray) -> np.ndarray:
    """Recover the embedded bit-string by majority vote across blocks."""
    n = max(8, int(settings.watermark_bits))
    step = float(settings.watermark_strength)
    y = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)[:, :, 0]
    h, w = y.shape
    bh, bw = h // 8, w // 8
    u, v = _COEFF
    votes = np.zeros((n, 2), dtype=np.int64)
    k = 0
    for by in range(bh):
        for bx in range(bw):
            block = y[by * 8 : by * 8 + 8, bx * 8 : bx * 8 + 8]
            dct = cv2.dct(block)
            bit = int(np.round(dct[u, v] / step)) & 1
            votes[k % n, bit] += 1
            k += 1
    return (votes[:, 1] >= votes[:, 0]).astype(np.int32)


def verify_payload(bgr: np.ndarray, payload: str) -> dict:
    """Match fraction between the recovered watermark and an expected payload."""
    expected = payload_bits(payload, max(8, int(settings.watermark_bits)))
    recovered = extract_bits(bgr)
    match = float(np.mean(recovered == expected))
    return {"match_fraction": round(match, 4), "watermark_present": bool(match >= 0.85)}


def perceptual_hash(bgr: np.ndarray) -> str:
    """64-bit DCT perceptual hash (hex) for tamper / duplicate detection."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)[:8, :8]
    med = np.median(dct[1:, 1:])
    bits = (dct > med).flatten()
    value = 0
    for b in bits[:64]:
        value = (value << 1) | int(b)
    return f"{value:016x}"


def hamming_distance(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64

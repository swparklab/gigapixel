"""Tiered access control and signed licence tokens.

Implements the KOCCA "단계별 활용 권한 관리 / 인증 사용자별" requirement: an
HMAC-SHA256 signed, expiring licence token carries a recipient and an access
*tier*. Tiers are ordered (most → least privileged) by ``license_tiers`` and
gate which download variants a request may obtain.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json

from ..config import settings


def _secret() -> bytes:
    s = str(settings.license_secret or "")
    # Dev fallback: a fixed key so tokens are still verifiable locally.
    return (s or "hga-dev-license-secret").encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def tiers() -> list[str]:
    return list(settings.license_tiers)


def tier_rank(tier: str) -> int:
    t = tiers()
    return t.index(tier) if tier in t else len(t)


def issue_token(recipient: str, tier: str, days: int = 365) -> dict:
    if tier not in tiers():
        tier = tiers()[-1]
    now = dt.datetime.now(dt.UTC)
    payload = {
        "recipient": recipient,
        "tier": tier,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(days=max(1, days))).timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    token = f"{body}.{sig}"
    return {"token": token, **payload, "signed": bool(settings.license_secret)}


def verify_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return {"valid": False, "reason": "malformed"}
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return {"valid": False, "reason": "bad_signature"}
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return {"valid": False, "reason": "malformed_payload"}
    now = int(dt.datetime.now(dt.UTC).timestamp())
    if int(payload.get("exp", 0)) < now:
        return {"valid": False, "reason": "expired", **payload}
    return {"valid": True, **payload}


# Which download variants each tier may obtain.
_TIER_VARIANTS = {
    "owner": {"raw", "optimized", "watermarked", "enhanced", "upscaled", "archive"},
    "researcher": {"optimized", "watermarked", "enhanced", "upscaled"},
    "viewer": {"watermarked"},
}


def tier_allows(tier: str, variant: str) -> bool:
    return variant in _TIER_VARIANTS.get(tier, _TIER_VARIANTS["viewer"])

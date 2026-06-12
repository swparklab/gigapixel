"""IIIF interoperability descriptors.

The cultural-heritage ecosystem (Mirador, Universal Viewer, aggregators) speaks
IIIF. Alongside the DZI tiles we emit a IIIF Image API 3.0 ``info.json`` and a
Presentation API 3.0 ``manifest.json`` describing the mosaic, so it can be
consumed by standard IIIF viewers and harvested by repositories.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from ..config import settings


def _base(session_id: str) -> str:
    base = str(settings.iiif_base_url).rstrip("/")
    prefix = f"{base}{settings.api_prefix}" if base else settings.api_prefix
    return f"{prefix}/sessions/{session_id}/iiif"


def build_info(session_id: str, width: int, height: int) -> dict:
    tile = int(settings.tile_size)
    scale_factors = []
    factor = 1
    while width // factor > tile or height // factor > tile:
        scale_factors.append(factor)
        factor *= 2
    scale_factors.append(factor)
    max_size = int(settings.iiif_max_size)
    return {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": _base(session_id),
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        # level2 = arbitrary region/size/rotation/quality served live.
        "profile": "level2",
        "width": int(width),
        "height": int(height),
        "maxWidth": max_size,
        "maxHeight": max_size,
        "tiles": [{"width": tile, "height": tile, "scaleFactors": scale_factors}],
        "extraFormats": ["jpg", "png"],
        "extraQualities": ["color", "gray", "bitonal", "default"],
        "extraFeatures": [
            "regionByPx",
            "regionByPct",
            "regionSquare",
            "sizeByW",
            "sizeByH",
            "sizeByWh",
            "sizeByPct",
            "sizeByConfinedWh",
            "rotationBy90s",
            "rotationArbitrary",
            "mirroring",
        ],
    }


def build_manifest(session_id: str, width: int, height: int) -> dict:
    base = _base(session_id)
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{base}/manifest",
        "type": "Manifest",
        "label": {"en": [f"Gigapixel heritage mosaic {session_id}"]},
        "items": [
            {
                "id": f"{base}/canvas/1",
                "type": "Canvas",
                "width": int(width),
                "height": int(height),
                "items": [
                    {
                        "id": f"{base}/page/1",
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "id": f"{base}/annotation/1",
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {
                                    "id": f"{base}/full/max/0/default.jpg",
                                    "type": "Image",
                                    "format": "image/jpeg",
                                    "width": int(width),
                                    "height": int(height),
                                    "service": [build_info(session_id, width, height)],
                                },
                                "target": f"{base}/canvas/1",
                            }
                        ],
                    }
                ],
            }
        ],
    }


# --- live IIIF Image API 3.0 rendering -------------------------------------
class IIIFError(ValueError):
    pass


def _parse_region(region: str, width: int, height: int) -> tuple[int, int, int, int]:
    region = region.lower()
    if region in ("full",):
        return 0, 0, width, height
    if region == "square":
        side = min(width, height)
        return (width - side) // 2, (height - side) // 2, side, side
    pct = region.startswith("pct:")
    body = region[4:] if pct else region
    try:
        x, y, w, h = (float(v) for v in body.split(","))
    except Exception as exc:
        raise IIIFError(f"bad region: {region}") from exc
    if pct:
        x, y, w, h = x / 100 * width, y / 100 * height, w / 100 * width, h / 100 * height
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    x = max(0, min(x, width))
    y = max(0, min(y, height))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return x, y, w, h


def _parse_size(size: str, rw: int, rh: int, cap: int) -> tuple[int, int]:
    size = size.lower().lstrip("^")  # allow upscaling marker, treat same
    if size in ("max", "full"):
        tw, th = rw, rh
    elif size.startswith("pct:"):
        scale = float(size[4:]) / 100.0
        tw, th = rw * scale, rh * scale
    elif size.startswith("!"):
        bw, bh = (float(v) if v else None for v in size[1:].split(","))
        scale = min((bw / rw) if bw else 1e9, (bh / rh) if bh else 1e9)
        tw, th = rw * scale, rh * scale
    else:
        sw, sh = ((float(v) if v else None) for v in size.split(","))
        if sw and sh:
            tw, th = sw, sh
        elif sw:
            tw, th = sw, rh * (sw / rw)
        elif sh:
            tw, th = rw * (sh / rh), sh
        else:
            raise IIIFError(f"bad size: {size}")
    tw, th = max(1, int(round(tw))), max(1, int(round(th)))
    longest = max(tw, th)
    if longest > cap:
        ratio = cap / longest
        tw, th = max(1, int(tw * ratio)), max(1, int(th * ratio))
    return tw, th


def render_iiif(raw_path: Path, region: str, size: str, rotation: str, quality: str, fmt: str) -> tuple[bytes, str]:
    """Serve a IIIF Image API 3.0 request from the raw mosaic. Returns (bytes, media_type)."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = None
    fmt = fmt.lower()
    if fmt not in ("jpg", "jpeg", "png"):
        raise IIIFError(f"unsupported format: {fmt}")

    with Image.open(raw_path) as source:
        width, height = source.size
        x, y, w, h = _parse_region(region, width, height)
        tile = source.crop((x, y, x + w, y + h)).convert("RGB")

    tw, th = _parse_size(size, w, h, int(settings.iiif_max_size))
    if (tw, th) != (w, h):
        tile = tile.resize((tw, th), Image.LANCZOS)

    mirror = rotation.startswith("!")
    angle = float(rotation[1:] if mirror else rotation or "0")
    if mirror:
        tile = ImageOps.mirror(tile)
    if angle % 360 != 0:
        tile = tile.rotate(-angle, expand=True, fillcolor=(255, 255, 255))

    quality = quality.lower()
    if quality == "gray":
        tile = ImageOps.grayscale(tile).convert("RGB")
    elif quality == "bitonal":
        tile = tile.convert("L").point(lambda p: 255 if p > 127 else 0).convert("RGB")

    buffer = io.BytesIO()
    if fmt == "png":
        tile.save(buffer, format="PNG")
        media = "image/png"
    else:
        tile.save(buffer, format="JPEG", quality=90, progressive=True)
        media = "image/jpeg"
    return buffer.getvalue(), media


def write_iiif(session_id: str, width: int, height: int, output_base: Path) -> tuple[Path, Path]:
    iiif_dir = output_base / "iiif"
    iiif_dir.mkdir(parents=True, exist_ok=True)
    info_path = iiif_dir / "info.json"
    manifest_path = iiif_dir / "manifest.json"
    info_path.write_text(json.dumps(build_info(session_id, width, height), indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(build_manifest(session_id, width, height), indent=2), encoding="utf-8")
    return info_path, manifest_path

import re
from pathlib import Path

import cv2
import numpy as np
from fastapi import HTTPException

from ..config import settings
from ..models import Session
from .storage import output_dir


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    return sanitized or "session"


def media_type_for_image(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".tif", ".tiff"}:
        return "image/tiff"
    return "image/jpeg"


def resolve_raw_image_path(session: Session) -> Path:
    candidates: list[Path] = []
    if session.stitched_image_path:
        candidates.append(Path(session.stitched_image_path))

    base = output_dir(session.id)
    candidates.extend(
        [
            base / "stitched_raw.png",
            base / "stitched.png",
            base / "stitched.tif",
            base / "stitched.tiff",
            base / "stitched.jpg",
            base / "stitched.jpeg",
        ]
    )

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    raise HTTPException(status_code=404, detail="Raw stitched image file is missing")


def _ensure_optimized_from_raw(raw_path: Path, optimized_path: Path) -> None:
    file_bytes = np.fromfile(str(raw_path), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=500, detail="Failed to read raw stitched image")

    quality = int(max(1, min(100, settings.optimized_jpeg_quality)))
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            quality,
            cv2.IMWRITE_JPEG_PROGRESSIVE,
            1,
            cv2.IMWRITE_JPEG_OPTIMIZE,
            1,
        ],
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create optimized stitched image")

    optimized_path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(optimized_path))


def resolve_optimized_image_path(session: Session) -> Path:
    base = output_dir(session.id)
    optimized_path = base / "stitched_optimized.jpg"
    if optimized_path.exists() and optimized_path.is_file():
        return optimized_path

    raw_path = resolve_raw_image_path(session)
    _ensure_optimized_from_raw(raw_path, optimized_path)
    return optimized_path


def build_download_filename(session: Session, variant: str, file_path: Path) -> str:
    ext = file_path.suffix.lower() or ".jpg"
    return f"{sanitize_filename(session.name)}_{session.id}_{variant}{ext}"

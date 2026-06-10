from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..config import settings
from .feature_matching import disable_opencl, read_image_bgr
from .stitch_pipeline import run_scans_pipeline

try:
    import tifffile  # type: ignore
except Exception:  # pragma: no cover
    tifffile = None

Image.MAX_IMAGE_PIXELS = None

disable_opencl()


def _status_to_message(code: int | None) -> str:
    mapping = {
        cv2.Stitcher_OK: "OK",
        1: "ERR_NEED_MORE_IMGS",
        2: "ERR_HOMOGRAPHY_EST_FAIL",
        3: "ERR_CAMERA_PARAMS_ADJUST_FAIL",
    }
    return mapping.get(code, f"UNKNOWN_ERROR_{code}")


def _is_memory_error(exc: cv2.error) -> bool:
    text = str(exc)
    markers = (
        "CL_MEM_OBJECT_ALLOCATION_FAILURE",
        "OpenCLAllocator",
        "Insufficient memory",
        "OutOfMemory",
        "bad allocation",
    )
    return any(marker in text for marker in markers)


def _read_image(path: Path):
    return read_image_bgr(path)


def _make_stitcher(mode: str, *, registration_mpx: float, seam_mpx: float, confidence: float):
    stitch_mode = cv2.Stitcher_SCANS if mode == "scans" else cv2.Stitcher_PANORAMA
    stitcher = cv2.Stitcher_create(stitch_mode)

    # Fallback path only. Scans use the modular full-resolution pipeline first.
    stitcher.setRegistrationResol(float(registration_mpx))
    stitcher.setSeamEstimationResol(float(seam_mpx))
    stitcher.setCompositingResol(float(settings.stitch_compositing_megapix))
    stitcher.setPanoConfidenceThresh(float(confidence))
    stitcher.setInterpolationFlags(cv2.INTER_LANCZOS4)
    stitcher.setWaveCorrection(mode != "scans")
    return stitcher


def _stitch_with_profile(read_images: list, mode: str, profile: dict[str, float]):
    stitcher = _make_stitcher(
        mode,
        registration_mpx=profile["registration_mpx"],
        seam_mpx=profile["seam_mpx"],
        confidence=profile["confidence"],
    )
    return stitcher.stitch(read_images)


def _format_pipeline_logs(logs: list[str]) -> str:
    if not logs:
        return ""
    return " Last stages: " + " | ".join(logs[-8:])


def stitch_images(image_paths: list[Path], mode: str = "scans") -> tuple[bool, str, object | None]:
    if len(image_paths) < 2:
        return False, "At least 2 images are required for stitching.", None

    disable_opencl()

    planar_message = ""
    if mode == "scans" and settings.stitch_planar_enabled:
        result = run_scans_pipeline(image_paths)
        planar_message = result.message + _format_pipeline_logs(result.logs)
        if result.success and result.image is not None:
            return True, planar_message, result.image

    try:
        read_images = [_read_image(path) for path in image_paths]
    except ValueError as exc:
        return False, str(exc), None

    high_precision = {
        "registration_mpx": settings.stitch_registration_megapix,
        "seam_mpx": settings.stitch_seam_megapix,
        "confidence": settings.stitch_confidence_threshold,
    }
    balanced_retry = {
        "registration_mpx": max(1.0, settings.stitch_registration_megapix * 0.6),
        "seam_mpx": max(0.3, settings.stitch_seam_megapix * 0.5),
        "confidence": min(settings.stitch_confidence_threshold, 0.45),
    }

    last_status = None
    last_error = None
    for profile_name, profile in (("high-precision", high_precision), ("balanced-retry", balanced_retry)):
        try:
            disable_opencl()
            status, stitched = _stitch_with_profile(read_images, mode, profile)
        except cv2.error as exc:
            last_error = exc
            if _is_memory_error(exc):
                continue
            return False, f"OpenCV fallback failed ({profile_name}): {exc}. {planar_message}", None

        last_status = status
        if status == cv2.Stitcher_OK and stitched is not None:
            fallback_note = f" Planar attempt: {planar_message}" if planar_message else ""
            return True, f"Stitching completed with OpenCV fallback {profile_name} profile.{fallback_note}", stitched

    if last_error is not None:
        return (
            False,
            f"{planar_message} OpenCV fallback failed because it could not allocate enough memory after disabling "
            f"OpenCL. Last error: {last_error}",
            None,
        )

    return False, f"{planar_message} OpenCV fallback failed: {_status_to_message(last_status)}", None


def save_stitched_image(stitched, output_path: Path) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ext = output_path.suffix.lower() if output_path.suffix else ".jpg"
    if ext in {".tif", ".tiff"}:
        _save_bigtiff(stitched, output_path)
    else:
        ok, encoded = cv2.imencode(ext, stitched)
        if ok:
            encoded.tofile(str(output_path))
        if not ok:
            raise RuntimeError(f"Failed to save stitched image to {output_path}")
    height, width = stitched.shape[:2]
    return width, height


def _bgr_to_rgb(stitched):
    if stitched.ndim == 2:
        return np.ascontiguousarray(stitched)
    if stitched.ndim == 3 and stitched.shape[2] == 3:
        return np.ascontiguousarray(stitched[:, :, ::-1])
    if stitched.ndim == 3 and stitched.shape[2] == 4:
        return np.ascontiguousarray(stitched[:, :, [2, 1, 0, 3]])
    raise RuntimeError(f"Unsupported stitched image shape for BigTIFF: {stitched.shape}")


def _tiff_compression():
    value = str(settings.raw_bigtiff_compression or "none").lower()
    if value in {"", "none", "raw", "uncompressed"}:
        return None
    return value


def _tiff_tile_shape():
    if not bool(getattr(settings, "raw_bigtiff_tiled", True)):
        return None
    size = int(getattr(settings, "raw_bigtiff_tile_size", 512))
    # tifffile requires tile dimensions to be multiples of 16.
    size = max(16, (size // 16) * 16)
    return (size, size)


def _save_bigtiff_with_tifffile(rgb, output_path: Path) -> bool:
    if tifffile is None:
        return False
    tile = _tiff_tile_shape()
    kwargs = dict(
        bigtiff=True,
        photometric="rgb" if rgb.ndim == 3 else "minisblack",
        metadata=None,
        compression=_tiff_compression(),
    )
    # Prefer a tiled layout for efficient partial reads at gigapixel scale.
    if tile is not None and rgb.shape[0] >= tile[0] and rgb.shape[1] >= tile[1]:
        try:
            tifffile.imwrite(str(output_path), rgb, tile=tile, **kwargs)
            return True
        except Exception:
            pass
    try:
        tifffile.imwrite(str(output_path), rgb, **kwargs)
        return True
    except Exception:
        return False


def _save_bigtiff_with_pillow(rgb, output_path: Path) -> None:
    if rgb.ndim == 2:
        image = Image.fromarray(rgb)
    else:
        mode = "RGBA" if rgb.shape[2] == 4 else "RGB"
        image = Image.fromarray(rgb, mode)
    compression = "raw" if _tiff_compression() is None else str(settings.raw_bigtiff_compression)
    image.save(output_path, format="TIFF", big_tiff=True, compression=compression)


def _save_bigtiff(stitched, output_path: Path) -> None:
    rgb = _bgr_to_rgb(stitched)
    if _save_bigtiff_with_tifffile(rgb, output_path):
        return
    _save_bigtiff_with_pillow(rgb, output_path)


def save_stitched_variants(
    stitched,
    raw_output_path: Path,
    optimized_output_path: Path,
    optimized_jpeg_quality: int = 85,
) -> tuple[int, int]:
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    optimized_output_path.parent.mkdir(parents=True, exist_ok=True)

    # Raw: BigTIFF, lossless, high-resolution output with 64-bit offsets.
    _save_bigtiff(stitched, raw_output_path)

    # Optimized: same resolution, smaller size with JPEG compression.
    jpeg_quality = int(max(1, min(100, optimized_jpeg_quality)))
    opt_ok, opt_encoded = cv2.imencode(
        ".jpg",
        stitched,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            jpeg_quality,
            cv2.IMWRITE_JPEG_PROGRESSIVE,
            1,
            cv2.IMWRITE_JPEG_OPTIMIZE,
            1,
        ],
    )
    if not opt_ok:
        raise RuntimeError(f"Failed to save optimized stitched image to {optimized_output_path}")
    opt_encoded.tofile(str(optimized_output_path))

    height, width = stitched.shape[:2]
    return width, height

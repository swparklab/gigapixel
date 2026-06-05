from pathlib import Path

import cv2
import numpy as np

from ..config import settings


def _disable_opencl() -> None:
    """Keep large stitching jobs on CPU RAM instead of fragile OpenCL buffers."""
    if hasattr(cv2, "ocl"):
        try:
            cv2.ocl.setUseOpenCL(False)
        except cv2.error:
            pass


_disable_opencl()


def _status_to_message(code: int) -> str:
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
    # Windows Unicode path safe read.
    file_bytes = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to read image: {path.name}")
    return image


def _make_stitcher(mode: str, *, registration_mpx: float, seam_mpx: float, confidence: float):
    stitch_mode = cv2.Stitcher_SCANS if mode == "scans" else cv2.Stitcher_PANORAMA
    stitcher = cv2.Stitcher_create(stitch_mode)

    # OpenCV defaults are registration=0.6MP and seam=0.1MP. They are fast, but
    # too coarse for heritage scans. Use denser estimation and compose at source
    # resolution so the downloadable raw result stays full fidelity.
    stitcher.setRegistrationResol(float(registration_mpx))
    stitcher.setSeamEstimationResol(float(seam_mpx))
    stitcher.setCompositingResol(float(settings.stitch_compositing_megapix))
    stitcher.setPanoConfidenceThresh(float(confidence))
    stitcher.setInterpolationFlags(cv2.INTER_LANCZOS4)

    # Wave correction is useful for handheld panoramas, but it can bend flat scans.
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


def stitch_images(image_paths: list[Path], mode: str = "scans") -> tuple[bool, str, object | None]:
    if len(image_paths) < 2:
        return False, "At least 2 images are required for stitching.", None

    _disable_opencl()

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
            _disable_opencl()
            status, stitched = _stitch_with_profile(read_images, mode, profile)
        except cv2.error as exc:
            last_error = exc
            if _is_memory_error(exc):
                continue
            return False, f"Stitching failed ({profile_name}): {exc}", None

        last_status = status
        if status == cv2.Stitcher_OK and stitched is not None:
            return True, f"Stitching completed with {profile_name} profile.", stitched

    if last_error is not None:
        return (
            False,
            "Stitching failed because OpenCV could not allocate enough memory after disabling OpenCL. "
            f"Last error: {last_error}",
            None,
        )

    return False, f"Stitching failed: {_status_to_message(last_status)}", None


def save_stitched_image(stitched, output_path: Path) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ext = output_path.suffix.lower() if output_path.suffix else ".jpg"
    ok, encoded = cv2.imencode(ext, stitched)
    if ok:
        encoded.tofile(str(output_path))
    if not ok:
        raise RuntimeError(f"Failed to save stitched image to {output_path}")
    height, width = stitched.shape[:2]
    return width, height


def save_stitched_variants(
    stitched,
    raw_output_path: Path,
    optimized_output_path: Path,
    optimized_jpeg_quality: int = 85,
) -> tuple[int, int]:
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    optimized_output_path.parent.mkdir(parents=True, exist_ok=True)

    # Raw: lossless, high-resolution output with minimal processing.
    raw_ok, raw_encoded = cv2.imencode(
        ".png",
        stitched,
        [cv2.IMWRITE_PNG_COMPRESSION, 0],
    )
    if not raw_ok:
        raise RuntimeError(f"Failed to save raw stitched image to {raw_output_path}")
    raw_encoded.tofile(str(raw_output_path))

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

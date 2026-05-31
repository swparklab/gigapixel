from pathlib import Path

import cv2
import numpy as np


def _status_to_message(code: int) -> str:
    mapping = {
        cv2.Stitcher_OK: "OK",
        1: "ERR_NEED_MORE_IMGS",
        2: "ERR_HOMOGRAPHY_EST_FAIL",
        3: "ERR_CAMERA_PARAMS_ADJUST_FAIL",
    }
    return mapping.get(code, f"UNKNOWN_ERROR_{code}")


def stitch_images(image_paths: list[Path], mode: str = "scans") -> tuple[bool, str, object | None]:
    if len(image_paths) < 2:
        return False, "At least 2 images are required for stitching.", None

    read_images = []
    for path in image_paths:
        # Windows Unicode path safe read.
        file_bytes = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if image is None:
            return False, f"Unable to read image: {path.name}", None
        read_images.append(image)

    stitch_mode = cv2.Stitcher_SCANS if mode == "scans" else cv2.Stitcher_PANORAMA
    stitcher = cv2.Stitcher_create(stitch_mode)
    status, stitched = stitcher.stitch(read_images)

    if status != cv2.Stitcher_OK or stitched is None:
        return False, f"Stitching failed: {_status_to_message(status)}", None

    return True, "Stitching completed.", stitched


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

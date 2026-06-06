from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..config import settings

LogFn = Callable[[str], None]


@dataclass(slots=True)
class ImageInfo:
    index: int
    path: Path
    width: int
    height: int
    orientation: str


@dataclass(slots=True)
class FeatureSet:
    index: int
    path: Path
    width: int
    height: int
    scale: float
    keypoints: list
    descriptors: np.ndarray | None
    detector: str


@dataclass(slots=True)
class PairMatch:
    left: int
    right: int
    h_left_to_right: np.ndarray
    points_left: np.ndarray
    points_right: np.ndarray
    inliers: int
    median_error: float
    score: float


def disable_opencl() -> None:
    if hasattr(cv2, "ocl"):
        try:
            cv2.ocl.setUseOpenCL(False)
        except cv2.error:
            pass


disable_opencl()
Image.MAX_IMAGE_PIXELS = None


def _noop(_: str) -> None:
    return


def _exif_orientation(image: Image.Image) -> int:
    try:
        return int(image.getexif().get(274, 1))
    except Exception:
        return 1


def _oriented_size(width: int, height: int, orientation: int) -> tuple[int, int]:
    if orientation in {5, 6, 7, 8}:
        return height, width
    return width, height


def read_image_info(path: Path, index: int) -> ImageInfo:
    with Image.open(path) as image:
        orientation = _exif_orientation(image)
        width, height = _oriented_size(*image.size, orientation)
    direction = "landscape" if width >= height else "portrait"
    return ImageInfo(index=index, path=path, width=width, height=height, orientation=direction)


def validate_image_set(image_paths: list[Path], log: LogFn = _noop) -> list[ImageInfo]:
    if len(image_paths) < 2:
        raise ValueError("At least 2 images are required for stitching.")

    infos = [read_image_info(path, idx) for idx, path in enumerate(image_paths)]
    directions = {info.orientation for info in infos}
    if len(directions) > 1:
        log("[validate] mixed image directions detected; EXIF rotation is applied before registration.")

    widths = [info.width for info in infos]
    heights = [info.height for info in infos]
    if min(widths) <= 0 or min(heights) <= 0:
        raise ValueError("Invalid image dimensions detected.")

    max_width_ratio = max(widths) / max(1, min(widths))
    max_height_ratio = max(heights) / max(1, min(heights))
    if max_width_ratio > 3.0 or max_height_ratio > 3.0:
        log("[validate] large dimension variance detected; overlap graph will determine placement.")

    log(f"[validate] {len(infos)} images ready; first={infos[0].width}x{infos[0].height}")
    return infos


def read_image_bgr(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        if image.mode == "RGBA":
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, image).convert("RGB")
        else:
            image = image.convert("RGB")
        array = np.asarray(image)
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def make_preview(image: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    max_dim = max(256, int(settings.stitch_planar_preview_max_dim))
    scale = min(1.0, max_dim / float(max(width, height)))
    if scale >= 0.999:
        return image, 1.0
    preview = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return preview, scale


def _create_detector() -> tuple[object, str]:
    requested = str(getattr(settings, "stitch_feature_detector", "sift")).lower()
    if requested == "orb" or not hasattr(cv2, "SIFT_create"):
        return cv2.ORB_create(nfeatures=max(1000, int(settings.stitch_planar_max_features))), "orb"
    return (
        cv2.SIFT_create(
            nfeatures=max(500, int(settings.stitch_planar_max_features)),
            contrastThreshold=0.01,
            edgeThreshold=12,
            sigma=1.6,
        ),
        "sift",
    )


def detect_features(preview: np.ndarray) -> tuple[list, np.ndarray | None, str]:
    gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    detector, detector_name = _create_detector()
    keypoints, descriptors = detector.detectAndCompute(gray, None)
    if descriptors is None or len(keypoints) < 8:
        return [], None, detector_name
    if detector_name == "sift":
        descriptors = descriptors.astype(np.float32, copy=False)
    return keypoints, descriptors, detector_name


def build_feature_sets(image_paths: list[Path], log: LogFn = _noop) -> list[FeatureSet]:
    features: list[FeatureSet] = []
    for idx, path in enumerate(image_paths):
        image = read_image_bgr(path)
        height, width = image.shape[:2]
        preview, scale = make_preview(image)
        keypoints, descriptors, detector = detect_features(preview)
        features.append(
            FeatureSet(
                index=idx,
                path=path,
                width=width,
                height=height,
                scale=scale,
                keypoints=keypoints,
                descriptors=descriptors,
                detector=detector,
            )
        )
        log(
            f"[features] {idx + 1}/{len(image_paths)} {path.name}: "
            f"{len(keypoints)} keypoints, scale={scale:.4f}, detector={detector}"
        )
    return features


def _ratio_passed_matches(knn_matches, ratio: float):
    good = []
    for item in knn_matches:
        if len(item) < 2:
            continue
        first, second = item[0], item[1]
        if first.distance < ratio * second.distance:
            good.append(first)
    return good


def _mutual_matches(left: FeatureSet, right: FeatureSet):
    if left.descriptors is None or right.descriptors is None:
        return []
    if len(left.descriptors) < 2 or len(right.descriptors) < 2:
        return []

    ratio = float(settings.stitch_planar_match_ratio)
    if left.detector == "orb" or right.detector == "orb":
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    else:
        matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 96})

    forward = _ratio_passed_matches(matcher.knnMatch(left.descriptors, right.descriptors, k=2), ratio)
    reverse = _ratio_passed_matches(matcher.knnMatch(right.descriptors, left.descriptors, k=2), ratio)
    reverse_best = {match.queryIdx: match.trainIdx for match in reverse}
    return [match for match in forward if reverse_best.get(match.trainIdx) == match.queryIdx]


def _scale_matrix(scale: float) -> np.ndarray:
    return np.array([[scale, 0.0, 0.0], [0.0, scale, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _reasonable_transform(matrix: np.ndarray) -> bool:
    if matrix is None or not np.all(np.isfinite(matrix)):
        return False
    linear = matrix[:2, :2]
    determinant = float(np.linalg.det(linear))
    if determinant <= 0.05 or determinant > 20.0:
        return False
    try:
        _, singular_values, _ = np.linalg.svd(linear)
    except np.linalg.LinAlgError:
        return False
    return bool(singular_values[0] / max(singular_values[-1], 1e-6) <= 25.0)


def _estimate_transform(left: FeatureSet, right: FeatureSet, matches: list) -> PairMatch | None:
    pts_left = np.float32([left.keypoints[match.queryIdx].pt for match in matches])
    pts_right = np.float32([right.keypoints[match.trainIdx].pt for match in matches])
    model = str(settings.stitch_planar_transform_model).lower()
    threshold = float(settings.stitch_planar_ransac_threshold)

    matrix = None
    mask = None
    if model == "homography":
        matrix, mask = cv2.findHomography(pts_left, pts_right, cv2.RANSAC, threshold)
    else:
        estimator = cv2.estimateAffinePartial2D if model == "similarity" else cv2.estimateAffine2D
        affine, mask = estimator(
            pts_left,
            pts_right,
            method=cv2.RANSAC,
            ransacReprojThreshold=threshold,
            maxIters=5000,
            confidence=0.995,
            refineIters=20,
        )
        if affine is not None:
            matrix = np.vstack([affine, [0.0, 0.0, 1.0]])

    if matrix is None or mask is None:
        return None

    inlier_mask = mask.ravel().astype(bool)
    inliers = int(np.count_nonzero(inlier_mask))
    if inliers < int(settings.stitch_planar_min_inliers):
        return None

    preview_left = pts_left[inlier_mask]
    preview_right = pts_right[inlier_mask]
    projected = cv2.perspectiveTransform(preview_left.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    errors = np.linalg.norm(projected - preview_right, axis=1)
    median_error = float(np.median(errors)) if len(errors) else 999.0

    full_matrix = np.linalg.inv(_scale_matrix(right.scale)) @ matrix @ _scale_matrix(left.scale)
    if abs(full_matrix[2, 2]) > 1e-12:
        full_matrix = full_matrix / full_matrix[2, 2]
    if not _reasonable_transform(full_matrix):
        return None

    points_left = preview_left.astype(np.float64) / float(left.scale)
    points_right = preview_right.astype(np.float64) / float(right.scale)
    score = inliers / max(1.0, median_error + 1.0)
    return PairMatch(
        left=left.index,
        right=right.index,
        h_left_to_right=full_matrix.astype(np.float64),
        points_left=points_left,
        points_right=points_right,
        inliers=inliers,
        median_error=median_error,
        score=score,
    )


def pair_candidates(count: int):
    if count <= int(settings.stitch_planar_exhaustive_limit):
        for left in range(count):
            for right in range(left + 1, count):
                yield left, right
        return

    window = max(1, int(settings.stitch_planar_neighbor_window))
    for left in range(count):
        for right in range(left + 1, min(count, left + window + 1)):
            yield left, right


def estimate_pair_matches(features: list[FeatureSet], log: LogFn = _noop) -> list[PairMatch]:
    matches: list[PairMatch] = []
    tested = 0
    for left_idx, right_idx in pair_candidates(len(features)):
        tested += 1
        left = features[left_idx]
        right = features[right_idx]
        raw_matches = _mutual_matches(left, right)
        if len(raw_matches) < int(settings.stitch_planar_min_inliers):
            continue
        pair = _estimate_transform(left, right, raw_matches)
        if pair is None:
            continue
        matches.append(pair)
        log(
            f"[match] {left_idx}->{right_idx}: inliers={pair.inliers}, "
            f"median_error={pair.median_error:.3f}, score={pair.score:.2f}"
        )

    log(f"[match] tested={tested}, accepted={len(matches)}")
    return matches

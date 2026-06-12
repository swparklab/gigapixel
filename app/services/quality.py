"""Quality assessment for the final stitched mosaic.

After compositing, a mosaic can still be defective: interior holes where no
source covered the canvas, ghosting/misalignment from a bad transform, blur,
or visible seams. :func:`assess_stitch_quality` inspects the output image and
produces a structured :class:`QualityReport` with a verdict (``ok`` / ``warn``
/ ``broken``) plus the located defect regions, which the repair stage can then
inpaint.

Analysis runs on a bounded-resolution copy for speed; defect locations are
stored as fractional bounding boxes so they map back to full resolution
regardless of the analysis scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from ..config import settings

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return


@dataclass(slots=True)
class HoleRegion:
    # Fractional bounding box on the full image (0..1).
    x: float
    y: float
    w: float
    h: float
    area_fraction: float  # of the content area

    def to_dict(self) -> dict:
        return {
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "w": round(self.w, 6),
            "h": round(self.h, 6),
            "area_fraction": round(self.area_fraction, 8),
        }


@dataclass(slots=True)
class QualityReport:
    width: int
    height: int
    verdict: str = "ok"  # ok | warn | broken
    issues: list[str] = field(default_factory=list)
    coverage_ratio: float = 1.0
    content_fraction: float = 1.0
    interior_hole_area_fraction: float = 0.0
    hole_count: int = 0
    holes: list[HoleRegion] = field(default_factory=list)
    sharpness: float = 0.0
    seam_score: float = 0.0
    exposure_uniformity: float = 1.0
    perceptual_quality: float | None = None
    perceptual_backend: str | None = None
    registration_rms: float | None = None
    repairable: bool = False
    repaired: bool = False
    repair_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "verdict": self.verdict,
            "issues": self.issues,
            "metrics": {
                "coverage_ratio": round(self.coverage_ratio, 6),
                "content_fraction": round(self.content_fraction, 6),
                "interior_hole_area_fraction": round(self.interior_hole_area_fraction, 8),
                "hole_count": self.hole_count,
                "sharpness": round(self.sharpness, 4),
                "seam_score": round(self.seam_score, 6),
                "exposure_uniformity": round(self.exposure_uniformity, 6),
                "perceptual_quality": self.perceptual_quality,
                "perceptual_backend": self.perceptual_backend,
                "registration_rms": self.registration_rms,
            },
            "holes": [h.to_dict() for h in self.holes],
            "repairable": self.repairable,
            "repaired": self.repaired,
            "repair_actions": self.repair_actions,
        }


def _analysis_image(image: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    max_dim = max(512, int(settings.stitch_quality_max_dim))
    scale = min(1.0, max_dim / float(max(width, height)))
    if scale < 0.999:
        small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return small, scale
    return image, 1.0


def _empty_mask(image: np.ndarray) -> np.ndarray:
    threshold = int(settings.stitch_quality_empty_threshold)
    return (image.max(axis=2) <= threshold)


def _exposure_uniformity(gray: np.ndarray, content: np.ndarray) -> float:
    """1.0 = perfectly even illumination; lower = visible exposure stepping."""
    blur = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), max(gray.shape) / 40.0)
    values = blur[content]
    if values.size < 100:
        return 1.0
    mean = float(np.mean(values))
    if mean < 1.0:
        return 1.0
    return float(max(0.0, 1.0 - np.std(values) / mean))


def _seam_score(gray: np.ndarray, content: np.ndarray) -> float:
    """Fraction of content covered by long straight edges (seam/tear proxy)."""
    edges = cv2.Canny(gray, 60, 180)
    edges[~content] = 0
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120, minLineLength=max(gray.shape) // 6, maxLineGap=8)
    area = max(1, int(np.count_nonzero(content)))
    if lines is None:
        return 0.0
    length = 0.0
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = line
        length += float(np.hypot(x2 - x1, y2 - y1))
    return float(min(1.0, length / np.sqrt(area) / 50.0))


def assess_stitch_quality(
    image_bgr: np.ndarray,
    registration_rms: float | None = None,
    log: LogFn = _noop,
) -> QualityReport:
    height, width = image_bgr.shape[:2]
    report = QualityReport(width=width, height=height, registration_rms=registration_rms)

    small, scale = _analysis_image(image_bgr)
    sh, sw = small.shape[:2]
    total_px = sh * sw

    empty = _empty_mask(small)
    content = ~empty
    content_px = int(np.count_nonzero(content))
    report.content_fraction = content_px / max(1, total_px)

    if content_px < 0.02 * total_px:
        report.verdict = "broken"
        report.issues.append("near-empty result: stitching almost certainly failed")
        log("[quality] near-empty result")
        return report

    # Interior holes: empty components that do not touch the image border.
    empty_u8 = empty.astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(empty_u8, connectivity=8)
    border_labels = set(np.unique(labels[0, :])) | set(np.unique(labels[-1, :]))
    border_labels |= set(np.unique(labels[:, 0])) | set(np.unique(labels[:, -1]))

    interior_area = 0
    holes: list[HoleRegion] = []
    for label in range(1, num):
        if label in border_labels:
            continue
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 4:
            continue
        bx = stats[label, cv2.CC_STAT_LEFT]
        by = stats[label, cv2.CC_STAT_TOP]
        bw = stats[label, cv2.CC_STAT_WIDTH]
        bh = stats[label, cv2.CC_STAT_HEIGHT]
        interior_area += area
        holes.append(
            HoleRegion(
                x=bx / sw,
                y=by / sh,
                w=bw / sw,
                h=bh / sh,
                area_fraction=area / max(1, content_px),
            )
        )

    holes.sort(key=lambda h: h.area_fraction, reverse=True)
    report.holes = holes
    report.hole_count = len(holes)
    report.interior_hole_area_fraction = interior_area / max(1, content_px)
    # Coverage measures only interior gaps; legitimately empty corners of a
    # rotated/sheared mosaic (which touch the border) are excluded.
    report.coverage_ratio = content_px / max(1, content_px + interior_area)

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    report.sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    report.exposure_uniformity = _exposure_uniformity(gray, content)
    report.seam_score = _seam_score(gray, content)

    if bool(settings.stitch_quality_iqa):
        try:
            from .iqa import perceptual_quality

            score, backend = perceptual_quality(small, log)
            report.perceptual_quality = score
            report.perceptual_backend = backend
        except Exception as exc:  # pragma: no cover - optional dependency
            log(f"[quality] perceptual IQA skipped: {exc}")

    _decide_verdict(report)

    report.repairable = (
        report.hole_count > 0
        and 0.0 < report.interior_hole_area_fraction <= float(settings.stitch_repair_max_hole_fraction)
    )

    log(
        f"[quality] verdict={report.verdict} coverage={report.coverage_ratio:.4f} "
        f"holes={report.hole_count}({report.interior_hole_area_fraction:.5f}) "
        f"sharpness={report.sharpness:.2f} seam={report.seam_score:.3f}"
    )
    return report


def _decide_verdict(report: QualityReport) -> None:
    warn = float(settings.stitch_quality_hole_area_warn)
    fail = float(settings.stitch_quality_hole_area_fail)
    min_cov = float(settings.stitch_quality_min_coverage)
    min_sharp = float(settings.stitch_quality_min_sharpness)
    rms_warn = float(settings.stitch_quality_rms_warn)
    rms_fail = float(settings.stitch_quality_rms_fail)

    level = 0  # 0 ok, 1 warn, 2 broken

    if report.interior_hole_area_fraction >= fail:
        level = max(level, 2)
        report.issues.append(f"large interior holes ({report.interior_hole_area_fraction:.3%} of content)")
    elif report.interior_hole_area_fraction >= warn:
        level = max(level, 1)
        report.issues.append(f"interior holes detected ({report.hole_count} regions)")

    if report.coverage_ratio < min_cov:
        level = max(level, 1)
        report.issues.append(f"low coverage in content bounding box ({report.coverage_ratio:.3%})")

    if report.sharpness < min_sharp * 0.5:
        level = max(level, 2)
        report.issues.append(f"very low sharpness ({report.sharpness:.2f}); possible heavy ghosting/blur")
    elif report.sharpness < min_sharp:
        level = max(level, 1)
        report.issues.append(f"low sharpness ({report.sharpness:.2f})")

    if report.registration_rms is not None:
        if report.registration_rms >= rms_fail:
            level = max(level, 2)
            report.issues.append(f"high registration RMS ({report.registration_rms:.2f}px)")
        elif report.registration_rms >= rms_warn:
            level = max(level, 1)
            report.issues.append(f"elevated registration RMS ({report.registration_rms:.2f}px)")

    if report.seam_score > 0.6:
        level = max(level, 1)
        report.issues.append(f"prominent straight seams/tears (score {report.seam_score:.2f})")

    # Only the learned CLIP-IQA score is reliable enough to gate the verdict;
    # the classical heuristic is reported as an informational metric only.
    if (
        report.perceptual_quality is not None
        and report.perceptual_backend == "pyiqa"
        and report.perceptual_quality < float(settings.stitch_quality_iqa_warn)
    ):
        level = max(level, 1)
        report.issues.append(f"low perceptual quality ({report.perceptual_quality:.2f})")

    report.verdict = {0: "ok", 1: "warn", 2: "broken"}[level]

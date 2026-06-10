from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .blending import blend_full_resolution
from .feature_matching import build_feature_sets, disable_opencl, estimate_pair_matches, validate_image_set
from .global_alignment import align_global
from .warping import plan_canvas


@dataclass(slots=True)
class StitchPipelineResult:
    success: bool
    message: str
    image: object | None = None
    logs: list[str] = field(default_factory=list)


class StageLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, message: str) -> None:
        self.lines.append(message)


def run_scans_pipeline(image_paths: list[Path]) -> StitchPipelineResult:
    logger = StageLogger()
    try:
        disable_opencl()
        logger("[pipeline] OpenCL disabled")
        validate_image_set(image_paths, logger)

        features = build_feature_sets(image_paths, logger)
        weak = [feature.path.name for feature in features if feature.descriptors is None]
        if weak:
            raise RuntimeError(f"Not enough visual features in: {', '.join(weak[:5])}")

        pair_matches = estimate_pair_matches(features, logger, image_paths=image_paths)
        alignment = align_global(features, pair_matches, logger)
        canvas_plan = plan_canvas(features, alignment.transforms, logger)
        stitched = blend_full_resolution(image_paths, canvas_plan, logger)

        mode = "optimized" if alignment.optimized else "tree"
        message = (
            "Planar full-resolution mosaic completed. "
            f"root={alignment.root_index}, pairs={len(pair_matches)}, tree={len(alignment.tree_edges)}, "
            f"alignment={mode}"
        )
        if alignment.rms_error is not None:
            message += f", rms={alignment.rms_error:.3f}px"
        logger(f"[pipeline] {message}")
        return StitchPipelineResult(True, message, stitched, logger.lines)
    except Exception as exc:
        logger(f"[pipeline] failed: {exc}")
        return StitchPipelineResult(False, f"Planar pipeline failed: {exc}", None, logger.lines)

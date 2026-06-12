import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Session as SessionModel
from .deepzoom import generate_dzi
from .quality import assess_stitch_quality
from .repair import repair_stitch
from .stitching import save_stitched_variants, stitch_images
from .storage import dzi_dir, output_dir

logger = logging.getLogger(__name__)

_RMS_PATTERN = re.compile(r"rms=([0-9]+(?:\.[0-9]+)?)")


def _parse_registration_rms(message: str) -> float | None:
    match = _RMS_PATTERN.search(message or "")
    return float(match.group(1)) if match else None


def _run_quality_control(stitched, message: str, output_base: Path):
    """Assess the mosaic, optionally repair holes, and write a JSON sidecar."""
    if not bool(settings.stitch_quality_check):
        return stitched, None

    actions_log: list[str] = []
    report = assess_stitch_quality(
        stitched, registration_rms=_parse_registration_rms(message), log=actions_log.append
    )

    if bool(settings.stitch_auto_repair) and report.repairable:
        stitched, actions = repair_stitch(stitched, report, log=actions_log.append)
        if actions:
            # Re-assess so the saved report reflects the repaired image.
            repaired = assess_stitch_quality(
                stitched, registration_rms=report.registration_rms, log=actions_log.append
            )
            repaired.repaired = True
            repaired.repair_actions = actions
            report = repaired

    try:
        report_path = output_base / "quality_report.json"
        payload = report.to_dict()
        payload["log"] = actions_log
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - sidecar write is best-effort
        logger.warning("failed to write quality report", extra={"error": str(exc)})

    logger.info(
        "stitch quality assessed",
        extra={
            "verdict": report.verdict,
            "hole_count": report.hole_count,
            "coverage_ratio": round(report.coverage_ratio, 4),
            "repaired": report.repaired,
        },
    )
    return stitched, report


def _maybe_enhance(stitched, output_base: Path) -> None:
    """Write a non-archival AI-enhanced JPEG variant when enabled."""
    if not bool(settings.stitch_enhance):
        return
    try:
        import cv2

        from .enhance import enhance_image

        actions: list[str] = []
        result = enhance_image(stitched, log=actions.append)
        if result is None:
            return
        enhanced, backend = result
        ok, encoded = cv2.imencode(
            ".jpg", enhanced, [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, settings.optimized_jpeg_quality)))]
        )
        if ok:
            encoded.tofile(str(output_base / "stitched_enhanced.jpg"))
            logger.info("stitch enhanced variant written", extra={"backend": backend})
    except Exception as exc:  # pragma: no cover - optional/best-effort
        logger.warning("enhancement skipped", extra={"error": str(exc)})


def _set_session_status(db: Session, session: SessionModel, status: str, error_message: str | None = None) -> None:
    session.status = status
    session.error_message = error_message
    db.commit()
    db.refresh(session)


def run_pipeline(db: Session, session: SessionModel, mode: str = "scans") -> SessionModel:
    _set_session_status(db, session, "processing")

    image_paths = [Path(img.file_path) for img in sorted(session.images, key=lambda x: x.sort_order)]

    try:
        success, message, stitched = stitch_images(image_paths, mode=mode)
        if not success or stitched is None:
            _set_session_status(db, session, "failed", message)
            return session

        output_base = output_dir(session.id)

        # Inspect the mosaic for defects and repair enclosed holes before saving,
        # so the saved BigTIFF/JPEG/DZI reflect the corrected pixels.
        stitched, _quality_report = _run_quality_control(stitched, message, output_base)

        raw_stitched_path = output_base / "stitched_raw.tif"
        optimized_stitched_path = output_base / "stitched_optimized.jpg"
        width, height = save_stitched_variants(
            stitched,
            raw_output_path=raw_stitched_path,
            optimized_output_path=optimized_stitched_path,
            optimized_jpeg_quality=settings.optimized_jpeg_quality,
        )

        _maybe_enhance(stitched, output_base)

        descriptor_path, dzi_width, dzi_height = generate_dzi(
            raw_stitched_path,
            dzi_dir(session.id),
            tile_size=settings.tile_size,
            overlap=settings.tile_overlap,
            max_source_pixels=settings.max_source_pixels,
        )

        session.status = "ready"
        # Keep the raw path as canonical stitched output path.
        session.stitched_image_path = str(raw_stitched_path)
        session.dzi_descriptor_path = str(descriptor_path)
        session.width = dzi_width if dzi_width else width
        session.height = dzi_height if dzi_height else height
        session.error_message = None
        db.commit()
        db.refresh(session)
        return session

    except Exception as exc:  # pragma: no cover
        session.status = "failed"
        session.error_message = str(exc)
        db.commit()
        db.refresh(session)
        return session

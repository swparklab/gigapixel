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


def _calibrate_color(stitched, output_base: Path):
    """Colour-calibrate the mosaic and write a color_report.json sidecar."""
    if not bool(settings.color_management):
        return stitched, None
    try:
        from .color import calibrate

        log: list[str] = []
        calibrated, report = calibrate(stitched, log=log.append)
        payload = report.to_dict()
        payload["log"] = log
        (output_base / "color_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("colour calibrated", extra={"method": report.method, "calibrated": report.calibrated})
        return calibrated, report
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("colour calibration skipped", extra={"error": str(exc)})
        return stitched, None


def _run_quality_control(stitched, message: str, output_base: Path):
    """Assess the mosaic, optionally repair holes, write the QC sidecar.

    Returns ``(stitched, report, synthetic_mask)``.
    """
    if not bool(settings.stitch_quality_check):
        return stitched, None, None

    actions_log: list[str] = []
    report = assess_stitch_quality(
        stitched, registration_rms=_parse_registration_rms(message), log=actions_log.append
    )

    synthetic_mask = None
    if bool(settings.stitch_auto_repair) and report.repairable:
        stitched, actions, synthetic_mask = repair_stitch(stitched, report, log=actions_log.append)
        if actions:
            repaired = assess_stitch_quality(
                stitched, registration_rms=report.registration_rms, log=actions_log.append
            )
            repaired.repaired = True
            repaired.repair_actions = actions
            report = repaired

    try:
        payload = report.to_dict()
        payload["log"] = actions_log
        (output_base / "quality_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - sidecar write is best-effort
        logger.warning("failed to write quality report", extra={"error": str(exc)})

    logger.info(
        "stitch quality assessed",
        extra={"verdict": report.verdict, "hole_count": report.hole_count, "repaired": report.repaired},
    )
    return stitched, report, synthetic_mask


def _write_provenance(stitched, synthetic_mask, output_base: Path):
    """Write coverage/synthetic/uncertainty layers; return the summary dict."""
    if not bool(settings.provenance_maps):
        return None
    try:
        from .provenance import compute_provenance, save_provenance

        summary, maps = compute_provenance(stitched, synthetic_mask)
        save_provenance(maps, output_base)
        (output_base / "provenance.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("provenance maps skipped", extra={"error": str(exc)})
        return None


def _maybe_enhance(stitched, output_base: Path) -> None:
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


def _write_iiif(session_id: str, width: int, height: int, output_base: Path) -> None:
    if not bool(settings.iiif_enabled):
        return
    try:
        from .iiif import write_iiif

        write_iiif(session_id, width, height, output_base)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("IIIF generation skipped", extra={"error": str(exc)})


def _write_manifest(session_id: str, output_base: Path, mode: str, message: str, context: dict) -> None:
    if not bool(settings.processing_manifest):
        return
    try:
        from .manifest import write_manifest

        write_manifest(session_id, output_base, mode=mode, message=message, context=context)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("manifest generation skipped", extra={"error": str(exc)})


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

        # Colour calibration first so every saved variant is colour-managed.
        stitched, color_report = _calibrate_color(stitched, output_base)

        # Defect inspection + hole repair before saving outputs.
        stitched, quality_report, synthetic_mask = _run_quality_control(stitched, message, output_base)

        # Provenance/uncertainty layers separating measured vs reconstructed pixels.
        provenance_summary = _write_provenance(stitched, synthetic_mask, output_base)

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

        final_width = dzi_width if dzi_width else width
        final_height = dzi_height if dzi_height else height

        _write_iiif(session.id, final_width, final_height, output_base)
        _write_manifest(
            session.id,
            output_base,
            mode=mode,
            message=message,
            context={
                "width": final_width,
                "height": final_height,
                "source_image_count": len(image_paths),
                "quality": quality_report.to_dict() if quality_report else None,
                "color": color_report.to_dict() if color_report else None,
                "provenance": provenance_summary,
            },
        )

        session.status = "ready"
        session.stitched_image_path = str(raw_stitched_path)
        session.dzi_descriptor_path = str(descriptor_path)
        session.width = final_width
        session.height = final_height
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

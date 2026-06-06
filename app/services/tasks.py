from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Session as SessionModel
from .deepzoom import generate_dzi
from .stitching import save_stitched_variants, stitch_images
from .storage import dzi_dir, output_dir


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
        raw_stitched_path = output_base / "stitched_raw.tif"
        optimized_stitched_path = output_base / "stitched_optimized.jpg"
        width, height = save_stitched_variants(
            stitched,
            raw_output_path=raw_stitched_path,
            optimized_output_path=optimized_stitched_path,
            optimized_jpeg_quality=settings.optimized_jpeg_quality,
        )

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

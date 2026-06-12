"""Processing provenance manifest, fixity (SHA-256) and descriptive metadata.

Reproducibility and long-term preservation require a machine-readable record of
*what produced this output*: the algorithm parameters, library versions, the
input set, and cryptographic checksums of every artefact. This module writes:

* ``processing_manifest.json`` — params, versions, inputs, and SHA-256 fixity.
* ``dublin_core.json`` — minimal Dublin Core descriptive metadata.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from pathlib import Path

from ..config import settings

_RELEVANT_SETTINGS = (
    "stitch_matcher",
    "stitch_planar_transform_model",
    "stitch_planar_global_optimize",
    "stitch_planar_robust_refine",
    "stitch_pair_selection",
    "stitch_retrieval_model",
    "stitch_planar_tiled_multiband",
    "stitch_planar_multiband_bands",
    "color_management",
    "color_conformance_target",
    "stitch_quality_check",
    "stitch_auto_repair",
    "stitch_repair_backend",
    "raw_bigtiff_compression",
    "raw_bigtiff_tiled",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versions() -> dict:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("cv2", "numpy", "tifffile"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:
            versions[name] = "absent"
    return versions


def _fixity(output_base: Path) -> list[dict]:
    artefacts = [
        "stitched_raw.tif",
        "stitched_optimized.jpg",
        "stitched_enhanced.jpg",
        "dzi/image.dzi",
        "quality_report.json",
        "color_report.json",
        "provenance.json",
    ]
    records = []
    for rel in artefacts:
        path = output_base / rel
        if path.exists() and path.is_file():
            records.append(
                {"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)}
            )
    return records


def write_manifest(session_id: str, output_base: Path, mode: str, message: str, context: dict) -> Path:
    manifest = {
        "schema": "gigapixel-heritage/processing-manifest/1.0",
        "session_id": session_id,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(),
        "pipeline": {
            "mode": mode,
            "message": message,
            "parameters": {key: getattr(settings, key, None) for key in _RELEVANT_SETTINGS},
        },
        "software": {"name": settings.app_name, "versions": _versions()},
        "result": context,
        "fixity": _fixity(output_base),
    }
    path = output_base / "processing_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    if bool(settings.embed_metadata):
        dublin_core = {
            "dc:title": f"Gigapixel heritage mosaic {session_id}",
            "dc:type": "StillImage",
            "dc:format": "image/tiff",
            "dc:identifier": session_id,
            "dc:date": manifest["created_utc"],
            "dc:source": f"{context.get('source_image_count', 0)} source captures",
            "dc:description": message,
        }
        (output_base / "dublin_core.json").write_text(json.dumps(dublin_core, indent=2), encoding="utf-8")
    return path

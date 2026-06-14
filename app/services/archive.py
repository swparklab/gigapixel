"""BagIt archival packaging of a session's outputs.

Produces a Library-of-Congress **BagIt 1.0** package (zipped) containing the
mosaic, optimised/derivative variants, DZI, IIIF descriptors, quality / colour /
provenance / manifest sidecars and descriptive metadata, with SHA-256 payload
checksums — the form national archives and repositories ingest for long-term
preservation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile
from pathlib import Path

# Output files included in the bag payload, when present.
_PAYLOAD = [
    "stitched_raw.tif",
    "stitched_optimized.jpg",
    "stitched_enhanced.jpg",
    "stitched_upscaled.jpg",
    "stitched_outpainted.jpg",
    "quality_report.json",
    "color_report.json",
    "condition_report.json",
    "provenance.json",
    "processing_manifest.json",
    "dublin_core.json",
    "metadata.json",
    "dzi/image.dzi",
    "iiif/info.json",
    "iiif/manifest.json",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_bagit(session_id: str, session_name: str, output_base: Path) -> bytes:
    """Return the bytes of a zipped BagIt package for the session outputs."""
    files: list[tuple[str, bytes]] = []
    for rel in _PAYLOAD:
        path = output_base / rel
        if path.exists() and path.is_file():
            files.append((f"data/{rel}", path.read_bytes()))

    manifest_lines = []
    total_bytes = 0
    for rel, data in files:
        manifest_lines.append(f"{_sha256_bytes(data)}  {rel}")
        total_bytes += len(data)

    created = dt.datetime.now(dt.UTC).isoformat()
    bagit_txt = "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
    bag_info = (
        f"Source-Organization: Hyper Gigapixel Agent\n"
        f"Bagging-Date: {created[:10]}\n"
        f"External-Identifier: {session_id}\n"
        f"External-Description: {session_name}\n"
        f"Payload-Oxum: {total_bytes}.{len(files)}\n"
        f"Bag-Software-Agent: Hyper Gigapixel Agent\n"
    )
    manifest_txt = "\n".join(manifest_lines) + ("\n" if manifest_lines else "")

    tagmanifest = []
    for name, text in (("bagit.txt", bagit_txt), ("bag-info.txt", bag_info), ("manifest-sha256.txt", manifest_txt)):
        tagmanifest.append(f"{_sha256_bytes(text.encode())}  {name}")
    tagmanifest_txt = "\n".join(tagmanifest) + "\n"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bagit.txt", bagit_txt)
        zf.writestr("bag-info.txt", bag_info)
        zf.writestr("manifest-sha256.txt", manifest_txt)
        zf.writestr("tagmanifest-sha256.txt", tagmanifest_txt)
        for rel, data in files:
            zf.writestr(rel, data)
    return buffer.getvalue()

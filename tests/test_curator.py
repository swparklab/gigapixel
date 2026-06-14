"""Tests for curator/scholar features: metadata, scale, region annotations,
condition report, sessions dashboard, BagIt archive."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path


def test_report_html_contains_sections():
    from app.services.reporting import render_report

    html = render_report({
        "session": {"id": "abc", "name": "백자 달항아리", "status": "ready", "width": 4000, "height": 3000,
                    "image_count": 12, "pixels_per_mm": 10.0},
        "metadata": {"title": "Moon Jar", "repository": "NMK", "material": "white porcelain"},
        "quality": {"verdict": "warn", "issues": ["interior holes"], "metrics": {"coverage_ratio": 0.99, "sharpness": 300}},
        "color": {"calibrated": True, "delta_e_mean": 2.1, "conformance_target": "fadgi", "conformance_pass": True},
        "condition": {"cracks": [{}, {}], "discolouration": [{}]},
        "provenance": {"synthetic_fraction": 0.001},
        "manifest": {"fixity": [{}, {}, {}], "created_utc": "2026-06-14T00:00:00+00:00"},
        "annotations": [{"id": 1, "shape": "rect", "text": "crack", "tags": "loss", "w": 50, "h": 30}],
    })
    assert "Moon Jar" in html and "NMK" in html
    assert "Image Quality" in html and "Colour Accuracy" in html and "Condition" in html
    assert "WARN" in html  # verdict badge
    assert "5.0 × 3.0 mm" in html  # rect extent at 10 px/mm


def test_bagit_archive_is_valid():
    from app.services.archive import build_bagit

    tmp = Path(tempfile.mkdtemp())
    (tmp / "stitched_optimized.jpg").write_bytes(b"\xff\xd8jpegdata")
    (tmp / "quality_report.json").write_text('{"verdict":"ok"}', encoding="utf-8")
    (tmp / "iiif").mkdir()
    (tmp / "iiif" / "manifest.json").write_text("{}", encoding="utf-8")

    data = build_bagit("sid-1", "Test Object", tmp)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert "bagit.txt" in names and "manifest-sha256.txt" in names and "tagmanifest-sha256.txt" in names
    assert any(n.startswith("data/") for n in names)
    # BagIt declaration + payload checksums present
    assert "BagIt-Version: 1.0" in z.read("bagit.txt").decode()
    manifest = z.read("manifest-sha256.txt").decode()
    assert "data/stitched_optimized.jpg" in manifest and len(manifest.split()[0]) == 64


def test_metadata_scale_and_region_annotation_api():
    from fastapi.testclient import TestClient

    import app.main as m

    c = TestClient(m.app)
    sid = c.post("/api/sessions", json={"name": "catalogue"}).json()["id"]

    meta = c.put(f"/api/sessions/{sid}/metadata", json={"title": "Object A", "repository": "Museum"}).json()
    assert meta["title"] == "Object A"
    assert c.get(f"/api/sessions/{sid}/metadata").json()["repository"] == "Museum"

    assert c.post(f"/api/sessions/{sid}/scale-set", json={"pixels_per_mm": 8.0}).json()["pixels_per_mm"] == 8.0
    assert c.get(f"/api/sessions/{sid}").json()["pixels_per_mm"] == 8.0

    a = c.post(f"/api/sessions/{sid}/annotations",
               json={"x": 10, "y": 20, "text": "loss", "shape": "rect", "w": 40, "h": 25, "tags": "loss,crack"}).json()
    assert a["shape"] == "rect" and a["w"] == 40 and a["tags"] == "loss,crack"

    iiif = c.get(f"/api/sessions/{sid}/iiif/annotations").json()
    assert iiif["type"] == "AnnotationPage" and len(iiif["items"]) == 1
    assert "xywh=10,20,40,25" in iiif["items"][0]["target"]

    listing = c.get("/api/sessions", params={"q": "catalogue"}).json()
    assert any(s["id"] == sid for s in listing)

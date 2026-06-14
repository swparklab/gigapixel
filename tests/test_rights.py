"""Tests for the rights-protection pillar: watermarking, tamper auth,
encrypted packaging, persistent identifiers, LIDO/DC XML, material maps."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def _scene(h=480, w=480, seed=0):
    return cv2.GaussianBlur(np.random.default_rng(seed).integers(40, 220, (h, w, 3), dtype=np.uint8), (0, 0), 2)


def test_watermark_embed_extract_survives_jpeg_and_is_invisible():
    from app.services.watermark import embed_watermark, verify_payload

    img = _scene()
    payload = "ark:/99999/obj7|recipient=curator-A"
    wm = embed_watermark(img, payload)
    assert cv2.PSNR(img, wm) > 38.0  # imperceptible

    ok, buf = cv2.imencode(".jpg", wm, [cv2.IMWRITE_JPEG_QUALITY, 90])
    reloaded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    assert verify_payload(reloaded, payload)["watermark_present"] is True
    assert verify_payload(reloaded, "different-recipient")["watermark_present"] is False


def test_perceptual_hash_detects_tamper():
    from app.services.watermark import hamming_distance, perceptual_hash

    img = _scene()
    tampered = img.copy()
    cv2.rectangle(tampered, (60, 60), (300, 300), (0, 0, 0), -1)
    assert hamming_distance(perceptual_hash(img), perceptual_hash(img.copy())) == 0
    assert hamming_distance(perceptual_hash(img), perceptual_hash(tampered)) > 8


def test_encrypted_package_roundtrip():
    crypto = pytest.importorskip("cryptography")  # noqa: F841
    from app.services.archive import decrypt_package, encrypt_package

    data = b"BagIt payload bytes " * 50
    blob = encrypt_package(data, "s3cret")
    assert blob.startswith(b"HGAENC1")
    assert decrypt_package(blob, "s3cret") == data
    with pytest.raises(Exception):
        decrypt_package(blob, "wrong-pass")


def test_material_maps_from_image():
    from app.services.splat import build_3d

    tmp = Path(tempfile.mkdtemp())
    result = build_3d(_scene(240, 320), "material", tmp)
    assert "roughness" in result["artifacts"] and "gloss" in result["artifacts"]
    assert Path(result["artifacts"]["roughness"]).exists()


def test_pid_and_metadata_xml_api():
    from fastapi.testclient import TestClient

    import app.main as m

    c = TestClient(m.app)
    sid = c.post("/api/sessions", json={"name": "rights"}).json()["id"]
    pid = c.get(f"/api/sessions/{sid}/pid").json()["pid"]
    assert pid.startswith("ark:/")
    assert c.get(f"/api/sessions/{sid}").json()["pid"] == pid

    c.put(f"/api/sessions/{sid}/metadata", json={"title": "Object Z", "repository": "Museum"})
    lido = c.get(f"/api/sessions/{sid}/metadata.xml", params={"format": "lido"})
    assert lido.status_code == 200 and "lido:lido" in lido.text and "Object Z" in lido.text
    dc = c.get(f"/api/sessions/{sid}/metadata.xml", params={"format": "dc"})
    assert dc.status_code == 200 and "oai_dc:dc" in dc.text and "ark:/" in dc.text

"""Tests for platform-ops features: queue robustness, coverage QA, multi-view
3D, semantic tagging/search, streaming compositor, and optional API auth."""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.config import settings


def _scene(h=600, w=1400, seed=0):
    img = np.full((h, w, 3), 60, np.uint8)
    rng = np.random.default_rng(seed)
    for x, y, c in [(120, 120, (200, 120, 60)), (500, 200, (60, 200, 120)), (900, 400, (120, 60, 200))]:
        cv2.circle(img, (x % w, y % h), 40, c, -1)
    cv2.putText(img, "HERITAGE MUSEUM", (40, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 3)
    return cv2.add(img, rng.integers(0, 14, (h, w, 3), dtype=np.uint8).astype(np.uint8))


def _overlapping_set(tmp: Path):
    scene = _scene()
    paths, transforms = [], []
    for k, (x0, x1) in enumerate([(0, 800), (600, 1400)]):
        p = tmp / f"v{k}.png"
        cv2.imwrite(str(p), scene[:, x0:x1].copy())
        paths.append(p)
        transforms.append(np.array([[1.0, 0, x0], [0, 1.0, 0], [0, 0, 1.0]]))
    return scene, paths, transforms


# --- queue robustness -------------------------------------------------------
def test_stale_job_recovery_requeue_and_fail():
    from app.database import SessionLocal, ensure_schema
    from app.models import ProcessingJob as J, Session as S
    from app.services.jobs import JobService, utc_now

    ensure_schema()
    db = SessionLocal()
    try:
        sess = S(name="q")
        db.add(sess)
        db.commit()
        db.refresh(sess)
        past = utc_now() - dt.timedelta(seconds=30)
        retry = J(session_id=sess.id, mode="scans", status="processing", attempts=1, max_attempts=3, lease_expires_at=past)
        dead = J(session_id=sess.id, mode="scans", status="processing", attempts=3, max_attempts=3, lease_expires_at=past)
        db.add_all([retry, dead])
        db.commit()
        JobService(db).recover_stale_jobs()
        db.refresh(retry)
        db.refresh(dead)
        assert retry.status == "queued" and retry.worker_id is None
        assert dead.status == "failed"
    finally:
        db.close()


# --- coverage QA ------------------------------------------------------------
def test_coverage_connected_for_overlapping_pair():
    tmp = Path(tempfile.mkdtemp())
    _scene_, paths, _ = _overlapping_set(tmp)
    from app.services.coverage import analyze_coverage

    report = analyze_coverage(paths)
    assert report.connected
    assert report.pair_count >= 1
    assert report.verdict in ("ok", "warn")


# --- multi-view 3D ----------------------------------------------------------
def test_multiview_reconstruction_fuses_views():
    tmp = Path(tempfile.mkdtemp())
    _scene_, paths, _ = _overlapping_set(tmp)
    from app.services.recon3d import reconstruct

    result = reconstruct(paths, tmp)
    assert result.backend in ("multiview_depth", "colmap_gsplat")
    assert result.num_points > 0
    assert result.pointcloud_path.exists()
    assert result.pointcloud_path.read_bytes()[:3] == b"ply"


# --- semantic tagging + search ---------------------------------------------
def test_semantic_tags_and_keyword_search():
    from app.services.semantic import auto_tags, backend, rank_sessions

    img = _scene()
    tags = auto_tags(img)
    assert tags and all("tag" in t for t in tags)
    # classical keyword search ranks the matching tags higher
    if backend() == "classical":
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "img.png"
        cv2.imwrite(str(p), img)
        items = [("a", p, "monochrome,detailed"), ("b", p, "vivid")]
        ranked = rank_sessions("monochrome", items)
        assert ranked[0]["session_id"] == "a"


# --- streaming compositor ---------------------------------------------------
def test_streaming_compositor_matches_in_memory():
    import app.services.blending as bl
    from app.services.warping import CanvasPlan

    tmp = Path(tempfile.mkdtemp())
    scene, paths, transforms = _overlapping_set(tmp)
    plan = CanvasPlan(transforms=transforms, width=1400, height=600)

    orig_stream = settings.streaming_compositor
    orig_thresh = settings.streaming_threshold_pixels
    orig_tile = settings.stitch_planar_tile_pixels
    try:
        settings.stitch_planar_tile_pixels = 4_000_000
        settings.streaming_compositor = False
        in_mem = bl.tiled_multiband_blend(paths, plan, lambda m: None)
        settings.streaming_compositor = True
        settings.streaming_threshold_pixels = 1
        streamed = bl.tiled_multiband_blend(paths, plan, lambda m: None)
        assert isinstance(streamed, np.ndarray) and not isinstance(streamed, np.memmap)
        assert streamed.shape == in_mem.shape
        assert float(np.abs(streamed.astype(int) - in_mem.astype(int)).mean()) < 0.5
    finally:
        settings.streaming_compositor = orig_stream
        settings.streaming_threshold_pixels = orig_thresh
        settings.stitch_planar_tile_pixels = orig_tile


# --- optional API auth ------------------------------------------------------
def test_api_key_auth_is_enforced_only_when_set():
    from fastapi.testclient import TestClient

    import app.main as m

    client = TestClient(m.app)
    orig = settings.api_key
    try:
        settings.api_key = "secret123"
        assert client.get("/api/sessions/none").status_code == 401
        assert client.get("/api/sessions/none", headers={"X-API-Key": "secret123"}).status_code == 404
        assert client.get("/").status_code == 200  # non-api routes are open
        settings.api_key = ""
        assert client.get("/api/sessions/none").status_code == 404
    finally:
        settings.api_key = orig

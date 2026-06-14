from contextlib import asynccontextmanager
from pathlib import Path
import logging
import shutil
import threading
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .logging_config import configure_logging
from .models import Annotation, Session as SessionModel, SourceImage
from .schemas import (
    AnnotationCreate,
    AnnotationRead,
    AcquisitionPlanRead,
    AcquisitionPlanRequest,
    ChangeDetectRequest,
    ChangeDetectResponse,
    ConditionResponse,
    CoverageResponse,
    DamageResponse,
    ExportPresetRequest,
    FocusStackResponse,
    LicenseRequest,
    LicenseResponse,
    MetadataUpdate,
    TimelineRequest,
    OutpaintRequest,
    OutpaintResponse,
    ScaleSetRequest,
    SessionSummary,
    ReconResponse,
    SearchResponse,
    TagsResponse,
    PhotometricRequest,
    PhotometricResponse,
    ProcessRequest,
    ProcessResponse,
    RestoreResponse,
    ScaleRequest,
    ScaleResponse,
    SegmentRequest,
    SegmentResponse,
    SessionCreate,
    SessionRead,
    SplatResponse,
    To3DRequest,
    To3DResponse,
    UpscaleRequest,
    UpscaleResponse,
    VerifyResponse,
    WatermarkRequest,
    WatermarkResponse,
)
from .services.exporter import (
    build_download_filename,
    media_type_for_image,
    resolve_enhanced_image_path,
    resolve_optimized_image_path,
    resolve_raw_image_path,
)
from .services.acquisition import build_acquisition_plan
from .services.node_runner import WorkflowExecutionError, execute_graph
from .services.jobs import JobService
from .services.storage import node_upload_dir, node_upload_path, output_dir, upload_dir

configure_logging(settings.log_level, settings.log_format)
logger = logging.getLogger(__name__)

# --- Embedded processing agent -------------------------------------------------
# Run the queue worker inside the API process so one launch starts everything.
_agent_stop = threading.Event()
_agent_thread: threading.Thread | None = None


def _embedded_agent_loop() -> None:
    from .agent import run_once

    poll = max(0.2, float(settings.agent_poll_interval_seconds))
    logger.info("embedded agent worker started", extra={"poll_interval_seconds": poll})
    while not _agent_stop.is_set():
        try:
            processed = run_once()
        except Exception:
            logger.exception("embedded agent iteration failed")
            processed = False
        if not processed:
            _agent_stop.wait(poll)
    logger.info("embedded agent worker stopped")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _agent_thread
    if settings.embedded_agent:
        _agent_stop.clear()
        _agent_thread = threading.Thread(
            target=_embedded_agent_loop, name="embedded-agent", daemon=True
        )
        _agent_thread.start()
    else:
        logger.info("embedded agent disabled; run `python -m app.agent` separately")
    try:
        yield
    finally:
        _agent_stop.set()
        if _agent_thread is not None:
            _agent_thread.join(timeout=5)
            _agent_thread = None


app = FastAPI(title=settings.app_name, lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_schema()


@app.middleware("http")
async def _api_key_guard(request: Request, call_next):
    """Optional API-key auth: enforced only when settings.api_key is set."""
    key = str(settings.api_key or "")
    health_path = f"{settings.api_prefix}/health"
    if key and request.url.path.startswith(settings.api_prefix) and request.url.path != health_path:
        if request.headers.get("X-API-Key") != key:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"detail": "Invalid or missing X-API-Key"})
    return await call_next(request)


@app.get(f"{settings.api_prefix}/health")
def health():
    """Liveness probe: confirms the API is up and whether the embedded worker runs."""
    worker_alive = bool(_agent_thread is not None and _agent_thread.is_alive())
    return {
        "status": "ok",
        "embedded_agent": settings.embedded_agent,
        "worker_alive": worker_alive,
    }


static_dir = Path(__file__).resolve().parent / "static"
templates_dir = Path(__file__).resolve().parent / "templates"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

TYPE_COLORS = {
    "flow": "#ffd166",
    "session": "#4cc9f0",
    "upload_ref": "#f72585",
    "string": "#90be6d",
    "int": "#ff9f1c",
    "float": "#9b5de5",
    "url": "#06d6a0",
}

NODE_LIBRARY = [
    {"type": "workflow/start", "title": "Start", "category": "workflow"},
    {"type": "data/upload_ref", "title": "UploadRef", "category": "data"},
    {"type": "data/string", "title": "String", "category": "data"},
    {"type": "data/int", "title": "Int", "category": "data"},
    {"type": "data/float", "title": "Float", "category": "data"},
    {"type": "math/add_int", "title": "AddInt", "category": "math"},
    {"type": "math/add_float", "title": "AddFloat", "category": "math"},
    {"type": "workflow/run_pipeline", "title": "RunPipeline", "category": "workflow"},
    {"type": "workflow/download", "title": "Download", "category": "workflow"},
]


def _load_region(raw_path: Path, payload: SegmentRequest) -> tuple["object", tuple[int, int]]:
    """Crop a bounded region of the (gigapixel) raw mosaic for segmentation.

    Returns (BGR ndarray, (origin_x, origin_y)). Cropping is lazy so the full
    gigapixel image is never decoded into memory.
    """
    import numpy as np
    import cv2
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    max_region = max(256, int(settings.sam_max_region))
    with Image.open(raw_path) as source:
        width, height = source.size
        if None not in (payload.box_x, payload.box_y, payload.box_w, payload.box_h):
            margin = 32
            x0 = int(payload.box_x) - margin
            y0 = int(payload.box_y) - margin
            x1 = int(payload.box_x + payload.box_w) + margin
            y1 = int(payload.box_y + payload.box_h) + margin
        else:
            cx = int(payload.point_x if payload.point_x is not None else width / 2)
            cy = int(payload.point_y if payload.point_y is not None else height / 2)
            half = max_region // 2
            x0, y0, x1, y1 = cx - half, cy - half, cx + half, cy + half
        x0 = max(0, min(x0, width - 1))
        y0 = max(0, min(y0, height - 1))
        x1 = max(x0 + 1, min(x1, width))
        y1 = max(y0 + 1, min(y1, height))
        # Cap the crop so segmentation stays bounded.
        x1 = min(x1, x0 + max_region)
        y1 = min(y1, y0 + max_region)
        region = source.crop((x0, y0, x1, y1)).convert("RGB")
    bgr = cv2.cvtColor(np.asarray(region), cv2.COLOR_RGB2BGR)
    return bgr, (x0, y0)


def _serialize_session(session: SessionModel, request: Request, db: Session) -> SessionRead:
    image_count = db.query(func.count(SourceImage.id)).filter(SourceImage.session_id == session.id).scalar() or 0
    share_url = str(request.base_url).rstrip("/") + f"/viewer/{session.id}"
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        image_count=image_count,
        width=session.width,
        height=session.height,
        created_at=session.created_at,
        updated_at=session.updated_at,
        error_message=session.error_message,
        share_url=share_url,
        tags=session.tags,
        pixels_per_mm=session.pixels_per_mm,
        pid=session.pid,
    )


def _serialize_annotation(row) -> "AnnotationRead":
    import json as _json

    points = None
    if getattr(row, "points_json", None):
        try:
            points = _json.loads(row.points_json)
        except Exception:
            points = None
    return AnnotationRead(
        id=row.id,
        session_id=row.session_id,
        x=row.x,
        y=row.y,
        text=row.text,
        shape=getattr(row, "shape", None) or "point",
        w=getattr(row, "w", None),
        h=getattr(row, "h", None),
        points=points,
        tags=getattr(row, "tags", None),
        created_at=row.created_at,
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Default landing mode is classic UI.
    return templates.TemplateResponse(request, "index.html")


@app.get("/classic", response_class=HTMLResponse)
def classic(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/viewer/{session_id}", response_class=HTMLResponse)
def viewer(request: Request, session_id: str):
    return templates.TemplateResponse(request, "viewer.html", {"session_id": session_id})


@app.get("/gallery", response_class=HTMLResponse)
def gallery_page(request: Request):
    return templates.TemplateResponse("gallery.html", {"request": request})


@app.get("/workflow", response_class=HTMLResponse)
def workflow_page(request: Request):
    return templates.TemplateResponse(request, "workflow.html")


@app.post(f"{settings.api_prefix}/acquisition/plan", response_model=AcquisitionPlanRead)
def plan_acquisition(payload: AcquisitionPlanRequest):
    return build_acquisition_plan(**payload.model_dump())


@app.post(f"{settings.api_prefix}/sessions", response_model=SessionRead)
def create_session(payload: SessionCreate, request: Request, db: Session = Depends(get_db)):
    session = SessionModel(name=payload.name)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session, request, db)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}", response_model=SessionRead)
def get_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize_session(session, request, db)


def _read_sidecar(session_id: str, rel: str):
    import json as _json

    path = output_dir(session_id) / rel
    if path.exists():
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


@app.get(f"{settings.api_prefix}/sessions", response_model=list[SessionSummary])
def list_sessions(q: str | None = None, status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    """Dashboard: recent sessions with status, tags and QC verdict."""
    query = db.query(SessionModel)
    if status:
        query = query.filter(SessionModel.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter((SessionModel.name.ilike(like)) | (SessionModel.tags.ilike(like)))
    rows = query.order_by(SessionModel.created_at.desc()).limit(max(1, min(500, limit))).all()
    out = []
    for s in rows:
        verdict = (_read_sidecar(s.id, "quality_report.json") or {}).get("verdict")
        thumb = f"{settings.api_prefix}/sessions/{s.id}/download/optimized" if s.status == "ready" else None
        out.append(
            SessionSummary(
                id=s.id, name=s.name, status=s.status, width=s.width, height=s.height,
                tags=s.tags, quality_verdict=verdict, created_at=s.created_at, thumbnail_url=thumb,
            )
        )
    return out


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/metadata")
def get_metadata(session_id: str, db: Session = Depends(get_db)):
    import json as _json

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return _json.loads(session.metadata_json) if session.metadata_json else {}
    except Exception:
        return {}


@app.put(f"{settings.api_prefix}/sessions/{{session_id}}/metadata")
def set_metadata(session_id: str, payload: MetadataUpdate, db: Session = Depends(get_db)):
    import json as _json

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    meta = {k: v for k, v in payload.model_dump().items() if v not in (None, "")}
    session.metadata_json = _json.dumps(meta, ensure_ascii=False)
    db.commit()
    # Persist a metadata sidecar for archival packaging.
    try:
        (output_dir(session_id) / "metadata.json").write_text(
            _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return meta


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/scale-set")
def set_scale(session_id: str, payload: ScaleSetRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.pixels_per_mm = float(payload.pixels_per_mm)
    db.commit()
    return {"pixels_per_mm": session.pixels_per_mm, "dpi": round(session.pixels_per_mm * 25.4, 2)}


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/iiif/annotations")
def get_iiif_annotations(session_id: str, db: Session = Depends(get_db)):
    """Export region annotations as a IIIF Presentation 3.0 AnnotationPage."""
    import json as _json

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    base = f"{settings.api_prefix}/sessions/{session_id}/iiif"
    canvas = f"{base}/canvas/1"
    items = []
    for a in db.query(Annotation).filter(Annotation.session_id == session_id).order_by(Annotation.id.asc()).all():
        if a.shape == "rect" and a.w and a.h:
            target = f"{canvas}#xywh={int(a.x)},{int(a.y)},{int(a.w)},{int(a.h)}"
        else:
            target = f"{canvas}#xywh={int(a.x) - 8},{int(a.y) - 8},16,16"
        body = [{"type": "TextualBody", "value": a.text, "format": "text/plain"}]
        if a.tags:
            for tag in str(a.tags).split(","):
                if tag.strip():
                    body.append({"type": "TextualBody", "value": tag.strip(), "purpose": "tagging"})
        items.append(
            {"id": f"{base}/annotation/{a.id}", "type": "Annotation", "motivation": "commenting",
             "body": body, "target": target}
        )
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{base}/annotations", "type": "AnnotationPage", "items": items,
    }


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/archive")
def download_archive(session_id: str, encrypt: bool = False, passphrase: str = "", db: Session = Depends(get_db)):
    from fastapi import Response

    from .services.archive import build_bagit, encrypt_package

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")
    data = build_bagit(session_id, session.name, output_dir(session_id))
    if encrypt:
        if not passphrase:
            raise HTTPException(status_code=400, detail="passphrase is required for an encrypted package")
        try:
            data = encrypt_package(data, passphrase)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        name = build_download_filename(session, variant="bagit", file_path=Path("x.zip")) + ".enc"
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    name = build_download_filename(session, variant="bagit", file_path=Path("x.zip"))
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/report/{session_id}", response_class=HTMLResponse)
def report_page(session_id: str, request: Request, db: Session = Depends(get_db)):
    import json as _json

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from .services.reporting import render_report

    image_count = db.query(func.count(SourceImage.id)).filter(SourceImage.session_id == session_id).scalar() or 0
    annotations = [_serialize_annotation(a).model_dump() for a in
                   db.query(Annotation).filter(Annotation.session_id == session_id).order_by(Annotation.id.asc()).all()]
    metadata = {}
    try:
        metadata = _json.loads(session.metadata_json) if session.metadata_json else {}
    except Exception:
        metadata = {}
    context = {
        "session": {
            "id": session.id, "name": session.name, "status": session.status,
            "width": session.width, "height": session.height, "image_count": image_count,
            "tags": session.tags, "pixels_per_mm": session.pixels_per_mm,
        },
        "metadata": metadata,
        "quality": _read_sidecar(session_id, "quality_report.json"),
        "color": _read_sidecar(session_id, "color_report.json"),
        "condition": _read_sidecar(session_id, "condition_report.json"),
        "provenance": _read_sidecar(session_id, "provenance.json"),
        "manifest": _read_sidecar(session_id, "processing_manifest.json"),
        "annotations": annotations,
    }
    return HTMLResponse(render_report(context))


@app.get("/relief/{session_id}", response_class=HTMLResponse)
def relief_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "relief.html", {"session_id": session_id})


@app.get("/sync", response_class=HTMLResponse)
def sync_compare_page(request: Request, a: str = "", b: str = ""):
    return templates.TemplateResponse(request, "sync.html", {"a": a, "b": b})


def _ensure_pid(session: SessionModel, db: Session) -> str:
    """Assign a stable ARK persistent identifier if the session lacks one."""
    if not session.pid:
        session.pid = f"ark:/{settings.pid_naan}/g{session.id.replace('-', '')[:14]}"
        db.commit()
    return session.pid


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/pid")
def get_pid(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pid": _ensure_pid(session, db)}


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/metadata.xml")
def get_metadata_xml(session_id: str, format: str = "lido", db: Session = Depends(get_db)):
    import json as _json
    from fastapi import Response
    from xml.sax.saxutils import escape

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        meta = _json.loads(session.metadata_json) if session.metadata_json else {}
    except Exception:
        meta = {}
    pid = _ensure_pid(session, db)

    def e(v):
        return escape("" if v is None else str(v))

    if format.lower() == "dc":
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f"  <dc:identifier>{e(pid)}</dc:identifier>\n"
            f"  <dc:title>{e(meta.get('title') or session.name)}</dc:title>\n"
            f"  <dc:creator>{e(meta.get('creator'))}</dc:creator>\n"
            f"  <dc:date>{e(meta.get('date'))}</dc:date>\n"
            f"  <dc:format>{e(meta.get('material'))}</dc:format>\n"
            f"  <dc:description>{e(meta.get('description'))}</dc:description>\n"
            f"  <dc:source>{e(meta.get('repository'))}</dc:source>\n"
            f"  <dc:rights>{e(meta.get('rights'))}</dc:rights>\n"
            f"  <dc:subject>{e(meta.get('subject'))}</dc:subject>\n"
            "</oai_dc:dc>\n"
        )
    else:  # LIDO 1.0 (minimal)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<lido:lido xmlns:lido="http://www.lido-schema.org">\n'
            f"  <lido:lidoRecID lido:type=\"local\">{e(pid)}</lido:lidoRecID>\n"
            "  <lido:descriptiveMetadata xml:lang=\"en\">\n"
            "    <lido:objectClassificationWrap><lido:objectWorkTypeWrap><lido:objectWorkType>"
            f"<lido:term>{e(meta.get('material'))}</lido:term>"
            "</lido:objectWorkType></lido:objectWorkTypeWrap></lido:objectClassificationWrap>\n"
            "    <lido:objectIdentificationWrap><lido:titleWrap><lido:titleSet><lido:appellationValue>"
            f"{e(meta.get('title') or session.name)}"
            "</lido:appellationValue></lido:titleSet></lido:titleWrap>\n"
            "      <lido:repositoryWrap><lido:repositorySet><lido:repositoryName><lido:legalBodyName>"
            f"<lido:appellationValue>{e(meta.get('repository'))}</lido:appellationValue>"
            "</lido:legalBodyName></lido:repositoryName>"
            f"<lido:workID>{e(meta.get('accession_number'))}</lido:workID>"
            "</lido:repositorySet></lido:repositoryWrap></lido:objectIdentificationWrap>\n"
            "  </lido:descriptiveMetadata>\n"
            "</lido:lido>\n"
        )
    return Response(content=xml, media_type="application/xml")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/watermark", response_model=WatermarkResponse)
def watermark_endpoint(session_id: str, payload: WatermarkRequest, db: Session = Depends(get_db)):
    import datetime as _dt
    import hashlib
    import json as _json

    import cv2

    from .services.watermark import block_hashes, embed_robust, perceptual_hash

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    pid = _ensure_pid(session, db)
    bgr = _read_raw_bgr(session, max_dim=4096)
    wm_payload = f"{pid}|{payload.recipient}|{payload.identifier or ''}"
    watermarked, backend = embed_robust(bgr, wm_payload)
    base = output_dir(session_id)
    out = base / "stitched_watermarked.jpg"
    cv2.imencode(".jpg", watermarked, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(out))

    phash = perceptual_hash(watermarked)
    token = hashlib.sha256(wm_payload.encode()).hexdigest()[:12]
    rights_path = base / "rights.json"
    try:
        registry = _json.loads(rights_path.read_text(encoding="utf-8")) if rights_path.exists() else []
    except Exception:
        registry = []
    registry.append({
        "payload": wm_payload, "recipient": payload.recipient, "identifier": payload.identifier,
        "token": token, "phash": phash, "backend": backend,
        "block_hashes": block_hashes(watermarked),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "issued_utc": _dt.datetime.now(_dt.UTC).isoformat(),
    })
    rights_path.write_text(_json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    return WatermarkResponse(
        ok=True, payload=wm_payload, token=token, phash=phash,
        download_url=f"{settings.api_prefix}/sessions/{session_id}/download/watermarked",
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/watermarked")
def download_watermarked(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "stitched_watermarked.jpg", "image/jpeg")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/verify-watermark", response_model=VerifyResponse)
async def verify_watermark(session_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Trace a (possibly leaked / modified) image back to its watermark + detect tampering."""
    import json as _json

    import cv2
    import numpy as np

    from .services.watermark import hamming_distance, localize_tamper, perceptual_hash, verify_payload

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    raw = np.frombuffer(await file.read(), np.uint8)
    bgr = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(status_code=400, detail="Could not decode the uploaded image")

    rights_path = output_dir(session_id) / "rights.json"
    registry = []
    if rights_path.exists():
        try:
            registry = _json.loads(rights_path.read_text(encoding="utf-8"))
        except Exception:
            registry = []

    best = {"match_fraction": 0.0, "recipient": None, "payload": None, "phash": None,
            "block_hashes": None, "backend": None}
    for rec in registry:
        res = verify_payload(bgr, rec["payload"])
        if res["match_fraction"] > best["match_fraction"]:
            best = {"match_fraction": res["match_fraction"], "recipient": rec.get("recipient"),
                    "payload": rec.get("payload"), "phash": rec.get("phash"),
                    "block_hashes": rec.get("block_hashes"), "backend": rec.get("backend")}

    found = best["match_fraction"] >= 0.85
    phash_dist = hamming_distance(best["phash"], perceptual_hash(bgr)) if best["phash"] else 64
    tampered_fraction = 0.0
    mask_url = None
    if best["block_hashes"]:
        resized = bgr
        # block_hashes were computed on a (possibly downscaled) issued image; the
        # grid is scale-invariant, so compare directly.
        mask, tampered_fraction = localize_tamper(resized, best["block_hashes"])
        if tampered_fraction > 0:
            cv2.imencode(".png", mask)[1].tofile(str(output_dir(session_id) / "tamper_mask.png"))
            mask_url = f"{settings.api_prefix}/sessions/{session_id}/3d/tamper_mask.png"
    tampered = bool(found and (phash_dist > 8 or tampered_fraction > 0.01))
    return VerifyResponse(
        watermark_found=found, recipient=best["recipient"] if found else None,
        payload=best["payload"] if found else None, match_fraction=round(best["match_fraction"], 4),
        tampered=tampered, phash_distance=phash_dist, tampered_fraction=tampered_fraction,
        tamper_mask_url=mask_url, backend=best["backend"],
    )


@app.post(f"{settings.api_prefix}/license/issue", response_model=LicenseResponse)
def issue_license(payload: LicenseRequest):
    from .services.licensing import issue_token

    data = issue_token(payload.recipient, payload.tier, payload.days)
    return LicenseResponse(token=data["token"], recipient=data["recipient"], tier=data["tier"],
                           exp=data["exp"], signed=data["signed"])


@app.get(f"{settings.api_prefix}/license/verify")
def verify_license(token: str):
    from .services.licensing import tier_allows, verify_token

    result = verify_token(token)
    if result.get("valid"):
        result["allows"] = sorted(v for v in ("raw", "optimized", "watermarked", "enhanced", "upscaled", "archive")
                                  if tier_allows(result.get("tier", "viewer"), v))
    return result


def _read_session_raw(session: SessionModel, max_dim: int = 3000):
    import cv2
    import numpy as np
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(resolve_raw_image_path(session)) as src:
        img = src.convert("RGB")
        scale = min(1.0, max_dim / float(max(img.size)))
        if scale < 1.0:
            img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/timeline")
def change_timeline(session_id: str, payload: TimelineRequest, db: Session = Depends(get_db)):
    """Multi-temporal state tracking: pairwise change across dated captures."""
    from .services.change_detection import detect_changes

    session = db.get(SessionModel, session_id)
    if not session or session.status != "ready":
        raise HTTPException(status_code=404, detail="Session not ready")
    ids = [session_id] + [i for i in payload.others if i != session_id]
    sessions = []
    for sid in ids:
        s = db.get(SessionModel, sid)
        if s and s.status == "ready":
            sessions.append(s)
    if len(sessions) < 2:
        raise HTTPException(status_code=400, detail="Need at least two ready sessions")
    sessions.sort(key=lambda s: s.created_at)

    images = {s.id: _read_session_raw(s) for s in sessions}
    steps = []
    for a, b in zip(sessions, sessions[1:]):
        result, _mask = detect_changes(images[a.id], images[b.id], sensitivity=payload.sensitivity)
        steps.append({
            "from": {"id": a.id, "name": a.name, "date": a.created_at.isoformat()},
            "to": {"id": b.id, "name": b.name, "date": b.created_at.isoformat()},
            "aligned": result.aligned, "change_fraction": result.change_fraction,
            "regions": result.regions[:50],
        })
    return {"object": session.name, "states": len(sessions), "steps": steps}


@app.get("/timeline/{session_id}", response_class=HTMLResponse)
def timeline_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "timeline.html", {"session_id": session_id})


@app.get("/mirador/{session_id}", response_class=HTMLResponse)
def mirador_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "mirador.html", {"session_id": session_id})


@app.get("/ar/{session_id}", response_class=HTMLResponse)
def ar_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "ar.html", {"session_id": session_id})


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/edm.xml")
def get_edm_xml(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Europeana Data Model (EDM) record for aggregation into national portals."""
    import json as _json
    from fastapi import Response
    from xml.sax.saxutils import escape

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        meta = _json.loads(session.metadata_json) if session.metadata_json else {}
    except Exception:
        meta = {}
    pid = _ensure_pid(session, db)
    base = str(request.base_url).rstrip("/")
    view = f"{base}/viewer/{session_id}"
    iiif = f"{base}{settings.api_prefix}/sessions/{session_id}/iiif/manifest"

    def e(v):
        return escape("" if v is None else str(v))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:edm="http://www.europeana.eu/schemas/edm/" xmlns:ore="http://www.openarchives.org/ore/terms/">\n'
        f'  <edm:ProvidedCHO rdf:about="{e(pid)}">\n'
        f"    <dc:title>{e(meta.get('title') or session.name)}</dc:title>\n"
        f"    <dc:creator>{e(meta.get('creator'))}</dc:creator>\n"
        f"    <dc:type>{e(meta.get('material'))}</dc:type>\n"
        f"    <dcterms:provenance>{e(meta.get('repository'))}</dcterms:provenance>\n"
        f"    <dc:rights>{e(meta.get('rights'))}</dc:rights>\n"
        f"    <edm:type>IMAGE</edm:type>\n"
        "  </edm:ProvidedCHO>\n"
        f'  <ore:Aggregation rdf:about="{e(pid)}#aggregation">\n'
        f'    <edm:aggregatedCHO rdf:resource="{e(pid)}"/>\n'
        f'    <edm:isShownAt rdf:resource="{e(view)}"/>\n'
        f'    <edm:isShownBy rdf:resource="{e(iiif)}"/>\n'
        f"    <edm:provider>Hyper Gigapixel Agent</edm:provider>\n"
        "  </ore:Aggregation>\n"
        "</rdf:RDF>\n"
    )
    return Response(content=xml, media_type="application/rdf+xml")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/export-preset")
def export_preset_endpoint(session_id: str, payload: ExportPresetRequest, db: Session = Depends(get_db)):
    from fastapi import Response

    from .services.export_presets import build_preset

    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")
    bgr = _read_raw_bgr(session, max_dim=2400)
    data, _files = build_preset(bgr, output_dir(session_id), payload.preset)
    name = build_download_filename(session, variant=f"preset-{payload.preset}", file_path=Path("x.zip"))
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/images")
async def upload_images(session_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    if len(files) > settings.max_upload_files:
        raise HTTPException(status_code=400, detail=f"Too many files. Max is {settings.max_upload_files}")

    base_dir = upload_dir(session_id)
    current_count = db.query(func.count(SourceImage.id)).filter(SourceImage.session_id == session_id).scalar() or 0

    saved = []
    for idx, file in enumerate(files):
        if not file.filename:
            continue
        safe_name = file.filename.replace("..", "_").replace("/", "_").replace("\\", "_")
        target = base_dir / f"{current_count + idx:05d}_{safe_name}"
        with target.open("wb") as fp:
            shutil.copyfileobj(file.file, fp)

        image_row = SourceImage(
            session_id=session_id,
            filename=file.filename,
            file_path=str(target),
            sort_order=current_count + idx,
        )
        db.add(image_row)
        saved.append(file.filename)

    session.status = "uploaded"
    db.commit()

    return {"session_id": session_id, "uploaded": saved, "count": len(saved)}


@app.post(f"{settings.api_prefix}/node/uploads")
async def create_node_upload(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > settings.max_upload_files:
        raise HTTPException(status_code=400, detail=f"Too many files. Max is {settings.max_upload_files}")

    upload_id = uuid.uuid4().hex
    base_dir = node_upload_dir(upload_id)

    saved: list[str] = []
    for idx, file in enumerate(files):
        if not file.filename:
            continue
        safe_name = file.filename.replace("..", "_").replace("/", "_").replace("\\", "_")
        target = base_dir / f"{idx:05d}_{safe_name}"
        with target.open("wb") as fp:
            shutil.copyfileobj(file.file, fp)
        saved.append(file.filename)

    if len(saved) < 2:
        for path in base_dir.iterdir():
            if path.is_file():
                path.unlink()
        base_dir.rmdir()
        raise HTTPException(status_code=400, detail="At least 2 images are required")

    return {"upload_id": upload_id, "count": len(saved), "files": saved}


@app.get(f"{settings.api_prefix}/node/uploads")
def list_node_uploads():
    root = node_upload_path("")
    items = []
    if root.exists():
        for child in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name):
            count = len([f for f in child.iterdir() if f.is_file()])
            items.append({"upload_id": child.name, "count": count})
    return {"uploads": items}


@app.websocket("/ws/workflow")
async def workflow_ws(websocket: WebSocket):
    await websocket.accept()

    async def emit(event: str, payload: dict):
        await websocket.send_json({"event": event, "payload": payload})

    await emit(
        "hello",
        {
            "message": "workflow socket connected",
            "type_colors": TYPE_COLORS,
            "node_library": NODE_LIBRARY,
        },
    )

    try:
        while True:
            message = await websocket.receive_json()
            action = str(message.get("action") or "").strip()

            if action == "ping":
                await emit("pong", {"ts": message.get("ts")})
                continue

            if action == "get_library":
                await emit("library", {"type_colors": TYPE_COLORS, "node_library": NODE_LIBRARY})
                continue

            if action == "run_graph":
                graph_payload = message.get("graph")
                if not isinstance(graph_payload, dict):
                    await emit("error", {"message": "graph payload is required"})
                    continue

                await emit("run_started", {"message": "Graph execution started"})
                db = SessionLocal()
                try:
                    await execute_graph(db, graph_payload, emit)
                    await emit("run_complete", {"message": "Graph execution completed"})
                except WorkflowExecutionError as exc:
                    db.rollback()
                    await emit("run_failed", {"message": str(exc)})
                except Exception as exc:  # pragma: no cover
                    db.rollback()
                    await emit("run_failed", {"message": str(exc)})
                finally:
                    db.close()
                continue

            await emit("error", {"message": f"Unsupported action: {action}"})
    except WebSocketDisconnect:
        return


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/process", response_model=ProcessResponse, status_code=202)
def process_session(
    session_id: str,
    payload: ProcessRequest,
    db: Session = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    image_count = db.query(func.count(SourceImage.id)).filter(SourceImage.session_id == session_id).scalar() or 0
    if image_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 images are required")

    jobs = JobService(db)
    active_job = jobs.active_job_for_session(session_id)
    if active_job:
        raise HTTPException(status_code=409, detail="A processing job is already active for this session")

    jobs.enqueue_processing_job(session, payload.mode)

    return ProcessResponse(message="Queued for agent processing", session_id=session_id, status="queued")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/dzi")
def get_dzi_descriptor(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session or not session.dzi_descriptor_path:
        raise HTTPException(status_code=404, detail="DZI not found")

    path = Path(session.dzi_descriptor_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="DZI descriptor missing")

    return FileResponse(path, media_type="application/xml")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/quality")
def get_quality_report(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    report_path = output_dir(session_id) / "quality_report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Quality report not available")

    return FileResponse(report_path, media_type="application/json")


def _serve_sidecar(session_id: str, db: Session, rel: str, media_type: str):
    if not db.get(SessionModel, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    path = output_dir(session_id) / rel
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{rel} not available")
    return FileResponse(path, media_type=media_type)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/manifest")
def get_manifest(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "processing_manifest.json", "application/json")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/color")
def get_color_report(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "color_report.json", "application/json")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/provenance")
def get_provenance(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "provenance.json", "application/json")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/provenance/{{layer}}")
def get_provenance_layer(session_id: str, layer: str, db: Session = Depends(get_db)):
    if layer not in {"coverage", "synthetic", "uncertainty"}:
        raise HTTPException(status_code=400, detail="Unknown provenance layer")
    return _serve_sidecar(session_id, db, f"provenance/{layer}.png", "image/png")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/iiif/info.json")
def get_iiif_info(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "iiif/info.json", "application/json")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/iiif/manifest")
def get_iiif_manifest(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "iiif/manifest.json", "application/json")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/scale", response_model=ScaleResponse)
def calibrate_scale(session_id: str, payload: ScaleRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from .services.scale import scale_from_marker, scale_from_reference

    if None not in (payload.point_a_x, payload.point_a_y, payload.point_b_x, payload.point_b_y) and payload.length_mm:
        result = scale_from_reference(
            (payload.point_a_x, payload.point_a_y), (payload.point_b_x, payload.point_b_y), payload.length_mm
        )
    else:
        if session.status != "ready":
            raise HTTPException(status_code=409, detail="Session is not ready yet")
        import cv2
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        raw_path = resolve_raw_image_path(session)
        with Image.open(raw_path) as src:
            import numpy as np

            bgr = cv2.cvtColor(np.asarray(src.convert("RGB")), cv2.COLOR_RGB2BGR)
        result = scale_from_marker(bgr, payload.marker_length_mm)
    if result.calibrated and result.pixels_per_mm:
        session.pixels_per_mm = float(result.pixels_per_mm)
        db.commit()
    return ScaleResponse(**result.to_dict())


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/change-detection", response_model=ChangeDetectResponse)
def run_change_detection(session_id: str, payload: ChangeDetectRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    other = db.get(SessionModel, payload.other_session_id)
    if not session or not other:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready" or other.status != "ready":
        raise HTTPException(status_code=409, detail="Both sessions must be ready")

    import cv2
    import numpy as np
    from PIL import Image

    from .services.change_detection import detect_changes

    Image.MAX_IMAGE_PIXELS = None

    def _read(s, max_dim=3000):
        with Image.open(resolve_raw_image_path(s)) as src:
            img = src.convert("RGB")
            scale = min(1.0, max_dim / float(max(img.size)))
            if scale < 1.0:
                img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
            return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

    result, _mask = detect_changes(_read(other), _read(session), sensitivity=payload.sensitivity)
    data = result.to_dict()
    return ChangeDetectResponse(**data)


def _session_source_paths(session: SessionModel) -> list[Path]:
    return [Path(img.file_path) for img in sorted(session.images, key=lambda x: x.sort_order)]


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/focus-stack", response_model=FocusStackResponse)
def run_focus_stack(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    paths = _session_source_paths(session)
    if len(paths) < 2:
        raise HTTPException(status_code=400, detail="Focus stacking needs at least 2 source images")

    import cv2

    from .services.focus_stack import focus_stack_paths

    fused = focus_stack_paths(paths)
    out_path = output_dir(session_id) / "focus_stacked.jpg"
    ok, encoded = cv2.imencode(".jpg", fused, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode fused image")
    encoded.tofile(str(out_path))
    return FocusStackResponse(ok=True, output=str(out_path), frames=len(paths))


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/photometric", response_model=PhotometricResponse)
def run_photometric(session_id: str, payload: PhotometricRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    paths = _session_source_paths(session)
    if len(paths) < 3:
        raise HTTPException(status_code=400, detail="Photometric stereo needs at least 3 lit images")
    if len(payload.light_dirs) != len(paths):
        raise HTTPException(status_code=400, detail="Provide one light direction per source image")

    import cv2

    from .services.feature_matching import read_image_bgr
    from .services.photometric import photometric_stereo

    images = [read_image_bgr(p) for p in paths]
    result = photometric_stereo(images, payload.light_dirs)
    base = output_dir(session_id)
    normal_path = base / "normal_map.png"
    albedo_path = base / "albedo.png"
    cv2.imencode(".png", result.normal_map_bgr)[1].tofile(str(normal_path))
    cv2.imencode(".png", (result.albedo * 255).astype("uint8"))[1].tofile(str(albedo_path))
    return PhotometricResponse(ok=True, normal_map=str(normal_path), albedo=str(albedo_path))


def _read_raw_bgr(session: SessionModel, max_dim: int = 0):
    """Read the raw mosaic as BGR, optionally downscaled to a long-edge cap."""
    import cv2
    import numpy as np
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(resolve_raw_image_path(session)) as src:
        img = src.convert("RGB")
        if max_dim and max(img.size) > max_dim:
            scale = max_dim / float(max(img.size))
            img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/iiif/{{region}}/{{size}}/{{rotation}}/{{quality_format}}")
def iiif_image(session_id: str, region: str, size: str, rotation: str, quality_format: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session or session.status != "ready":
        raise HTTPException(status_code=404, detail="Image not available")
    from fastapi import Response

    from .services.iiif import IIIFError, render_iiif

    quality, _, fmt = quality_format.rpartition(".")
    if not fmt:
        raise HTTPException(status_code=400, detail="format required, e.g. default.jpg")
    try:
        data, media = render_iiif(resolve_raw_image_path(session), region, size, rotation, quality or "default", fmt)
    except IIIFError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(content=data, media_type=media)


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/analyze-condition", response_model=ConditionResponse)
def analyze_condition_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    import cv2

    from .services.damage_ai import analyze_condition

    bgr = _read_raw_bgr(session, max_dim=int(settings.condition_max_dim))
    report, overlay = analyze_condition(bgr)
    base = output_dir(session_id)
    cv2.imencode(".png", overlay)[1].tofile(str(base / "condition_overlay.png"))
    import json

    (base / "condition_report.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    data = report.to_dict()
    data["overlay_url"] = f"{settings.api_prefix}/sessions/{session_id}/condition/overlay"
    return ConditionResponse(**data)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/condition/overlay")
def get_condition_overlay(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "condition_overlay.png", "image/png")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/condition")
def get_condition_report(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "condition_report.json", "application/json")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/restore", response_model=RestoreResponse)
def restore_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    import cv2

    from .services.restore import restore_image

    bgr = _read_raw_bgr(session, max_dim=int(settings.restore_max_dim))
    result = restore_image(bgr)
    out = output_dir(session_id) / "restored.jpg"
    cv2.imencode(".jpg", result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(out))
    return RestoreResponse(
        ok=True,
        backend=result.backend,
        actions=result.actions,
        before_url=f"{settings.api_prefix}/sessions/{session_id}/download/optimized",
        after_url=f"{settings.api_prefix}/sessions/{session_id}/download/restored",
        compare_url=f"/compare/{session_id}",
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/restored")
def download_restored(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "restored.jpg", "image/jpeg")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/outpaint", response_model=OutpaintResponse)
def outpaint_endpoint(session_id: str, payload: OutpaintRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    import cv2

    from .services.outpaint import outpaint_image

    bgr = _read_raw_bgr(session, max_dim=max(2048, int(settings.outpaint_max_dim)))
    result = outpaint_image(bgr, mode=payload.mode, margin=payload.margin)
    base = output_dir(session_id)
    cv2.imencode(".jpg", result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(base / "stitched_outpainted.jpg"))
    cv2.imencode(".png", result.generated_mask)[1].tofile(str(base / "outpaint_mask.png"))
    h, w = result.image.shape[:2]
    generated = float(int((result.generated_mask > 0).sum())) / max(1, h * w)
    api = settings.api_prefix
    return OutpaintResponse(
        ok=True,
        backend=result.backend,
        mode=result.mode,
        width=w,
        height=h,
        generated_fraction=round(generated, 6),
        image_url=f"{api}/sessions/{session_id}/download/outpainted",
        mask_url=f"{api}/sessions/{session_id}/outpaint-mask",
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/outpainted")
def download_outpainted(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "stitched_outpainted.jpg", "image/jpeg")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/outpaint-mask")
def get_outpaint_mask(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "outpaint_mask.png", "image/png")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/upscale", response_model=UpscaleResponse)
def upscale_endpoint(session_id: str, payload: UpscaleRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    import cv2

    from .services.upscale import upscale_image

    factor = float(payload.factor)
    # Cap the input so the upscaled output stays within the configured pixel budget.
    import math

    max_out = int(settings.upscale_max_output_pixels)
    input_cap = max(512, int(math.sqrt(max_out) / max(1.0, factor)))
    bgr = _read_raw_bgr(session, max_dim=input_cap)

    if payload.backend:
        original_backend = settings.upscale_backend
        settings.upscale_backend = payload.backend
    try:
        result = upscale_image(bgr, factor)
    finally:
        if payload.backend:
            settings.upscale_backend = original_backend

    out_path = output_dir(session_id) / "stitched_upscaled.jpg"
    cv2.imencode(".jpg", result.image, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(out_path))
    h, w = result.image.shape[:2]
    return UpscaleResponse(
        ok=True,
        backend=result.backend,
        factor=result.factor,
        width=w,
        height=h,
        image_url=f"{settings.api_prefix}/sessions/{session_id}/download/upscaled",
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/upscaled")
def download_upscaled(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "stitched_upscaled.jpg", "image/jpeg")


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/splat", response_model=SplatResponse)
def splat_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    from .services.splat import generate_splat

    bgr = _read_raw_bgr(session, max_dim=2400)
    result = generate_splat(bgr, output_dir(session_id))
    api = settings.api_prefix
    return SplatResponse(
        ok=True,
        num_points=result.num_points,
        depth_backend=result.depth_backend,
        pointcloud_url=f"{api}/sessions/{session_id}/pointcloud.ply" if result.pointcloud_path else None,
        gaussian_url=f"{api}/sessions/{session_id}/gaussians.ply" if result.gaussian_path else None,
        explorer_url=f"/viewer3d/{session_id}",
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/pointcloud.ply")
def get_pointcloud(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "pointcloud.ply", "application/octet-stream")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/gaussians.ply")
def get_gaussians(session_id: str, db: Session = Depends(get_db)):
    return _serve_sidecar(session_id, db, "gaussians.ply", "application/octet-stream")


_3D_MEDIA = {
    ".splat": "application/octet-stream",
    ".ply": "application/octet-stream",
    ".obj": "text/plain",
    ".mtl": "text/plain",
    ".glb": "model/gltf-binary",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/to3d", response_model=To3DResponse)
def to3d_endpoint(session_id: str, payload: To3DRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    from .services.splat import build_3d

    bgr = _read_raw_bgr(session, max_dim=2400)
    result = build_3d(bgr, payload.representation, output_dir(session_id))
    api = settings.api_prefix
    artifacts = {
        name: f"{api}/sessions/{session_id}/3d/{Path(path).name}"
        for name, path in result["artifacts"].items()
    }
    return To3DResponse(
        ok=True,
        representation=result["representation"],
        depth_backend=result["depth_backend"],
        num_points=result["num_points"],
        artifacts=artifacts,
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/3d/{{filename}}")
def get_3d_asset(session_id: str, filename: str, db: Session = Depends(get_db)):
    if not db.get(SessionModel, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    name = Path(filename).name  # prevent path traversal
    media = _3D_MEDIA.get(Path(name).suffix.lower())
    if media is None:
        raise HTTPException(status_code=400, detail="Unsupported 3D asset type")
    path = output_dir(session_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="3D asset not available")
    return FileResponse(path, media_type=media)


@app.get("/viewer3d/{session_id}", response_class=HTMLResponse)
def viewer3d_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "viewer3d.html", {"session_id": session_id})


@app.get("/compare/{session_id}", response_class=HTMLResponse)
def compare_page(session_id: str, request: Request):
    return templates.TemplateResponse(request, "compare.html", {"session_id": session_id})


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/reconstruct3d", response_model=ReconResponse)
def reconstruct3d_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    paths = _session_source_paths(session)
    if len(paths) < 2:
        raise HTTPException(status_code=400, detail="Multi-view reconstruction needs at least 2 source images")

    import shutil as _shutil

    from .services.recon3d import reconstruct

    base = output_dir(session_id)
    result = reconstruct(paths, base)
    # Surface the multi-view cloud through the existing 3D explorer.
    if result.pointcloud_path:
        _shutil.copyfile(result.pointcloud_path, base / "pointcloud.ply")
    if result.gaussian_path:
        _shutil.copyfile(result.gaussian_path, base / "gaussians.ply")
    api = settings.api_prefix
    return ReconResponse(
        ok=True,
        backend=result.backend,
        num_points=result.num_points,
        pointcloud_url=f"{api}/sessions/{session_id}/pointcloud.ply" if result.pointcloud_path else None,
        gaussian_url=f"{api}/sessions/{session_id}/gaussians.ply" if result.gaussian_path else None,
        explorer_url=f"/viewer3d/{session_id}",
        note=result.note,
    )


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/tags", response_model=TagsResponse)
def auto_tag_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    from .services.semantic import auto_tags, backend as semantic_backend

    bgr = _read_raw_bgr(session, max_dim=1024)
    tags = auto_tags(bgr)
    session.tags = ",".join(t["tag"] for t in tags)
    db.commit()
    return TagsResponse(backend=semantic_backend(), tags=tags)


@app.get(f"{settings.api_prefix}/search", response_model=SearchResponse)
def semantic_search(q: str, limit: int = 20, db: Session = Depends(get_db)):
    from .services.semantic import backend as semantic_backend, rank_sessions

    ready = db.query(SessionModel).filter(SessionModel.status == "ready").all()
    items = []
    for s in ready:
        try:
            items.append((s.id, resolve_optimized_image_path(s), s.tags))
        except HTTPException:
            continue
    results = rank_sessions(q, items, limit=limit)
    return SearchResponse(backend=semantic_backend(), query=q, results=results)


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/coverage-check", response_model=CoverageResponse)
def coverage_check_endpoint(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    paths = _session_source_paths(session)
    if len(paths) < 2:
        raise HTTPException(status_code=400, detail="Coverage QA needs at least 2 source images")

    from .services.coverage import analyze_coverage

    report = analyze_coverage(paths)
    return CoverageResponse(**report.to_dict())


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/queue")
def queue_status(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    jobs = JobService(db)
    job = jobs.active_job_for_session(session_id)
    return {
        "session_status": session.status,
        "job_status": job.status if job else None,
        "queue_position": jobs.queue_position(session_id),
        "attempts": job.attempts if job else 0,
    }


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/tiles/{{tile_path:path}}")
def get_tile(session_id: str, tile_path: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session or not session.dzi_descriptor_path:
        raise HTTPException(status_code=404, detail="Session or DZI not found")

    root = Path(session.dzi_descriptor_path).parent
    target = (root / "image_files" / tile_path).resolve()

    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tile path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Tile not found")

    return FileResponse(target)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/annotations", response_model=list[AnnotationRead])
def list_annotations(session_id: str, db: Session = Depends(get_db)):
    rows = db.query(Annotation).filter(Annotation.session_id == session_id).order_by(Annotation.id.asc()).all()
    return [_serialize_annotation(row) for row in rows]


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download")
def download_result_package(session_id: str, db: Session = Depends(get_db)):
    # Backward-compatible alias: default download returns the pure high-resolution output.
    return download_raw_image(session_id=session_id, db=db)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/raw")
def download_raw_image(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    stitched_path = resolve_raw_image_path(session)
    image_name = build_download_filename(session, variant="raw", file_path=stitched_path)

    return FileResponse(
        stitched_path,
        media_type=media_type_for_image(stitched_path),
        filename=image_name,
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/optimized")
def download_optimized_image(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    stitched_path = resolve_optimized_image_path(session)
    image_name = build_download_filename(session, variant="optimized", file_path=stitched_path)

    return FileResponse(
        stitched_path,
        media_type=media_type_for_image(stitched_path),
        filename=image_name,
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/download/enhanced")
def download_enhanced_image(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    stitched_path = resolve_enhanced_image_path(session)
    image_name = build_download_filename(session, variant="enhanced", file_path=stitched_path)

    return FileResponse(
        stitched_path,
        media_type=media_type_for_image(stitched_path),
        filename=image_name,
    )


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/segment", response_model=SegmentResponse)
def segment_region_endpoint(session_id: str, payload: SegmentRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not bool(settings.sam_enabled):
        raise HTTPException(status_code=503, detail="Smart annotation is disabled")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    from .services.segmentation import segment_region

    raw_path = resolve_raw_image_path(session)
    crop, origin = _load_region(raw_path, payload)
    point = None
    if payload.point_x is not None and payload.point_y is not None:
        point = (payload.point_x - origin[0], payload.point_y - origin[1])
    box = None
    if None not in (payload.box_x, payload.box_y, payload.box_w, payload.box_h):
        box = (
            payload.box_x - origin[0],
            payload.box_y - origin[1],
            payload.box_x + payload.box_w - origin[0],
            payload.box_y + payload.box_h - origin[1],
        )

    polygon, backend = segment_region(crop, point, box)
    mapped = [[float(px + origin[0]), float(py + origin[1])] for px, py in polygon]
    return SegmentResponse(backend=backend, polygon=mapped)


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/detect-damage", response_model=DamageResponse)
def detect_damage_endpoint(session_id: str, payload: SegmentRequest, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not bool(settings.sam_enabled):
        raise HTTPException(status_code=503, detail="Smart annotation is disabled")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    from .services.segmentation import detect_damage

    raw_path = resolve_raw_image_path(session)
    crop, origin = _load_region(raw_path, payload)
    regions = detect_damage(crop)
    for region in regions:
        region["x"] += int(origin[0])
        region["y"] += int(origin[1])
    return DamageResponse(backend="classical", regions=regions)


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/annotations", response_model=AnnotationRead)
def create_annotation(session_id: str, payload: AnnotationCreate, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    import json as _json

    row = Annotation(
        session_id=session_id,
        x=payload.x,
        y=payload.y,
        text=payload.text,
        shape=payload.shape,
        w=payload.w,
        h=payload.h,
        points_json=_json.dumps(payload.points) if payload.points else None,
        tags=payload.tags,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_annotation(row)


@app.delete(f"{settings.api_prefix}/annotations/{{annotation_id}}")
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    row = db.get(Annotation, annotation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(row)
    db.commit()
    return {"deleted": annotation_id}

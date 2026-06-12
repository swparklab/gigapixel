from pathlib import Path
import shutil
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .logging_config import configure_logging
from .models import Annotation, Session as SessionModel, SourceImage
from .schemas import (
    AnnotationCreate,
    AnnotationRead,
    AcquisitionPlanRead,
    AcquisitionPlanRequest,
    DamageResponse,
    ProcessRequest,
    ProcessResponse,
    SegmentRequest,
    SegmentResponse,
    SessionCreate,
    SessionRead,
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

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

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
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Default landing mode is classic UI.
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/classic", response_class=HTMLResponse)
def classic(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/viewer/{session_id}", response_class=HTMLResponse)
def viewer(request: Request, session_id: str):
    return templates.TemplateResponse("viewer.html", {"request": request, "session_id": session_id})


@app.get("/workflow", response_class=HTMLResponse)
def workflow_page(request: Request):
    return templates.TemplateResponse("workflow.html", {"request": request})


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
    return [
        AnnotationRead(
            id=row.id,
            session_id=row.session_id,
            x=row.x,
            y=row.y,
            text=row.text,
            created_at=row.created_at,
        )
        for row in rows
    ]


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

    row = Annotation(session_id=session_id, x=payload.x, y=payload.y, text=payload.text)
    db.add(row)
    db.commit()
    db.refresh(row)

    return AnnotationRead(
        id=row.id,
        session_id=row.session_id,
        x=row.x,
        y=row.y,
        text=row.text,
        created_at=row.created_at,
    )


@app.delete(f"{settings.api_prefix}/annotations/{{annotation_id}}")
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    row = db.get(Annotation, annotation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(row)
    db.commit()
    return {"deleted": annotation_id}

from pathlib import Path
import json
import re
import shutil
import zipfile

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import Annotation, Session as SessionModel, SourceImage
from .schemas import (
    AnnotationCreate,
    AnnotationRead,
    ProcessRequest,
    ProcessResponse,
    SessionCreate,
    SessionRead,
)
from .services.storage import upload_dir
from .services.tasks import run_pipeline

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


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    return sanitized or "session"


def _build_download_package(session: SessionModel, annotations: list[Annotation]) -> tuple[Path, str]:
    if not session.stitched_image_path or not session.dzi_descriptor_path:
        raise HTTPException(status_code=404, detail="Output files are not ready")

    stitched_path = Path(session.stitched_image_path)
    descriptor_path = Path(session.dzi_descriptor_path)
    if not stitched_path.exists() or not descriptor_path.exists():
        raise HTTPException(status_code=404, detail="Output files are missing")

    tiles_root = descriptor_path.parent / "image_files"
    if not tiles_root.exists():
        raise HTTPException(status_code=404, detail="DZI tiles are missing")

    download_dir = descriptor_path.parent / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    bundle_name = f"{_sanitize_filename(session.name)}_{session.id}.zip"
    bundle_path = download_dir / bundle_name

    annotations_payload = [
        {
            "id": row.id,
            "session_id": row.session_id,
            "x": row.x,
            "y": row.y,
            "text": row.text,
            "created_at": row.created_at.isoformat(),
        }
        for row in annotations
    ]

    manifest_payload = {
        "session_id": session.id,
        "name": session.name,
        "status": session.status,
        "width": session.width,
        "height": session.height,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "files": {
            "stitched_image": "stitched/stitched.jpg",
            "dzi_descriptor": "deepzoom/image.dzi",
            "dzi_tiles_dir": "deepzoom/image_files/",
            "annotations": "annotations.json",
        },
    }

    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(stitched_path, arcname="stitched/stitched.jpg")
        zipf.write(descriptor_path, arcname="deepzoom/image.dzi")

        for tile_path in tiles_root.rglob("*"):
            if tile_path.is_file():
                relative = tile_path.relative_to(descriptor_path.parent)
                zipf.write(tile_path, arcname=f"deepzoom/{relative.as_posix()}")

        zipf.writestr(
            "annotations.json",
            json.dumps(annotations_payload, ensure_ascii=False, indent=2),
        )
        zipf.writestr(
            "manifest.json",
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        )

    return bundle_path, bundle_name


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


def _run_pipeline_background(session_id: str, mode: str) -> None:
    db = SessionLocal()
    try:
        session = db.get(SessionModel, session_id)
        if not session:
            return
        run_pipeline(db, session, mode=mode)
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/viewer/{session_id}", response_class=HTMLResponse)
def viewer(request: Request, session_id: str):
    return templates.TemplateResponse("viewer.html", {"request": request, "session_id": session_id})


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


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/process", response_model=ProcessResponse)
def process_session(
    session_id: str,
    payload: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    image_count = db.query(func.count(SourceImage.id)).filter(SourceImage.session_id == session_id).scalar() or 0
    if image_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 images are required")

    session.status = "queued"
    session.error_message = None
    db.commit()

    background_tasks.add_task(_run_pipeline_background, session_id, payload.mode)

    return ProcessResponse(message="Processing started", session_id=session_id, status="queued")


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/dzi")
def get_dzi_descriptor(session_id: str, db: Session = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if not session or not session.dzi_descriptor_path:
        raise HTTPException(status_code=404, detail="DZI not found")

    path = Path(session.dzi_descriptor_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="DZI descriptor missing")

    return FileResponse(path, media_type="application/xml")


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
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready yet")

    annotations = db.query(Annotation).filter(Annotation.session_id == session_id).order_by(Annotation.id.asc()).all()
    bundle_path, bundle_name = _build_download_package(session, annotations)

    return FileResponse(
        bundle_path,
        media_type="application/zip",
        filename=bundle_name,
    )


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

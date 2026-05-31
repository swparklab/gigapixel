from pathlib import Path

from ..config import settings


def session_root(session_id: str) -> Path:
    path = settings.data_root / "sessions" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def upload_dir(session_id: str) -> Path:
    path = session_root(session_id) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(session_id: str) -> Path:
    path = session_root(session_id) / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dzi_dir(session_id: str) -> Path:
    path = output_dir(session_id) / "dzi"
    path.mkdir(parents=True, exist_ok=True)
    return path


def node_uploads_root() -> Path:
    path = settings.data_root / "node_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def node_upload_dir(upload_id: str) -> Path:
    path = node_upload_path(upload_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def node_upload_path(upload_id: str) -> Path:
    return node_uploads_root() / upload_id

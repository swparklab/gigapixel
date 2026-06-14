from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Additive columns introduced after the initial schema. SQLite supports
# ADD COLUMN, so we apply them idempotently instead of pulling in Alembic.
_ADDITIVE_COLUMNS = {
    "processing_jobs": {
        "worker_id": "VARCHAR(80)",
        "heartbeat_at": "DATETIME",
        "lease_expires_at": "DATETIME",
        "attempts": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 3",
    },
    "sessions": {
        "tags": "TEXT",
        "metadata_json": "TEXT",
        "pixels_per_mm": "FLOAT",
        "pid": "VARCHAR(80)",
    },
    "annotations": {
        "shape": "VARCHAR(16) DEFAULT 'point'",
        "w": "FLOAT",
        "h": "FLOAT",
        "points_json": "TEXT",
        "tags": "TEXT",
    },
}


def ensure_schema() -> None:
    """Create tables and apply additive column migrations in place."""
    from . import models  # noqa: F401  (register ORM models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Session as SessionModel
from app.services.jobs import JobService


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def test_enqueue_and_claim_job():
    db = make_db()
    try:
        session = SessionModel(name="queue smoke")
        db.add(session)
        db.commit()
        db.refresh(session)

        jobs = JobService(db)
        job = jobs.enqueue_processing_job(session, "scans")

        assert session.status == "queued"
        assert job.status == "queued"
        assert jobs.active_job_for_session(session.id).id == job.id

        claimed = jobs.claim_next_job()

        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == "processing"
        assert claimed.started_at is not None
    finally:
        db.close()


def test_finish_job_from_ready_session_result():
    db = make_db()
    try:
        session = SessionModel(name="finish smoke")
        db.add(session)
        db.commit()
        db.refresh(session)

        jobs = JobService(db)
        job = jobs.enqueue_processing_job(session, "scans")
        claimed = jobs.claim_next_job()
        assert claimed is not None

        session.status = "ready"
        db.commit()

        finished = jobs.finish_job_from_session_result(job.id, session)

        assert finished is not None
        assert finished.status == "done"
        assert finished.error_message is None
        assert finished.finished_at is not None
    finally:
        db.close()


def test_fail_job_marks_session_failed():
    db = make_db()
    try:
        session = SessionModel(name="failure smoke")
        db.add(session)
        db.commit()
        db.refresh(session)

        jobs = JobService(db)
        job = jobs.enqueue_processing_job(session, "scans")
        failed = jobs.fail_job(job.id, session.id, "boom")
        db.refresh(session)

        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_message == "boom"
        assert session.status == "failed"
        assert session.error_message == "boom"
    finally:
        db.close()


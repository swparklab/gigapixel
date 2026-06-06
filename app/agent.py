import argparse
import datetime as dt
import time

from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from .models import ProcessingJob, Session as SessionModel
from .services.tasks import run_pipeline


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _claim_next_job(db: Session) -> ProcessingJob | None:
    candidate = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status == "queued")
        .order_by(ProcessingJob.created_at.asc(), ProcessingJob.id.asc())
        .first()
    )
    if not candidate:
        return None

    updated = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.id == candidate.id, ProcessingJob.status == "queued")
        .update(
            {
                ProcessingJob.status: "processing",
                ProcessingJob.started_at: utc_now(),
                ProcessingJob.error_message: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        return None

    return db.get(ProcessingJob, candidate.id)


def _process_claimed_job(db: Session, job: ProcessingJob) -> None:
    started = utc_now()
    session = db.get(SessionModel, job.session_id)
    if not session:
        job.status = "failed"
        job.error_message = f"Session not found: {job.session_id}"
        job.finished_at = utc_now()
        db.commit()
        return

    try:
        result = run_pipeline(db, session, mode=job.mode)
        job = db.get(ProcessingJob, job.id)
        if not job:
            return

        job.finished_at = utc_now()
        if result.status == "ready":
            job.status = "done"
            job.error_message = None
        else:
            job.status = "failed"
            job.error_message = result.error_message or "Processing failed"
        db.commit()
        elapsed = (utc_now() - started).total_seconds()
        print(
            f"[agent] finished job={job.id} session={job.session_id} "
            f"job_status={job.status} session_status={result.status} elapsed={elapsed:.1f}s"
        )
    except Exception as exc:
        db.rollback()
        session = db.get(SessionModel, job.session_id)
        if session:
            session.status = "failed"
            session.error_message = str(exc)

        job = db.get(ProcessingJob, job.id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = utc_now()
        db.commit()
        elapsed = (utc_now() - started).total_seconds()
        print(f"[agent] failed job={job.id} session={job.session_id} elapsed={elapsed:.1f}s error={exc}")


def run_once() -> bool:
    db = SessionLocal()
    try:
        job = _claim_next_job(db)
        if not job:
            return False

        print(f"[agent] processing job={job.id} session={job.session_id} mode={job.mode}")
        _process_claimed_job(db, job)
        return True
    finally:
        db.close()


def run_forever(poll_interval: float) -> None:
    Base.metadata.create_all(bind=engine)
    print(f"[agent] started. poll_interval={poll_interval}s")
    while True:
        processed = run_once()
        if not processed:
            time.sleep(max(0.2, poll_interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="Gigapixel processing agent")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.agent_poll_interval_seconds,
        help="Queue polling interval in seconds",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process only one job and exit",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    if args.once:
        processed = run_once()
        print("[agent] processed one job." if processed else "[agent] no queued jobs.")
        return

    try:
        run_forever(args.poll_interval)
    except KeyboardInterrupt:
        print("[agent] stopped.")


if __name__ == "__main__":
    main()

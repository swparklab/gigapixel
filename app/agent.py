import argparse
import logging
import os
import socket
import threading
import time
import uuid

from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, ensure_schema
from .logging_config import configure_logging
from .models import ProcessingJob, Session as SessionModel
from .services.jobs import JobService, utc_now
from .services.tasks import run_pipeline

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def _claim_next_job(db: Session) -> ProcessingJob | None:
    return JobService(db).claim_next_job(worker_id=WORKER_ID)


class _Heartbeat:
    """Keeps a job's lease alive while a (blocking) pipeline runs."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        interval = max(2, int(settings.job_heartbeat_seconds))
        while not self._stop.wait(interval):
            db = SessionLocal()
            try:
                JobService(db).heartbeat(self.job_id, WORKER_ID)
            except Exception:
                pass
            finally:
                db.close()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


def _process_claimed_job(db: Session, job: ProcessingJob) -> None:
    started = utc_now()
    jobs = JobService(db)
    session = db.get(SessionModel, job.session_id)
    if not session:
        jobs.mark_missing_session(job)
        return

    try:
        job_id = job.id
        session_id = job.session_id
        with _Heartbeat(job_id):
            result = run_pipeline(db, session, mode=job.mode)
        job = jobs.finish_job_from_session_result(job_id, result)
        if not job:
            return

        elapsed = (utc_now() - started).total_seconds()
        logger.info(
            "agent job finished",
            extra={
                "job_id": job.id,
                "session_id": job.session_id,
                "job_status": job.status,
                "session_status": result.status,
                "elapsed_seconds": round(elapsed, 3),
            },
        )
    except Exception as exc:
        db.rollback()
        job = jobs.fail_job(job.id, job.session_id, str(exc))
        elapsed = (utc_now() - started).total_seconds()
        logger.exception(
            "agent job failed",
            extra={
                "job_id": job.id if job else None,
                "session_id": job.session_id if job else session_id,
                "elapsed_seconds": round(elapsed, 3),
            },
        )


def run_once() -> bool:
    db = SessionLocal()
    try:
        recovered = JobService(db).recover_stale_jobs()
        if recovered:
            logger.warning("recovered stale jobs", extra={"recovered": recovered})
        job = _claim_next_job(db)
        if not job:
            return False

        logger.info(
            "agent job processing",
            extra={"job_id": job.id, "session_id": job.session_id, "mode": job.mode},
        )
        _process_claimed_job(db, job)
        return True
    finally:
        db.close()


def run_forever(poll_interval: float) -> None:
    ensure_schema()
    logger.info("agent started", extra={"poll_interval_seconds": poll_interval})
    while True:
        processed = run_once()
        if not processed:
            time.sleep(max(0.2, poll_interval))


def main() -> None:
    configure_logging(settings.log_level, settings.log_format)
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

    ensure_schema()

    if args.once:
        processed = run_once()
        logger.info("agent once complete", extra={"processed": processed})
        return

    try:
        run_forever(args.poll_interval)
    except KeyboardInterrupt:
        logger.info("agent stopped")


if __name__ == "__main__":
    main()

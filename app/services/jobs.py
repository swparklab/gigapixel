from __future__ import annotations

import datetime as dt

from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..models import ProcessingJob, Session as SessionModel


ACTIVE_JOB_STATUSES = ("queued", "processing")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite may return naive datetimes; coerce to UTC-aware for comparison."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


class JobService:
    """Queue coordination boundary for processing jobs."""

    def __init__(self, db: DbSession) -> None:
        self.db = db

    def active_job_for_session(self, session_id: str) -> ProcessingJob | None:
        return (
            self.db.query(ProcessingJob)
            .filter(
                ProcessingJob.session_id == session_id,
                ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .first()
        )

    def enqueue_processing_job(self, session: SessionModel, mode: str) -> ProcessingJob:
        session.status = "queued"
        session.error_message = None
        job = ProcessingJob(session_id=session.id, mode=mode, status="queued")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def queue_position(self, session_id: str) -> int:
        """Number of queued jobs ahead of this session's active job (0 = next)."""
        job = self.active_job_for_session(session_id)
        if not job or job.status != "queued":
            return 0
        return (
            self.db.query(ProcessingJob)
            .filter(
                ProcessingJob.status == "queued",
                or_(
                    ProcessingJob.created_at < job.created_at,
                    (ProcessingJob.created_at == job.created_at) & (ProcessingJob.id < job.id),
                ),
            )
            .count()
        )

    def claim_next_job(self, worker_id: str | None = None) -> ProcessingJob | None:
        candidate = (
            self.db.query(ProcessingJob)
            .filter(ProcessingJob.status == "queued")
            .order_by(ProcessingJob.created_at.asc(), ProcessingJob.id.asc())
            .first()
        )
        if not candidate:
            return None

        now = utc_now()
        lease = now + dt.timedelta(seconds=int(settings.job_lease_seconds))
        updated = (
            self.db.query(ProcessingJob)
            .filter(ProcessingJob.id == candidate.id, ProcessingJob.status == "queued")
            .update(
                {
                    ProcessingJob.status: "processing",
                    ProcessingJob.started_at: now,
                    ProcessingJob.heartbeat_at: now,
                    ProcessingJob.lease_expires_at: lease,
                    ProcessingJob.worker_id: worker_id,
                    ProcessingJob.attempts: (candidate.attempts or 0) + 1,
                    ProcessingJob.error_message: None,
                },
                synchronize_session=False,
            )
        )
        self.db.commit()
        if updated != 1:
            return None

        return self.db.get(ProcessingJob, candidate.id)

    def heartbeat(self, job_id: int, worker_id: str | None = None) -> None:
        now = utc_now()
        lease = now + dt.timedelta(seconds=int(settings.job_lease_seconds))
        self.db.query(ProcessingJob).filter(ProcessingJob.id == job_id).update(
            {ProcessingJob.heartbeat_at: now, ProcessingJob.lease_expires_at: lease},
            synchronize_session=False,
        )
        self.db.commit()

    def recover_stale_jobs(self) -> int:
        """Requeue (or fail) processing jobs whose lease has expired."""
        if not bool(settings.job_stale_recovery):
            return 0
        now = utc_now()
        stale = (
            self.db.query(ProcessingJob)
            .filter(ProcessingJob.status == "processing")
            .all()
        )
        recovered = 0
        for job in stale:
            expiry = _aware(job.lease_expires_at)
            if expiry is not None and expiry > now:
                continue
            recovered += 1
            max_attempts = job.max_attempts or int(settings.job_max_attempts)
            if (job.attempts or 0) >= max_attempts:
                job.status = "failed"
                job.error_message = f"Exceeded {max_attempts} attempts (stale worker)."
                job.finished_at = now
                session = self.db.get(SessionModel, job.session_id)
                if session and session.status not in ("ready",):
                    session.status = "failed"
                    session.error_message = job.error_message
            else:
                job.status = "queued"
                job.worker_id = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                job.error_message = "Requeued after stale worker."
                session = self.db.get(SessionModel, job.session_id)
                if session and session.status == "processing":
                    session.status = "queued"
        if recovered:
            self.db.commit()
        return recovered

    def mark_missing_session(self, job: ProcessingJob) -> None:
        job.status = "failed"
        job.error_message = f"Session not found: {job.session_id}"
        job.finished_at = utc_now()
        self.db.commit()

    def finish_job_from_session_result(self, job_id: int, result: SessionModel) -> ProcessingJob | None:
        job = self.db.get(ProcessingJob, job_id)
        if not job:
            return None

        job.finished_at = utc_now()
        if result.status == "ready":
            job.status = "done"
            job.error_message = None
        else:
            job.status = "failed"
            job.error_message = result.error_message or "Processing failed"
        self.db.commit()
        self.db.refresh(job)
        return job

    def fail_job(self, job_id: int, session_id: str, error_message: str) -> ProcessingJob | None:
        session = self.db.get(SessionModel, session_id)
        if session:
            session.status = "failed"
            session.error_message = error_message

        job = self.db.get(ProcessingJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = error_message
            job.finished_at = utc_now()
        self.db.commit()
        if job:
            self.db.refresh(job)
        return job


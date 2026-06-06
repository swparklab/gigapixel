from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session as DbSession

from ..models import ProcessingJob, Session as SessionModel


ACTIVE_JOB_STATUSES = ("queued", "processing")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


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

    def claim_next_job(self) -> ProcessingJob | None:
        candidate = (
            self.db.query(ProcessingJob)
            .filter(ProcessingJob.status == "queued")
            .order_by(ProcessingJob.created_at.asc(), ProcessingJob.id.asc())
            .first()
        )
        if not candidate:
            return None

        updated = (
            self.db.query(ProcessingJob)
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
        self.db.commit()
        if updated != 1:
            return None

        return self.db.get(ProcessingJob, candidate.id)

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


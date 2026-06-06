from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected application errors with structured context."""

    code = "app_error"
    http_status = 500

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class ValidationAppError(AppError):
    code = "validation_error"
    http_status = 400


class StorageError(AppError):
    code = "storage_error"
    http_status = 500


class PipelineError(AppError):
    code = "pipeline_error"
    http_status = 500


class ResourceLimitError(PipelineError):
    code = "resource_limit_error"
    http_status = 413


class JobError(AppError):
    code = "job_error"
    http_status = 500


class WorkflowError(AppError):
    code = "workflow_error"
    http_status = 400


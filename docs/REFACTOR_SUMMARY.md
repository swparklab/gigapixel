# Refactor Summary

Last updated: 2026-06-06

## Phase 0: Maintainability Foundation

This phase introduced a small safety foundation without changing public routes or user-facing behavior.

## Changes

- Added `app/errors.py` with a shared application exception hierarchy.
- Added `app/logging_config.py` with JSON structured logging.
- Added `log_level` and `log_format` settings.
- Replaced agent `print()` calls with structured logger calls.
- Added `app/services/jobs.py` as the first queue coordination boundary.
- Updated `app.main.process_session()` to enqueue through `JobService`.
- Updated `app.agent` to claim and finish jobs through `JobService`.
- Made `WorkflowExecutionError` inherit from the shared workflow error type.
- Added pytest as a test dependency.
- Added unit tests for job queue behavior, error hierarchy, filename sanitation, and JSON log formatting.

## Behavior Preservation

The following public behavior remains unchanged:

- Classic UI routes.
- Viewer routes.
- Node workflow route and WebSocket path.
- `/api/sessions/{session_id}/process` queue semantics.
- Agent CLI entry point: `py -3 -m app.agent`.
- Raw and optimized download URLs.

## Verification

Commands run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; py -3 -m pytest -q
$env:PYTHONDONTWRITEBYTECODE='1'; py -3 -c "from app.main import app; print(app.title)"
$env:PYTHONDONTWRITEBYTECODE='1'; py -3 -m app.agent --once
```

Results:

- `6 passed`
- FastAPI app import succeeded.
- Agent `--once` completed and emitted structured JSON logs.

## Remaining Refactor Work

- Add job heartbeat, stale recovery, retry policy, and worker identity.
- Split `app.main` into routers and application services.
- Refactor `GraphRunner` into a node executor registry.
- Route node workflow pipeline execution through the same queue used by classic mode.
- Replace full-array gigapixel output flow with tiled/streaming BigTIFF and DZI generation.


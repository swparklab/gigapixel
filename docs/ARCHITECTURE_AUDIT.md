# Architecture Audit

Last reviewed: 2026-06-06

## Executive Summary

The repository has evolved from a compact local prototype into a multi-surface image processing system with classic UI, node UI, viewer UI, a polling agent, and a high-resolution stitching pipeline. The current architecture is functional, but the production risks are concentrated in four areas:

- Memory safety for 30,000 x 30,000+ BigTIFF workflows.
- Queue reliability and stale job recovery.
- Separation of concerns between API, workflow execution, storage, and pipeline code.
- Observability, testing, and operational controls.

The most important theme: the image alignment pipeline has started moving toward a PTGui-like staged architecture, but the output lifecycle still often returns to full in-memory NumPy/Pillow images. That is the main mismatch with true gigapixel production requirements.

## Critical Findings

### C1. Full-image memory model is not safe for gigapixel BigTIFF outputs

Evidence:

- `services.blending.blend_full_resolution()` returns a full `np.ndarray`.
- `services.stitching.save_stitched_variants()` receives the full stitched array, converts BGR to RGB, writes BigTIFF, then encodes optimized JPEG.
- `services.deepzoom._generate_with_pillow()` opens the stitched image, converts the full image to RGB, and resizes whole pyramid levels.
- `services.exporter._ensure_optimized_from_raw()` can regenerate optimized output from a full Pillow image.

Impact:

- A 30,000 x 30,000 RGB image is about 2.7 GB before copies.
- BGR to RGB conversion, JPEG encoding, DZI generation, masks, weights, and temporary warped images can multiply peak memory.
- The application can still crash or hang on the exact workload it is intended to support.

Severity rationale:

This is the highest production blocker because it can terminate long-running jobs after minutes or hours, leave sessions stuck, and make the BigTIFF research target unreliable.

### C2. Processing jobs can become permanently stuck

Evidence:

- `app.agent._claim_next_job()` marks a job as `processing`.
- There is no heartbeat column, lease timeout, retry counter, worker id, or stale recovery routine.
- `ProcessingJob` has only `created_at`, `started_at`, and `finished_at`.

Impact:

- If the worker process is killed, crashes, loses power, or hits an unhandled memory termination, the job can remain `processing`.
- The API rejects another job for that session because it sees an active `queued` or `processing` job.
- User-facing status becomes confusing: "queued" or "processing" may not reflect reality.

Severity rationale:

This directly matches observed operational confusion around agent processing and queued states.

### C3. Heavy workflow execution bypasses the queue

Evidence:

- `app.main.workflow_ws()` calls `execute_graph()` inside the WebSocket handler.
- `services.node_runner.GraphRunner` calls `run_pipeline()` directly for `workflow/run_pipeline`.
- The classic UI uses `/api/sessions/{id}/process` and `app.agent`, but the node UI executes in the WebSocket lifecycle.

Impact:

- A long stitch job can block a WebSocket task for a long time.
- Browser disconnects and server reloads can interrupt work.
- Workflow jobs do not benefit from queue semantics, job visibility, stale recovery, or retry policy.
- Multiple start nodes can trigger multiple heavy workflows from one WebSocket request.

Severity rationale:

This is a reliability and scalability break between the two main product modes.

### C4. No structured, persistent stage logging for pipeline failures

Evidence:

- `StageLogger` collects in-memory strings.
- `app.agent` uses `print()`.
- `tasks.run_pipeline()` catches broad exceptions and stores only `str(exc)` in `Session.error_message`.
- There is no `processing_events` table or log file per session.

Impact:

- When a 50-image stitch fails, the user cannot reliably see which stage failed after the process exits.
- Debugging depends on terminal output and transient in-memory logs.
- Quality regressions are hard to compare across test sets.

Severity rationale:

For a research tool handling expensive long-running jobs, missing stage-level observability is a production blocker.

## High Findings

### H1. `app.main` is a God module

Evidence:

- `app.main` defines FastAPI app construction, CORS, table creation, template routes, session API, image upload, node upload, WebSocket execution, processing queue API, DZI routes, tile serving, annotations, and downloads.

Impact:

- Hard to test individual route groups.
- Hard to reason about dependencies.
- Small changes to one feature risk unrelated behavior.

### H2. `GraphRunner` is a growing God class

Evidence:

- `services.node_runner.GraphRunner` normalizes links, manages graph state, validates node inputs, creates sessions, copies files, executes math nodes, runs image pipelines, resolves downloads, and emits UI events.

Impact:

- Adding new node libraries will increase coupling.
- Node type validation is ad hoc.
- It is difficult to unit-test nodes independently.

### H3. SQLite polling queue is not robust enough for production workloads

Evidence:

- `database.py` uses SQLite with `check_same_thread=False`.
- The agent claims jobs through a select-then-update pattern without row-level locks.
- There is only one worker loop and no lease or retry.

Impact:

- Concurrent agents can race under heavier load.
- SQLite can become a bottleneck for job state updates and event logs.
- Production scale will require a stronger queue model.

### H4. Security controls are weak

Evidence:

- `allow_origins` defaults to `["*"]`.
- There is no authentication or local access token.
- File upload validation mainly checks count and filename presence.
- The app accepts `image/*` from the browser but does not verify magic bytes server-side.
- Runtime file paths are stored directly in the database.

Impact:

- If exposed beyond localhost, the app can accept cross-origin operations.
- Invalid or malicious files can reach Pillow/OpenCV.
- Storage abuse is possible due to missing upload size controls.

### H5. External CDN dependencies are runtime availability and supply-chain risks

Evidence:

- `workflow.html` imports LiteGraph from unpkg.
- `viewer.html` imports OpenSeadragon from cdnjs.
- `viewer.js` references OpenSeadragon image assets from cdnjs.

Impact:

- The local tool is not fully offline-capable.
- CDN outage or version drift can break UI.
- Production environments may block external scripts.

### H6. Configuration and database initialization have import-time side effects

Evidence:

- `config.py` creates data directories at import time.
- `main.py` and `agent.py` call `Base.metadata.create_all(bind=engine)`.

Impact:

- Importing modules mutates the filesystem.
- Database schema lifecycle is not explicit.
- There is no migration path for schema changes.

### H7. `.gitignore` is duplicated and overly broad

Evidence:

- `data/sessions/` appears multiple times.
- Image patterns such as `*.png`, `*.jpg`, `*.tif`, and `*.tiff` ignore all image files anywhere in the repository.

Impact:

- Legitimate UI assets, screenshots, test fixtures, and documentation images can be accidentally hidden from Git.
- The ignore file is harder to maintain.

### H8. DZI fallback path is not production-safe

Evidence:

- `pyvips` is optional.
- Without pyvips, `deepzoom.py` falls back to Pillow full-image pyramid generation.

Impact:

- Environments without libvips can fail on gigapixel images.
- Users may believe BigTIFF is supported while the deployment lacks the only practical DZI backend.

## Medium Findings

### M1. Feature preview generation reads full images first

Evidence:

- `feature_matching.build_feature_sets()` calls `read_image_bgr(path)`, then `make_preview(image)`.

Impact:

- Feature matching can load every full-resolution source image just to produce a downscaled preview.
- This increases memory pressure for 20 to 50 image runs.

### M2. No automated tests are present

Evidence:

- No test files were found in the repository file list.
- Core functionality depends on manual browser and image-set checks.

Impact:

- Refactors are risky.
- Pipeline quality regressions can slip through.
- API and queue semantics are not protected.

### M3. Broad exception handling hides error taxonomy

Evidence:

- Broad `except Exception` appears in `main.py`, `agent.py`, `tasks.py`, `stitch_pipeline.py`, `global_alignment.py`, `blending.py`, `exporter.py`, and support modules.

Impact:

- User errors, validation errors, memory errors, IO errors, and algorithm failures are all flattened.
- Recovery logic cannot make targeted decisions.

### M4. No database migrations

Evidence:

- Schema is created through `Base.metadata.create_all`.
- No Alembic or migration folder exists.

Impact:

- Adding job leases, event logs, indexes, or constraints will be fragile for existing users.

### M5. API statuses are plain strings without central state machine

Evidence:

- Status values are assigned directly in multiple modules.
- There are no enum types or allowed transition checks.

Impact:

- Invalid transitions are possible.
- UI and backend can drift on status semantics.

### M6. Upload handling is duplicated

Evidence:

- `/api/sessions/{id}/images` and `/api/node/uploads` both sanitize names and copy uploaded files.
- `GraphRunner` copies node upload files into sessions separately.

Impact:

- Validation and storage bugs must be fixed in several places.
- Future metadata tracking will duplicate effort.

### M7. Frontend workflow script is too large

Evidence:

- `workflow.js` contains node definitions, language strings, permissions, graph seeding, upload handling, WebSocket handling, event rendering, keyboard shortcuts, and canvas management.

Impact:

- UI changes are risky.
- Node library evolution is hard to coordinate with backend node execution.

### M8. Download generation can perform expensive work during request handling

Evidence:

- `resolve_optimized_image_path()` can regenerate optimized JPEG from raw if missing.

Impact:

- A download request can trigger expensive image IO and compression.
- HTTP request timeout risk increases.

### M9. No dependency lock or environment reproducibility layer

Evidence:

- `requirements.txt` uses broad lower bounds.
- No lockfile, Dockerfile, or documented native libvips install path is present.

Impact:

- OpenCV/Pillow/tifffile behavior can change across installations.
- Reproducing stitching results is harder.

### M10. No explicit resource budget enforcement beyond pixel count

Evidence:

- `max_source_pixels` checks pixels, not RAM, disk, CPU time, number of output tiles, or concurrent jobs.

Impact:

- A job can pass pixel validation but still exceed memory due to temporary arrays and copies.

## Low Findings

### L1. README route descriptions are partially stale

Evidence:

- README says "Node UI: `/`", while `main.py` comments and routes make `/` the classic UI.

Impact:

- New users can start in the wrong mode.

### L2. `allfiles.txt` appears to be generated project inventory

Evidence:

- `allfiles.txt` is present at repository root.

Impact:

- It can drift and become noise unless intentionally maintained.

### L3. Magic strings are scattered

Evidence:

- Node types, status strings, DZI names, output filenames, and event names are repeated in backend/frontend files.

Impact:

- Typos and drift become more likely as features grow.

### L4. Lack of code formatting/linting policy

Evidence:

- No `pyproject.toml`, Ruff, Black, MyPy, ESLint, or Prettier config was found.

Impact:

- Style and type quality will vary as more contributors join.

## Architectural Smells

| Smell | Location | Severity | Notes |
| --- | --- | --- | --- |
| God module | `app/main.py` | High | Routes, WebSocket, upload, downloads, app setup |
| God class | `services/node_runner.py::GraphRunner` | High | Interpreter, storage, DB, pipeline, event handling |
| Hidden side effects | `app/config.py`, `app/main.py`, `app/agent.py` | High | Directory and DB creation during import/startup |
| Global state | `settings`, SQLAlchemy `engine`, `SessionLocal`, module-level app | Medium | Acceptable for prototype, needs lifecycle boundaries |
| Duplicated logic | Upload handling and filename sanitation | Medium | Present in API and workflow runner |
| Hardcoded values | Node library, type colors, filenames, statuses | Medium | Should move to registries/constants |
| Circular imports | Not currently evident | Low | Current graph is mostly acyclic |
| Dead code | No confirmed dead code yet | Low | Some compatibility paths may be obsolete but need tests before removal |

## Performance and Memory Risks

| Risk | Location | Why it matters |
| --- | --- | --- |
| Full mosaic array | `blend_full_resolution`, `save_stitched_variants` | Peak RAM can exceed raw image size several times |
| Full preview source reads | `build_feature_sets` | Reads full images before downscaling for registration |
| Multiband temporary arrays | `prepare_warped_images`, `multiband_blend` | Holds all warped ROIs and masks for smaller canvases |
| Pillow DZI fallback | `deepzoom._generate_with_pillow` | Converts full source and pyramid levels in memory |
| Optimized download regeneration | `exporter._ensure_optimized_from_raw` | Heavy work during HTTP request |
| Exhaustive pair matching | `pair_candidates` | Up to O(n^2) pairs under exhaustive limit |

## Concurrency Risks

| Risk | Location | Impact |
| --- | --- | --- |
| No job lease | `agent.py` | Stale processing jobs |
| Select-then-update queue claim | `agent.py` | Potential worker race if multiple agents run |
| WebSocket direct pipeline | `main.py`, `node_runner.py` | Request lifecycle tied to long compute |
| SQLite write contention | `database.py` | Limited scaling under multiple workers/events |
| No cancellation model | Pipeline modules | User cannot safely cancel long jobs |

## Security Risks

| Risk | Location | Impact |
| --- | --- | --- |
| CORS wildcard | `config.py`, `main.py` | Unsafe if exposed beyond localhost |
| No auth | Entire API | Anyone with access can upload/process/delete annotations |
| Weak upload validation | `main.py`, `node_runner.py` | Invalid or malicious files may reach image libraries |
| No upload size limit | API layer | Storage and memory abuse |
| CDN scripts | Templates | Supply-chain and offline risk |
| Runtime paths in DB | Models | Requires care when moving storage roots |

## Positive Architecture Notes

- The scans pipeline has already been split into meaningful stages.
- OpenCL is disabled before stitching to avoid observed OpenCL allocation failures.
- EXIF orientation is handled before image processing.
- BigTIFF output exists and uses `tifffile` when available.
- Raw and optimized downloads are separate.
- Tile path serving uses `relative_to` to prevent path traversal.
- Frontend preferences are shared across pages.
- The classic queue flow and processing agent are a good foundation for long-running work once leases and logging are added.


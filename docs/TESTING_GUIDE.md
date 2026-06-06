# Testing Guide

Last updated: 2026-06-06

## Install Test Dependency

```powershell
py -3 -m pip install -r requirements.txt
```

## Run Tests

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
py -3 -m pytest -q
```

`PYTHONDONTWRITEBYTECODE=1` is recommended because this repository currently has tracked `__pycache__` files. It prevents test runs from creating noisy bytecode diffs.

## Current Test Coverage

The initial test suite covers:

- `JobService` enqueue, claim, finish, and fail behavior.
- Shared exception hierarchy and error context.
- Download filename sanitation.
- JSON log formatter output.

## Next Tests To Add

- FastAPI route tests with `TestClient`.
- Upload validation tests.
- Agent stale-job recovery tests after heartbeat fields are added.
- Synthetic stitching pipeline smoke tests.
- DZI generation tests for pyvips and low-resolution Pillow fallback.
- Workflow graph execution tests with a fake node graph and mocked pipeline.


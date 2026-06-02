# Gigapixel Heritage Viewer

Local web app for gigapixel heritage image stitching, Deep Zoom tiling, annotation, and downloadable output packages.

## Key Features
- Node-style workflow UI (`/`, `/workflow`)
- Real-time bi-directional control via WebSocket
- Multiple independent Start nodes
- Type-colored links (`flow`, `session`, `upload_ref`, `string`, `int`, `float`, `url`)
- Function library nodes
- Dual downloads: raw high-resolution + optimized version
- Classic UI (`/classic`)
- Queue-based background processing agent (`/api/sessions/{id}/process` + `app.agent`)

## Install
If `pip` is not found, use the Python launcher:

```bash
py -3 -m pip install -r requirements.txt
```

## Run API
```bash
py -3 -m uvicorn app.main:app --reload
```

## Run Agent (separate terminal)
```bash
py -3 -m app.agent
```
git status
git add .
git commit -m "Initial commit"
git push -u origin main

## URLs
- Node UI: `http://127.0.0.1:8000/`
- Node UI (explicit): `http://127.0.0.1:8000/workflow`
- Classic UI: `http://127.0.0.1:8000/classic`
- Viewer: `http://127.0.0.1:8000/viewer/{session_id}`
- Raw download: `/api/sessions/{session_id}/download/raw`
- Optimized download: `/api/sessions/{session_id}/download/optimized`

## How To View The Agent Window
1. Run API server in terminal A.
2. Open terminal B and run `py -3 -m app.agent`.
3. Watch `[agent] ...` logs in terminal B.

PowerShell helpers:

```powershell
.\run_api.ps1
.\run_agent.ps1
.\open_agent_window.ps1
```

## Large Image Pixel Limit
- Pillow decompression-bomb default is disabled in code.
- Effective limit is `MAX_SOURCE_PIXELS` (default: `10_000_000_000`).
- Optimized JPEG quality is `OPTIMIZED_JPEG_QUALITY` (default: `85`).
- You can override in `.env`:

```env
MAX_SOURCE_PIXELS=15000000000
OPTIMIZED_JPEG_QUALITY=85
```

## Project Layout
```text
gigapixel-heritage-viewer/
  app/
    main.py
    agent.py
    models.py
    schemas.py
    services/
      node_runner.py
      exporter.py
      tasks.py
  data/
  requirements.txt
```

##  본고는  문화체육관광부 및 한국콘텐츠진흥원(KOCCA)의 2024년도 문화체육관광연구개발사업으로 수행되었음(과제명: 복합소재 문화유산 고품질 복원을 위한 디지털 문화유산 획득용 광학기술 및 공유 플랫폼 기술 개발, 과제번호: RS-2024-00442410)


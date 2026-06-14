$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Use the project venv if present, otherwise fall back to the system launcher.
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) { $py = $venvPy } else { $py = "py" }

Write-Host "Hyper Gigapixel Agent" -ForegroundColor Cyan
Write-Host "  API + embedded processing worker start together in this one process." -ForegroundColor DarkGray
Write-Host "  App      : http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  API docs : http://127.0.0.1:8000/docs"
Write-Host "  Health   : http://127.0.0.1:8000/api/health  (worker_alive should be true)"
Write-Host ""

& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

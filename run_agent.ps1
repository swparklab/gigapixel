$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# NOTE: The API server (run_api.ps1) now starts an embedded worker by default,
# so you normally do NOT need this. Run this only if you want a dedicated or
# additional worker process (e.g. set EMBEDDED_AGENT=false and scale workers).
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) { $py = $venvPy } else { $py = "py" }

& $py -m app.agent

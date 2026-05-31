$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

py -3 -m app.agent

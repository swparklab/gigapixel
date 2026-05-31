$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$cmd = "Set-Location '$PSScriptRoot'; py -3 -m app.agent"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd

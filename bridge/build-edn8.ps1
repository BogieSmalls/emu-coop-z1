# Compatibility wrapper for the old EDN8 builder name.
#
# Usage: powershell -ExecutionPolicy Bypass -File .\build-edn8.ps1

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "build-hardware.ps1"
& powershell -ExecutionPolicy Bypass -File $script @args
exit $LASTEXITCODE

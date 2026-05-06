# Builds the bridge as a single Windows .exe via PyInstaller.
# Usage: powershell -ExecutionPolicy Bypass -File .\build-windows.ps1

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# Ensure dev/dist deps are installed in the uv-managed env
uv sync --extra test --extra dist

# Run PyInstaller
uv run pyinstaller bridge.spec --clean --noconfirm

$exe = Join-Path $PSScriptRoot "dist\bridge.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Built: $exe ($size MB)"
} else {
    Write-Error "Build failed - bridge.exe not found"
    exit 1
}

Pop-Location

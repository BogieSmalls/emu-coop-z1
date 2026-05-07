# Builds the EDN8 bridge as a single Windows .exe via PyInstaller, then renames
# it to a versioned, audience-tagged filename for distribution.
# Usage: powershell -ExecutionPolicy Bypass -File .\build-windows.ps1

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# Read the release version from ../version.lua; format e.g. "2.0 beta1" -> "2.0-beta1"
$versionLua = Join-Path $PSScriptRoot "..\version.lua"
$versionLine = Select-String -Path $versionLua -Pattern '^\s*release\s*=\s*"([^"]+)"' -List
if (-not $versionLine) {
    Write-Error "Could not find release version in $versionLua"
    exit 1
}
$rawVersion = $versionLine.Matches[0].Groups[1].Value
$version = $rawVersion -replace '\s+', '-'

# Ensure dev/dist deps are installed in the uv-managed env
uv sync --extra test --extra dist

# Run PyInstaller (spec produces dist\bridge.exe by default)
uv run pyinstaller bridge.spec --clean --noconfirm

$built = Join-Path $PSScriptRoot "dist\bridge.exe"
if (-not (Test-Path $built)) {
    Write-Error "Build failed - dist\bridge.exe not found"
    exit 1
}

# Rename to a versioned, audience-tagged filename
$dist = Join-Path $PSScriptRoot "dist"
$finalName = "emu-coop-plus-$version-edn8.exe"
$finalPath = Join-Path $dist $finalName
if (Test-Path $finalPath) { Remove-Item -Force $finalPath }
Move-Item -Path $built -Destination $finalPath

$size = [math]::Round((Get-Item $finalPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Built: $finalPath ($size MB)"

Pop-Location

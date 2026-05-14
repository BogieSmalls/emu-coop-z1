# Builds the hardware bridge as a single Windows .exe via PyInstaller and lands
# the artifact in the centralized dist/hardware/ tree at the repo root.
#
# The hardware bridge currently supports EDN8 and MiSTer endpoints.
#
# Usage: powershell -ExecutionPolicy Bypass -File .\build-hardware.ps1
#
# Output: ..\dist\hardware\z1rr-coop-<version>-hardware.exe

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

# Read the release version from version.lua; format e.g. "2.0 beta5" -> "2.0-beta5"
$versionLua = Join-Path $repoRoot "version.lua"
$versionLine = Select-String -Path $versionLua -Pattern '^\s*release\s*=\s*"([^"]+)"' -List
if (-not $versionLine) {
    Write-Error "Could not find release version in $versionLua"
    exit 1
}
$rawVersion = $versionLine.Matches[0].Groups[1].Value
$version = $rawVersion -replace '\s+', '-'

# Ensure dev/dist deps are installed in the uv-managed env
uv sync --extra test --extra dist

# Run PyInstaller (spec produces dist\bridge.exe inside bridge/ by default)
uv run pyinstaller bridge.spec --clean --noconfirm

$built = Join-Path $PSScriptRoot "dist\bridge.exe"
if (-not (Test-Path $built)) {
    Write-Error "Build failed - dist\bridge.exe not found"
    exit 1
}

# Copy into the centralized dist/hardware/ tree at the repo root while leaving
# bridge\dist\bridge.exe available for quick local GUI testing.
$endpointDist = Join-Path $repoRoot "dist\hardware"
New-Item -ItemType Directory -Path $endpointDist -Force | Out-Null
$finalName = "z1rr-coop-$version-hardware.exe"
$finalPath = Join-Path $endpointDist $finalName
if (Test-Path $finalPath) { Remove-Item -Force $finalPath }
Copy-Item -Path $built -Destination $finalPath

$size = [math]::Round((Get-Item $finalPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Built: $finalPath ($size MB)"

Pop-Location

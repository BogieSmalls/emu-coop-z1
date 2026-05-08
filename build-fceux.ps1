# Builds a zip distribution of the FCEUX endpoint.
#
# Includes only the FCEUX-relevant files: top-level Lua scripts, the IUP DLLs
# for the connection dialog, and the modes/, pl/, socket/, vendor/ directories.
# Excludes the bridge/ (Python hardware client), relay/ (server), docs/, tests/,
# and dist/ that aren't needed by FCEUX players.
#
# Usage: powershell -ExecutionPolicy Bypass -File .\build-fceux.ps1
#
# Output: dist\emu\emu-coop-plus-<version>-fceux.zip

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# Read the version from version.lua. Format: release = "2.0 beta1" -> "2.0-beta1"
$versionLine = Select-String -Path "version.lua" -Pattern '^\s*release\s*=\s*"([^"]+)"' -List
if (-not $versionLine) {
    Write-Error "Could not find release version in version.lua"
    exit 1
}
$rawVersion = $versionLine.Matches[0].Groups[1].Value
$version = $rawVersion -replace '\s+', '-'   # "2.0 beta1" -> "2.0-beta1"

$packageName = "emu-coop-plus-$version-fceux"
$endpointDist = Join-Path $PSScriptRoot "dist\emu"
New-Item -ItemType Directory -Path $endpointDist -Force | Out-Null
$staging = Join-Path $endpointDist $packageName
$zipPath = Join-Path $endpointDist "$packageName.zip"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
New-Item -ItemType Directory -Path $staging | Out-Null

# Top-level files FCEUX users need
$rootFiles = @(
    "coop.lua",
    "debug.lua",
    "dialog.lua",
    "driver.lua",
    "pipe.lua",
    "pipe_direct.lua",
    "pipe_relay.lua",
    "socket.lua",
    "util.lua",
    "version.lua",
    "iup.dll",
    "iuplua.dll",
    "README.md"
)
foreach ($f in $rootFiles) {
    if (Test-Path $f) {
        Copy-Item $f $staging
    } else {
        Write-Warning "Missing expected file: $f"
    }
}

# Directories users need (Lua modules + modes)
$dirs = @("modes", "pl", "socket", "vendor")
foreach ($d in $dirs) {
    if (Test-Path $d) {
        Copy-Item -Recurse $d $staging
    } else {
        Write-Warning "Missing expected directory: $d"
    }
}

# Strip .bak files and any test scaffolding that might have been pulled in
Get-ChildItem -Path $staging -Recurse -Include "*.bak" | Remove-Item -Force

# Compress
Compress-Archive -Path "$staging\*" -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $staging

$size = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
Write-Host ""
Write-Host "Built: $zipPath ($size KB)"

Pop-Location

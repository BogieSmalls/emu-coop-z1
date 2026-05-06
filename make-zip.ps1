# Builds an emu-coop distribution ZIP for end users (FCEUX side only).
# Excludes the relay/ daemon, tests/, design docs, and dev artifacts.
# Usage: powershell -ExecutionPolicy Bypass -File .\make-zip.ps1

$ErrorActionPreference = "Stop"

# Read the version from version.lua so the zip filename matches the release
$versionFile = Get-Content "$PSScriptRoot\version.lua" -Raw
if ($versionFile -match 'release\s*=\s*"([^"]+)"') {
    $version = $matches[1]
} else {
    Write-Error "Could not find release version in version.lua"
    exit 1
}

$distDir = Join-Path $PSScriptRoot "dist"
$zipName = "emu-coop-$version.zip"
$zipPath = Join-Path $distDir $zipName

if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}

# Items shipped to end users
$include = @(
    "coop.lua",
    "debug.lua",
    "dialog.lua",
    "driver.lua",
    "pipe.lua",
    "pipe_direct.lua",
    "pipe_relay.lua",
    "util.lua",
    "version.lua",
    "socket.lua",
    "iup.dll",
    "iuplua.dll",
    "README.md",
    "MODDING.md",
    "modes",
    "pl",
    "socket",
    "vendor"
)

$missing = $include | Where-Object { -not (Test-Path (Join-Path $PSScriptRoot $_)) }
if ($missing) {
    Write-Error "Missing files: $($missing -join ', ')"
    exit 1
}

if (Test-Path $zipPath) {
    Remove-Item $zipPath
}

Push-Location $PSScriptRoot
try {
    Compress-Archive -Path $include -DestinationPath $zipPath -CompressionLevel Optimal
} finally {
    Pop-Location
}

$size = (Get-Item $zipPath).Length / 1KB
Write-Host ""
Write-Host "Built: $zipPath ($([math]::Round($size, 1)) KB)"
Write-Host ""
Write-Host "Contents (top-level):"
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $archive.Entries |
        ForEach-Object { ($_.FullName -split "[\\/]")[0] } |
        Sort-Object -Unique |
        ForEach-Object { Write-Host "  $_" }
} finally {
    $archive.Dispose()
}

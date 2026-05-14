# Builds zip distributions of the FCEUX endpoint.
#
# Includes only the FCEUX-relevant files: top-level Lua scripts, the IUP DLLs
# for the connection dialog, and the modes/, pl/, socket/, vendor/ directories.
# Excludes the bridge/ (Python hardware client), relay/ (server), docs/, tests/,
# and dist/ that aren't needed by FCEUX players.
#
# Native Lua modules must match the FCEUX process bitness. The repo currently
# vendors win32 DLLs at the root. A win64 package is emitted only if matching
# native DLLs are present under native\fceux-win64\.
#
# Usage: powershell -ExecutionPolicy Bypass -File .\build-fceux.ps1
#
# Output:
#   dist\emu\z1rr-coop-<version>-fceux-win32.zip
#   dist\emu\z1rr-coop-<version>-fceux-win64.zip (when win64 DLLs exist)
# Package name pattern: z1rr-coop-$version-fceux-win32 / z1rr-coop-$version-fceux-win64

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

$packageBaseName = "z1rr-coop-$version-fceux"
$endpointDist = Join-Path $PSScriptRoot "dist\emu"
$stagingRoot = Join-Path $endpointDist ".staging"
New-Item -ItemType Directory -Path $endpointDist -Force | Out-Null
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

# Remove the older architecture-ambiguous artifact name so a rebuild does not
# leave users with a stale zip that looks current.
$legacyZipPath = Join-Path $endpointDist "$packageBaseName.zip"
if (Test-Path $legacyZipPath) { Remove-Item -Force $legacyZipPath }

# Top-level files FCEUX users need
$rootFiles = @(
    "coop.lua",
    "coop_config.lua",
    "debug.lua",
    "dialog.lua",
    "driver.lua",
    "pipe.lua",
    "pipe_direct.lua",
    "pipe_relay.lua",
    "socket.lua",
    "util.lua",
    "version.lua",
    "README.md"
)

# Directories users need (Lua modules + modes)
$dirs = @("modes", "pl", "socket", "vendor")

$nativeFiles = @(
    "iup.dll",
    "iuplua.dll",
    "socket\core.dll"
)

$targets = @(
    @{
        arch = "win32"
        nativeRoot = $PSScriptRoot
        required = $true
    },
    @{
        arch = "win64"
        nativeRoot = Join-Path $PSScriptRoot "native\fceux-win64"
        required = $false
    }
)

function Test-NativeFiles($nativeRoot) {
    foreach ($file in $nativeFiles) {
        if (-not (Test-Path (Join-Path $nativeRoot $file))) {
            return $false
        }
    }
    return $true
}

function Copy-NativeFiles($nativeRoot, $staging) {
    foreach ($file in $nativeFiles) {
        $src = Join-Path $nativeRoot $file
        $dest = Join-Path $staging $file
        $destDir = Split-Path $dest -Parent
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item $src $dest -Force
    }
}

foreach ($target in $targets) {
    $arch = $target.arch
    $nativeRoot = $target.nativeRoot
    $packageName = "$packageBaseName-$arch"
    $staging = Join-Path $stagingRoot $packageName
    $zipPath = Join-Path $endpointDist "$packageName.zip"
    $hasNativeFiles = Test-NativeFiles $nativeRoot

    if (-not $hasNativeFiles) {
        if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
        if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
        $message = "Skipping FCEUX $arch package; missing native DLLs under $nativeRoot"
        if ($target.required) {
            Write-Error $message
            exit 1
        }
        Write-Warning $message
        continue
    }

    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    New-Item -ItemType Directory -Path $staging | Out-Null

    foreach ($f in $rootFiles) {
        if (Test-Path $f) {
            Copy-Item $f $staging
        } else {
            Write-Warning "Missing expected file: $f"
        }
    }

    foreach ($d in $dirs) {
        if (Test-Path $d) {
            Copy-Item -Recurse $d $staging
        } else {
            Write-Warning "Missing expected directory: $d"
        }
    }

    Copy-NativeFiles $nativeRoot $staging

    # Strip .bak files and any test scaffolding that might have been pulled in
    Get-ChildItem -Path $staging -Recurse -Include "*.bak" | Remove-Item -Force

    # Compress
    Compress-Archive -Path "$staging\*" -DestinationPath $zipPath -CompressionLevel Optimal
    Remove-Item -Recurse -Force $staging

    $size = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
    Write-Host ""
    Write-Host "Built: $zipPath ($size KB)"
}

Pop-Location

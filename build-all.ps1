# Builds every distributable endpoint artifact for the current release.
#
# Each endpoint has its own builder script and lands its output in a per-endpoint
# subdirectory under dist/ at the repo root, so we can keep adding endpoints
# (MiSTer, Bizhawk, Mesen, etc.) without disturbing the shared layout:
#
#   dist/edn8/emu-coop-plus-<version>-edn8.exe
#   dist/fceux/emu-coop-plus-<version>-fceux.zip
#   dist/<future-endpoint>/...
#
# Usage: powershell -ExecutionPolicy Bypass -File .\build-all.ps1

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# List of endpoint builders. Each entry: (label, script-path-relative-to-repo-root).
$endpoints = @(
    @{ label = "EDN8";  script = "bridge\build-edn8.ps1" },
    @{ label = "FCEUX"; script = "build-fceux.ps1" }
)

$results = @()
foreach ($ep in $endpoints) {
    Write-Host ""
    Write-Host "==> Building $($ep.label) endpoint..."
    Write-Host ""
    $script = Join-Path $PSScriptRoot $ep.script
    if (-not (Test-Path $script)) {
        Write-Warning "Skipping $($ep.label): builder not found at $script"
        $results += @{ label = $ep.label; status = "missing"; path = $script }
        continue
    }
    & powershell -ExecutionPolicy Bypass -File $script
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "$($ep.label) builder exited with code $LASTEXITCODE"
        $results += @{ label = $ep.label; status = "failed"; path = $script }
        continue
    }
    $results += @{ label = $ep.label; status = "ok"; path = $script }
}

# Final summary listing every artifact under dist/<endpoint>/
Write-Host ""
Write-Host "==> Build summary"
Write-Host ""
$dist = Join-Path $PSScriptRoot "dist"
if (Test-Path $dist) {
    Get-ChildItem -Path $dist -Directory | ForEach-Object {
        $endpoint = $_.Name
        Write-Host "  dist\$endpoint\"
        Get-ChildItem -Path $_.FullName -File | ForEach-Object {
            $sizeMB = [math]::Round($_.Length / 1MB, 2)
            $sizeKB = [math]::Round($_.Length / 1KB, 1)
            $size = if ($_.Length -ge 1MB) { "$sizeMB MB" } else { "$sizeKB KB" }
            Write-Host "    $($_.Name)  ($size)"
        }
    }
}

$failures = @($results | Where-Object { $_.status -ne "ok" })
if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Failures:" -ForegroundColor Yellow
    $failures | ForEach-Object {
        Write-Host "  $($_.label): $($_.status) ($($_.path))" -ForegroundColor Yellow
    }
    Pop-Location
    exit 1
}

Pop-Location

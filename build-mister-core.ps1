# Builds the emu-coop MiSTer NES core with Quartus and copies the .rbf into
# the bridge payload folder under a non-stock core name.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\build-mister-core.ps1
#   powershell -ExecutionPolicy Bypass -File .\build-mister-core.ps1 -QuartusBin C:\intelFPGA_lite\17.0\quartus\bin64

param(
    [string]$QuartusBin = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$coreDir = Join-Path $repoRoot "mister/cores/NES_emu-coop"
$builtRbf = Join-Path $coreDir "output_files\NES.rbf"
$payloadRbf = Join-Path $repoRoot "bridge\bridge_core\mister_payload\NES_emu-coop.rbf"

function Find-QuartusSh {
    param([string]$BinPath)

    if ($BinPath) {
        $candidate = Join-Path $BinPath "quartus_sh.exe"
        if (Test-Path $candidate) { return $candidate }
        throw "quartus_sh.exe was not found in $BinPath"
    }

    $fromPath = Get-Command quartus_sh -ErrorAction SilentlyContinue
    if ($fromPath) { return $fromPath.Source }

    $knownBins = @(
        "C:\intelFPGA_lite\17.0\quartus\bin64",
        "C:\intelFPGA\17.0\quartus\bin64"
    )
    foreach ($knownBin in $knownBins) {
        $candidate = Join-Path $knownBin "quartus_sh.exe"
        if (Test-Path $candidate) { return $candidate }
    }

    throw "Quartus 17.0 quartus_sh.exe was not found. Add quartus\bin64 to PATH or pass -QuartusBin."
}

if (-not (Test-Path (Join-Path $coreDir "NES.qpf"))) {
    throw "MiSTer NES Quartus project not found at $coreDir"
}

$quartusSh = Find-QuartusSh -BinPath $QuartusBin
Write-Host "Using Quartus: $quartusSh"
Write-Host "Building MiSTer core: $coreDir"

Push-Location $coreDir
try {
    & $quartusSh --flow compile NES
    if ($LASTEXITCODE -ne 0) {
        throw "quartus_sh --flow compile NES failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $builtRbf)) {
    throw "Build completed but expected output was not found: $builtRbf"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $payloadRbf) -Force | Out-Null
Copy-Item -LiteralPath $builtRbf -Destination $payloadRbf -Force

$size = [math]::Round((Get-Item $payloadRbf).Length / 1MB, 1)
Write-Host ""
Write-Host "Built: $payloadRbf ($size MB)"
Write-Host "Next: cd bridge; uv run python -m bridge_cli mister-deploy --host <MISTER_IP>"

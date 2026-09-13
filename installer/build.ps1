<#
.SYNOPSIS
    Builds the GClaude Indexer installer.

.DESCRIPTION
    The version is read from `SYSTEM_VERSION` in `gclaude_indexer/web/app.py`
    and handed to the compiler. It is never written here: two copies of a
    version number drift, and this project has already paid for that class
    of mistake more than once.

    The compiler is looked for in three places, not two. winget installs
    Inno Setup into `%LOCALAPPDATA%\Programs` when it cannot elevate, which
    is what happened on the machine this was written on — a build script
    that only knew about Program Files would have reported "Inno Setup not
    found" on a machine that had it.

.PARAMETER OutputDir
    Where the .exe lands. Defaults to `dist/` beside the repository root.
#>
param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\dist")
)

$ErrorActionPreference = "Stop"

$appPy = Join-Path $PSScriptRoot "..\gclaude_indexer\web\app.py"
if (-not (Test-Path $appPy)) {
    throw "Could not find $appPy — run this from the repository."
}

$match = Select-String -Path $appPy -Pattern '^SYSTEM_VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1
if (-not $match) {
    throw "SYSTEM_VERSION not found in $appPy"
}
$version = $match.Matches[0].Groups[1].Value

$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw ("Inno Setup 6 not found. Install it with: " +
           "winget install --id JRSoftware.InnoSetup --exact")
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Version : $version"   -ForegroundColor Cyan
Write-Host "Compiler: $iscc"      -ForegroundColor Cyan
Write-Host "Output  : $OutputDir" -ForegroundColor Cyan

& $iscc "/DAppVersion=$version" "/O$OutputDir" (Join-Path $PSScriptRoot "GClaudeIndexer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE"
}

$built = Join-Path $OutputDir "GClaude-Indexer-Setup-$version.exe"
if (-not (Test-Path $built)) {
    throw "The compiler reported success but $built is not there."
}

$size = [math]::Round((Get-Item $built).Length / 1MB, 1)
Write-Host "Built $built ($size MB)" -ForegroundColor Green

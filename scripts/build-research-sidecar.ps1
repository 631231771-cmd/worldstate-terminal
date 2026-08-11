param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ServiceRoot = Join-Path $RepoRoot "services\research-api"
$Python = Join-Path $ServiceRoot ".venv\Scripts\python.exe"
$WorkRoot = Join-Path $ServiceRoot ".sidecar-build"
$DistRoot = Join-Path $ServiceRoot ".sidecar-dist"
$BinRoot = Join-Path $RepoRoot "apps\desktop-tauri\src-tauri\bin"
$TargetName = "worldstate-research-api-x86_64-pc-windows-msvc.exe"
$TargetRoot = Join-Path $BinRoot "worldstate-research-api"
$TargetPath = Join-Path $TargetRoot $TargetName

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Research API virtual environment is missing: $Python"
}

foreach ($path in @($WorkRoot, $DistRoot)) {
    $resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $path))
    if (-not $resolvedParent.StartsWith($ServiceRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a sidecar path outside the Research API directory: $path"
    }
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
if (Test-Path -LiteralPath $TargetRoot) {
    $resolvedTarget = [System.IO.Path]::GetFullPath($TargetRoot)
    if (-not $resolvedTarget.StartsWith($BinRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a sidecar target outside the Tauri bin directory: $TargetRoot"
    }
    Remove-Item -LiteralPath $TargetRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $WorkRoot, $DistRoot, $BinRoot, $TargetRoot | Out-Null

$addAlembic = "$(Join-Path $ServiceRoot 'alembic.ini');."
$addMigrations = "$(Join-Path $ServiceRoot 'migrations');migrations"
$entryPoint = Join-Path $ServiceRoot "src\worldstate\sidecar.py"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name worldstate-research-api `
    --paths (Join-Path $ServiceRoot "src") `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    --specpath $WorkRoot `
    --add-data $addAlembic `
    --add-data $addMigrations `
    --collect-all alembic `
    --collect-all uvicorn `
    --hidden-import aiosqlite `
    --hidden-import sqlalchemy.dialects.sqlite.aiosqlite `
    --hidden-import worldstate.main `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan.on `
    $entryPoint
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$builtRoot = Join-Path $DistRoot "worldstate-research-api"
$built = Join-Path $builtRoot "worldstate-research-api.exe"
if (-not (Test-Path -LiteralPath $built)) { throw "Sidecar artifact was not produced: $built" }
Copy-Item -Path (Join-Path $builtRoot "*") -Destination $TargetRoot -Recurse -Force
Move-Item -LiteralPath (Join-Path $TargetRoot "worldstate-research-api.exe") -Destination $TargetPath -Force

if (-not $SkipSmoke) {
    $SmokeRoot = Join-Path $env:TEMP "worldstate-sidecar-smoke"
    New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
    $DatabasePath = Join-Path $SmokeRoot "worldstate.db"
    if (Test-Path -LiteralPath $DatabasePath) { Remove-Item -LiteralPath $DatabasePath -Force }
    $env:WORLDSTATE_DATABASE_URL = "sqlite+aiosqlite:///$($DatabasePath.Replace('\', '/'))"
    $env:WORLDSTATE_ROOT = $RepoRoot
    & $TargetPath migrate
    if ($LASTEXITCODE -ne 0) { throw "Frozen sidecar migration smoke failed" }
    $Process = Start-Process -FilePath $TargetPath -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "8765") -PassThru -WindowStyle Hidden
    try {
        $Healthy = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Milliseconds 500
            try {
                $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/v2/health" -TimeoutSec 2
                if ($Health.product -eq "worldstate-terminal" -and $Health.api_version -eq "v2") {
                    $Healthy = $true
                    break
                }
            } catch { }
        }
        if (-not $Healthy) { throw "Frozen sidecar did not pass /v2/health smoke" }
    } finally {
        if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
    }
}

$Artifact = Get-Item -LiteralPath $TargetPath
[pscustomobject]@{
    status = "ok"
    artifact = $Artifact.FullName
    bytes = $Artifact.Length
    smoke = -not $SkipSmoke
} | ConvertTo-Json

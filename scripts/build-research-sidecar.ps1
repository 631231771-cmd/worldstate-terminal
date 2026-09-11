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
    # Smoke from a clean, repo-independent install directory.  This catches
    # accidental imports/resources from the source checkout and keeps the
    # database in a writable runtime directory rather than beside the EXE.
    $SmokeRoot = Join-Path $env:TEMP "worldstate-sidecar-smoke-v07"
    $SmokeInstall = Join-Path $SmokeRoot "install"
    $SmokeWorking = Join-Path $SmokeRoot "working"
    $smokeParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $SmokeRoot))
    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP)
    if (-not $smokeParent.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a smoke path outside TEMP: $SmokeRoot"
    }
    if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $SmokeInstall, $SmokeWorking | Out-Null
    Copy-Item -Path (Join-Path $builtRoot "*") -Destination $SmokeInstall -Recurse -Force
    $SmokeExe = Join-Path $SmokeInstall "worldstate-research-api.exe"
    $DatabasePath = Join-Path $SmokeRoot "worldstate.db"
    $env:WORLDSTATE_DATABASE_URL = "sqlite+aiosqlite:///$($DatabasePath.Replace('\', '/'))"
    Remove-Item Env:WORLDSTATE_ROOT -ErrorAction SilentlyContinue
    & $SmokeExe migrate
    if ($LASTEXITCODE -ne 0) { throw "Frozen sidecar migration smoke failed" }
    $Process = Start-Process -FilePath $SmokeExe -WorkingDirectory $SmokeWorking -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "8765") -PassThru -WindowStyle Hidden
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
        foreach ($method in @("POST", "PATCH", "DELETE")) {
            $preflight = Invoke-WebRequest -UseBasicParsing -Method Options `
                -Uri "http://127.0.0.1:8765/v2/watchlist" -TimeoutSec 5 `
                -Headers @{Origin = "http://tauri.localhost"; "Access-Control-Request-Method" = $method}
            if ($preflight.StatusCode -ne 200 -or $preflight.Headers["Access-Control-Allow-Origin"] -ne "http://tauri.localhost") {
                throw "Frozen sidecar rejected the Windows desktop $method origin"
            }
        }
        foreach ($endpoint in @("today", "markets", "macro", "events")) {
            $bodyPath = Join-Path $SmokeRoot "$endpoint.json"
            $statusCode = (& curl.exe --silent --show-error --max-time 5 --output $bodyPath --write-out "%{http_code}" "http://127.0.0.1:8765/v2/product/$endpoint").Trim()
            if ($statusCode -ne "200") {
                $body = if (Test-Path -LiteralPath $bodyPath) { Get-Content -LiteralPath $bodyPath -Raw } else { "" }
                throw "Frozen sidecar product smoke failed: $endpoint ($statusCode) $body"
            }
        }
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

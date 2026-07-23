param(
    [ValidateSet("start", "stop", "restart", "status", "sync", "doctor", "logs")]
    [string]$Command = "start",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArguments
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $RepoRoot ".runtime"
$LogRoot = Join-Path $RuntimeRoot "logs"
$ServiceRoot = Join-Path $RepoRoot "services\macro-engine"
$ServicePython = Join-Path $ServiceRoot ".venv\Scripts\python.exe"
$ConfigPath = Join-Path $RuntimeRoot "worldstate.env"
$DatabasePath = Join-Path $RuntimeRoot "worldstate.db"
$FrontendUrl = "http://127.0.0.1:4173/?lang=zh"
$EngineHealthUrl = "http://127.0.0.1:8000/v1/health"

function Write-WorldState {
    param([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray)
    Write-Host "[WorldState] $Message" -ForegroundColor $Color
}

function Ensure-RuntimeDirectories {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot, $LogRoot | Out-Null
}

function Get-ToolPath {
    param([string]$Name)
    $tool = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $tool) { return $null }
    return $tool.Source
}

function Ensure-LocalConfig {
    Ensure-RuntimeDirectories
    if (Test-Path -LiteralPath $ConfigPath) { return }
    $databaseUrl = "sqlite+aiosqlite:///$($DatabasePath.Replace('\', '/'))"
    $content = @(
        "# World State Terminal local configuration"
        "# Add your FRED key after FRED_API_KEY=, then run: WorldState.bat sync"
        "MACRO_ENGINE_URL=http://127.0.0.1:8000"
        "MACRO_DATABASE_URL=$databaseUrl"
        "MACRO_DEFAULT_LOCALE=zh-CN"
        "MACRO_DEFAULT_TIMEZONE=Asia/Taipei"
        "MACRO_STRICT_POINT_IN_TIME=true"
        "MACRO_ENABLE_WRITES=false"
        "MACRO_STALE_AFTER_HOURS=72"
        "FRED_API_KEY="
    )
    Set-Content -LiteralPath $ConfigPath -Value $content -Encoding UTF8
    Write-WorldState "Created local configuration: .runtime\worldstate.env" Green
}

function Import-LocalConfig {
    Ensure-LocalConfig
    foreach ($line in Get-Content -LiteralPath $ConfigPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

function Ensure-Dependencies {
    $python = Get-ToolPath "python"
    if (-not $python) {
        throw "Python is required. Install Python 3.12 or newer, then run WorldState.bat again."
    }
    $node = Get-ToolPath "node"
    $npm = Get-ToolPath "npm"
    if (-not $node -or -not $npm) {
        throw "Node.js and npm are required. Install Node.js 22 or newer, then run WorldState.bat again."
    }

    & $python -m uv --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-WorldState "Installing the local Python environment manager..." Yellow
        & $python -m pip install --user "uv==0.11.31"
        if ($LASTEXITCODE -ne 0) { throw "Unable to install uv." }
    }

    Write-WorldState "Checking Macro Engine dependencies..."
    & $python -m uv sync --locked --project $ServiceRoot
    if ($LASTEXITCODE -ne 0) { throw "Macro Engine dependency installation failed." }

    $viteEntry = Join-Path $RepoRoot "node_modules\vite\bin\vite.js"
    if (-not (Test-Path -LiteralPath $viteEntry)) {
        Write-WorldState "Installing dashboard dependencies..." Yellow
        Push-Location $RepoRoot
        try {
            & $npm ci --ignore-scripts --prefer-offline
            if ($LASTEXITCODE -ne 0) { throw "Dashboard dependency installation failed." }
        }
        finally {
            Pop-Location
        }
    }
}

function Invoke-Migration {
    Write-WorldState "Applying local database migrations..."
    & $ServicePython -m macro_engine.cli migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
}

function Get-PidPath {
    param([string]$Name)
    return Join-Path $RuntimeRoot "$Name.pid"
}

function Get-ManagedProcess {
    param([string]$Name)
    $pidPath = Get-PidPath $Name
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $savedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        return $null
    }
    $marker = switch ($Name) {
        "engine" { "macro_engine.cli serve" }
        "frontend" { "vite.js" }
        "sync" { "macro_engine.cli sync" }
        default { "" }
    }
    if (-not $process.CommandLine -or
        $process.CommandLine.IndexOf($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        ($marker -and $process.CommandLine.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -lt 0)) {
        Write-WorldState "Ignoring stale $Name PID; it does not belong to this checkout." Yellow
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        return $null
    }
    return $process
}

function Stop-ManagedProcess {
    param([string]$Name)
    $rootProcess = Get-ManagedProcess $Name
    if ($null -eq $rootProcess) { return }
    $allProcesses = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.List[int]]::new()
    function Add-Descendants {
        param([int]$ParentId)
        foreach ($child in $allProcesses | Where-Object { $_.ParentProcessId -eq $ParentId }) {
            Add-Descendants -ParentId $child.ProcessId
        }
        $ids.Add($ParentId)
    }
    Add-Descendants -ParentId $rootProcess.ProcessId
    foreach ($processId in $ids) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Get-PidPath $Name) -Force -ErrorAction SilentlyContinue
    Write-WorldState "Stopped $Name." Green
}

function Wait-ForEndpoint {
    param([string]$Url, [int]$TimeoutSeconds = 45)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Start-WorldState {
    Ensure-RuntimeDirectories
    Import-LocalConfig
    Ensure-Dependencies
    Invoke-Migration

    $engine = Get-ManagedProcess "engine"
    if ($null -eq $engine) {
        $engineOut = Join-Path $LogRoot "engine.out.log"
        $engineError = Join-Path $LogRoot "engine.error.log"
        $engineProcess = Start-Process `
            -FilePath $ServicePython `
            -ArgumentList @("-m", "macro_engine.cli", "serve", "--host", "127.0.0.1", "--port", "8000") `
            -WorkingDirectory $ServiceRoot `
            -RedirectStandardOutput $engineOut `
            -RedirectStandardError $engineError `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath (Get-PidPath "engine") -Value $engineProcess.Id -Encoding ASCII
        Write-WorldState "Macro Engine started (PID $($engineProcess.Id))." Green
    }
    else {
        Write-WorldState "Macro Engine is already running (PID $($engine.ProcessId))."
    }

    $frontend = Get-ManagedProcess "frontend"
    if ($null -eq $frontend) {
        $node = Get-ToolPath "node"
        $viteEntry = Join-Path $RepoRoot "node_modules\vite\bin\vite.js"
        $env:VITE_VARIANT = "macro"
        $env:VITE_MACRO_ENGINE_URL = "http://127.0.0.1:8000"
        $frontendOut = Join-Path $LogRoot "frontend.out.log"
        $frontendError = Join-Path $LogRoot "frontend.error.log"
        $frontendProcess = Start-Process `
            -FilePath $node `
            -ArgumentList @($viteEntry, "--host", "127.0.0.1", "--port", "4173") `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $frontendOut `
            -RedirectStandardError $frontendError `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath (Get-PidPath "frontend") -Value $frontendProcess.Id -Encoding ASCII
        Write-WorldState "Dashboard started (PID $($frontendProcess.Id))." Green
    }
    else {
        Write-WorldState "Dashboard is already running (PID $($frontend.ProcessId))."
    }

    if (-not (Wait-ForEndpoint -Url $EngineHealthUrl)) {
        throw "Macro Engine did not become ready. See .runtime\logs\engine.error.log."
    }
    if (-not (Wait-ForEndpoint -Url $FrontendUrl)) {
        throw "Dashboard did not become ready. See .runtime\logs\frontend.error.log."
    }

    if ($null -eq (Get-ManagedProcess "sync")) {
        $syncOut = Join-Path $LogRoot "sync.out.log"
        $syncError = Join-Path $LogRoot "sync.error.log"
        $syncProcess = Start-Process `
            -FilePath $ServicePython `
            -ArgumentList @("-m", "macro_engine.cli", "sync", "--all", "--recent-days", "3650") `
            -WorkingDirectory $ServiceRoot `
            -RedirectStandardOutput $syncOut `
            -RedirectStandardError $syncError `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath (Get-PidPath "sync") -Value $syncProcess.Id -Encoding ASCII
        Write-WorldState "Background data initialization started (PID $($syncProcess.Id))."
    }

    Write-WorldState "Ready: $FrontendUrl" Cyan
    Start-Process $FrontendUrl
}

function Stop-WorldState {
    Stop-ManagedProcess "sync"
    Stop-ManagedProcess "frontend"
    Stop-ManagedProcess "engine"
}

function Show-Status {
    $engine = Get-ManagedProcess "engine"
    $frontend = Get-ManagedProcess "frontend"
    $sync = Get-ManagedProcess "sync"
    Write-WorldState "Macro Engine: $(if ($engine) { "RUNNING (PID $($engine.ProcessId))" } else { "STOPPED" })"
    Write-WorldState "Dashboard:    $(if ($frontend) { "RUNNING (PID $($frontend.ProcessId))" } else { "STOPPED" })"
    Write-WorldState "Sync:         $(if ($sync) { "RUNNING (PID $($sync.ProcessId))" } else { "IDLE" })"
    if ($engine) {
        try {
            $health = Invoke-RestMethod -Uri $EngineHealthUrl -TimeoutSec 3
            Write-WorldState "Database:     $($health.database.status)"
            Write-WorldState "Methodology:  $($health.methodology_version)"
        }
        catch {
            Write-WorldState "Health probe failed." Yellow
        }
    }
}

function Invoke-ManualSync {
    Import-LocalConfig
    Ensure-Dependencies
    Invoke-Migration
    $arguments = @("-m", "macro_engine.cli", "sync", "--all")
    if ($ExtraArguments.Count -gt 0) {
        if ($ExtraArguments[0] -eq "--series" -and $ExtraArguments.Count -gt 1) {
            $arguments = @("-m", "macro_engine.cli", "sync", "--series", $ExtraArguments[1])
        }
    }
    Write-WorldState "Synchronizing macro data..."
    & $ServicePython @arguments
    if ($LASTEXITCODE -ne 0) { throw "Synchronization failed." }
}

function Invoke-Doctor {
    Ensure-RuntimeDirectories
    $checks = @(
        @("Python", (Get-ToolPath "python")),
        @("Node.js", (Get-ToolPath "node")),
        @("npm", (Get-ToolPath "npm")),
        @("Local config", $(if (Test-Path -LiteralPath $ConfigPath) { $ConfigPath } else { "will be created on start" })),
        @("SQLite database", $(if (Test-Path -LiteralPath $DatabasePath) { $DatabasePath } else { "will be created on start" }))
    )
    foreach ($check in $checks) {
        $ok = [bool]$check[1]
        Write-Host ("{0,-18} {1}" -f $check[0], $(if ($ok) { $check[1] } else { "MISSING" })) `
            -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
    }
    Show-Status
}

function Show-Logs {
    Ensure-RuntimeDirectories
    $files = @(
        "engine.out.log",
        "engine.error.log",
        "frontend.out.log",
        "frontend.error.log",
        "sync.out.log",
        "sync.error.log"
    )
    foreach ($name in $files) {
        $path = Join-Path $LogRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        Write-Host "`n=== $name ===" -ForegroundColor Cyan
        Get-Content -LiteralPath $path -Tail 60
    }
}

try {
    switch ($Command) {
        "start" { Start-WorldState }
        "stop" { Stop-WorldState }
        "restart" {
            Stop-WorldState
            Start-WorldState
        }
        "status" { Show-Status }
        "sync" { Invoke-ManualSync }
        "doctor" { Invoke-Doctor }
        "logs" { Show-Logs }
    }
    exit 0
}
catch {
    Write-WorldState $_.Exception.Message Red
    exit 1
}

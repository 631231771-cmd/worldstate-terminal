param(
    [ValidateSet("launch", "start", "stop", "restart", "status", "doctor", "logs", "migrate", "bootstrap", "build", "data-doctor", "sync-official", "sync-calendar", "snapshot-consensus", "estimate-backfill", "backfill", "sync-market", "reconcile-data", "data-status")]
    [string]$Command = "start",
    [switch]$NoBrowser,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $RepoRoot ".runtime"
$LogRoot = Join-Path $RuntimeRoot "logs"
$ServiceRoot = Join-Path $RepoRoot "services\research-api"
$ServicePython = Join-Path $ServiceRoot ".venv\Scripts\python.exe"
$UiRoot = Join-Path $RepoRoot "apps\terminal-ui"
$ConfigPath = Join-Path $RuntimeRoot "worldstate.env"
$DatabasePath = Join-Path $RuntimeRoot "worldstate.db"
$UiUrl = "http://127.0.0.1:4173/#today"
$ApiHealthUrl = "http://127.0.0.1:8000/v2/health"
$ApiPort = 8000
$UiPort = 4173
$DesktopReleaseExe = Join-Path $RepoRoot "apps\desktop-tauri\src-tauri\target\release\worldstate-terminal.exe"
$DesktopDebugExe = Join-Path $RepoRoot "apps\desktop-tauri\src-tauri\target\debug\worldstate-terminal.exe"
$DesktopLogRoot = Join-Path $env:LOCALAPPDATA "research.worldstate.terminal\logs"

function Write-WorldState {
    param([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray)
    Write-Host "[WorldState] $Message" -ForegroundColor $Color
}

function Ensure-Runtime {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot, $LogRoot | Out-Null
}

function Get-ToolPath {
    param([string]$Name)
    $tool = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $tool) { return $null }
    return $tool.Source
}

function Get-PortListener {
    param([int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" `
        -ErrorAction SilentlyContinue
}

function Get-DesktopProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'worldstate-terminal.exe'" `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            $_.ExecutablePath.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)
        } |
        Select-Object -First 1
}

function Test-ProcessTreeReferencesRepo {
    param($Process)
    $current = $Process
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    while ($null -ne $current -and $visited.Add([int]$current.ProcessId)) {
        $identity = "$($current.ExecutablePath) $($current.CommandLine)"
        if ($identity.IndexOf($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
        if (-not $current.ParentProcessId) { break }
        $current = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($current.ParentProcessId)" -ErrorAction SilentlyContinue
    }
    return $false
}

function Get-WorldStateHealth {
    try {
        $health = Invoke-RestMethod -Uri $ApiHealthUrl -TimeoutSec 3
        if ($health.service -eq "worldstate-research-api" -and $health.api_version -eq "v2") {
            return $health
        }
    }
    catch {}
    return $null
}

function Ensure-Config {
    Ensure-Runtime
    $databaseUrl = "sqlite+aiosqlite:///$($DatabasePath.Replace('\', '/'))"
    $defaults = @(
        "# WorldState Macro Research Terminal local configuration"
        "WORLDSTATE_DATABASE_URL=$databaseUrl"
        "WORLDSTATE_API_URL=http://127.0.0.1:8000"
        "WORLDSTATE_DEFAULT_LOCALE=zh-CN"
        "WORLDSTATE_DEFAULT_TIMEZONE=Asia/Shanghai"
        "WORLDSTATE_STRICT_POINT_IN_TIME=true"
        "WORLDSTATE_DATA_START_DATE=2015-01-01"
        "WORLDSTATE_MARKET_INTRADAY_PRE_MINUTES=90"
        "WORLDSTATE_MARKET_INTRADAY_POST_MINUTES=240"
        "WORLDSTATE_MARKET_DAILY_PRE_DAYS=5"
        "WORLDSTATE_MARKET_DAILY_POST_DAYS=5"
        "WORLDSTATE_DATABENTO_MAX_ESTIMATED_COST_USD=0"
        "WORLDSTATE_ALLOW_PAID_DOWNLOAD=false"
        "WORLDSTATE_DEMO_MODE=false"
        "WORLDSTATE_SCHEDULER_ENABLED=true"
        "WORLDSTATE_AI_PROVIDER=auto"
        "WORLDSTATE_AI_MODEL=gpt-5.6-sol"
        "WORLDSTATE_AI_BASE_URL=https://api.openai.com/v1"
        "OPENAI_API_KEY="
        "OLLAMA_BASE_URL="
        "WORLDSTATE_OLLAMA_MODEL=qwen3:8b"
        "FRED_API_KEY="
        "BLS_API_KEY="
        "TRADING_ECONOMICS_API_KEY="
        "WORLDSTATE_TRADING_ECONOMICS_PIT_ENTITLED=false"
        "DATABENTO_API_KEY="
    )
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Set-Content -LiteralPath $ConfigPath -Value $defaults -Encoding UTF8
        Write-WorldState "Created local configuration: .runtime\worldstate.env" Green
        return
    }
    $existing = @(Get-Content -LiteralPath $ConfigPath)
    $knownKeys = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($line in $existing) {
        $trimmed = $line.Trim()
        if ($trimmed -and -not $trimmed.StartsWith("#") -and $trimmed.Contains("=")) {
            [void]$knownKeys.Add($trimmed.Split("=", 2)[0].Trim())
        }
    }
    $missing = @(
        $defaults | Where-Object {
            $_ -and -not $_.StartsWith("#") -and
            -not $knownKeys.Contains($_.Split("=", 2)[0].Trim())
        }
    )
    if ($missing.Count -gt 0) {
        Add-Content -LiteralPath $ConfigPath -Value @("", "# v0.5 data foundation", $missing) `
            -Encoding UTF8
        Write-WorldState "Added missing v0.5 settings to local configuration." Green
    }
}

function Import-Config {
    Ensure-Config
    foreach ($line in Get-Content -LiteralPath $ConfigPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

function Ensure-Dependencies {
    $python = Get-ToolPath "python"
    $npm = Get-ToolPath "npm"
    if (-not $python) { throw "Python 3.12 is required. Install it, then open WorldStateApp.bat again." }
    if (-not $npm) { throw "Node.js 20 or newer is required. Install it, then open WorldStateApp.bat again." }

    & $python -m uv --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-WorldState "Preparing the Python environment manager..." Yellow
        & $python -m pip install --user "uv>=0.11,<0.12"
        if ($LASTEXITCODE -ne 0) { throw "Python environment manager installation failed." }
    }
    if (-not (Test-Path -LiteralPath $ServicePython)) {
        Write-WorldState "First launch: installing Research API dependencies..." Yellow
        & $python -m uv sync --locked --all-groups --project $ServiceRoot
        if ($LASTEXITCODE -ne 0) { throw "Research API dependency installation failed." }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $UiRoot "node_modules\vite\bin\vite.js"))) {
        Write-WorldState "First launch: installing Terminal UI dependencies..." Yellow
        & $npm install --ignore-scripts --prefix $UiRoot
        if ($LASTEXITCODE -ne 0) { throw "Terminal UI dependency installation failed." }
    }
}

function Invoke-Migration {
    Import-Config
    Ensure-Dependencies
    Write-WorldState "Checking database v3..." Cyan
    Push-Location $ServiceRoot
    try {
        & $ServicePython -m worldstate.cli migrate
        if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
    }
    finally { Pop-Location }
}

function Invoke-DataCommand {
    Invoke-Migration
    Push-Location $ServiceRoot
    try {
        & $ServicePython -m worldstate.cli $Command @CommandArgs
        $dataExitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
    if ($dataExitCode -ne 0) {
        Write-WorldState "Data command '$Command' did not complete (exit $dataExitCode)." Yellow
        exit $dataExitCode
    }
}

function Get-PidPath {
    param([string]$Name)
    Join-Path $RuntimeRoot "$Name.pid"
}

function Get-ManagedProcess {
    param([string]$Name)
    $pidPath = Get-PidPath $Name
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $savedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
    if ($null -eq $process -or -not $process.CommandLine -or
        $process.CommandLine.IndexOf($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        return $null
    }
    return $process
}

function Stop-ManagedProcess {
    param([string]$Name)
    $process = Get-ManagedProcess $Name
    if ($null -eq $process) { return }
    $all = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.List[int]]::new()
    function Add-Tree {
        param([int]$ParentId)
        foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $ParentId }) {
            Add-Tree -ParentId $child.ProcessId
        }
        $ids.Add($ParentId)
    }
    Add-Tree -ParentId $process.ProcessId
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
        catch { Start-Sleep -Milliseconds 500 }
    }
    return $false
}

function Start-WorldState {
    $desktop = Get-DesktopProcess
    if ($null -ne $desktop) {
        Write-WorldState "Desktop application is already running (PID $($desktop.ProcessId))." Green
        Show-Status
        return
    }

    Invoke-Migration
    $api = Get-ManagedProcess "research-api"
    if ($null -eq $api) {
        $apiListener = Get-PortListener $ApiPort
        if ($null -ne $apiListener) {
            $health = Get-WorldStateHealth
            if ($null -ne $health -and (Test-ProcessTreeReferencesRepo $apiListener)) {
                Set-Content -LiteralPath (Get-PidPath "research-api") `
                    -Value $apiListener.ProcessId -Encoding ASCII
                $api = $apiListener
                Write-WorldState "Adopted the existing WorldState Research API (PID $($api.ProcessId))." Yellow
            }
            else {
                throw "Port $ApiPort is already used by another program (PID $($apiListener.ProcessId), $($apiListener.Name))."
            }
        }
    }
    if ($null -eq $api) {
        $apiProcess = Start-Process -FilePath $ServicePython `
            -ArgumentList @("-m", "worldstate.cli", "serve", "--host", "127.0.0.1", "--port", "8000") `
            -WorkingDirectory $ServiceRoot `
            -RedirectStandardOutput (Join-Path $LogRoot "research-api.out.log") `
            -RedirectStandardError (Join-Path $LogRoot "research-api.error.log") `
            -WindowStyle Hidden -PassThru
        Set-Content -LiteralPath (Get-PidPath "research-api") -Value $apiProcess.Id -Encoding ASCII
        Write-WorldState "Research API started." Green
    }
    $ui = Get-ManagedProcess "terminal-ui"
    if ($null -eq $ui) {
        $uiListener = Get-PortListener $UiPort
        if ($null -ne $uiListener) {
            if (Test-ProcessTreeReferencesRepo $uiListener) {
                Set-Content -LiteralPath (Get-PidPath "terminal-ui") `
                    -Value $uiListener.ProcessId -Encoding ASCII
                $ui = $uiListener
                Write-WorldState "Adopted the existing WorldState Terminal UI (PID $($ui.ProcessId))." Yellow
            }
            else {
                throw "Port $UiPort is already used by another program (PID $($uiListener.ProcessId), $($uiListener.Name))."
            }
        }
    }
    if ($null -eq $ui) {
        $node = Get-ToolPath "node"
        $vite = Join-Path $UiRoot "node_modules\vite\bin\vite.js"
        $uiProcess = Start-Process -FilePath $node `
            -ArgumentList @($vite, "--host", "127.0.0.1", "--port", "4173", "--strictPort") `
            -WorkingDirectory $UiRoot `
            -RedirectStandardOutput (Join-Path $LogRoot "terminal-ui.out.log") `
            -RedirectStandardError (Join-Path $LogRoot "terminal-ui.error.log") `
            -WindowStyle Hidden -PassThru
        Set-Content -LiteralPath (Get-PidPath "terminal-ui") -Value $uiProcess.Id -Encoding ASCII
        Write-WorldState "Terminal UI started." Green
    }
    if (-not (Wait-ForEndpoint $ApiHealthUrl)) {
        throw "Research API did not become ready. See .runtime\logs\research-api.error.log."
    }
    if (-not (Wait-ForEndpoint $UiUrl)) {
        throw "Terminal UI did not become ready. See .runtime\logs\terminal-ui.error.log."
    }
    Write-WorldState "WorldState is ready: $UiUrl" Cyan
    if (-not $NoBrowser) { Start-Process $UiUrl }
}

function Start-WorldStateApp {
    $desktop = Get-DesktopProcess
    if ($null -ne $desktop) {
        Write-WorldState "Desktop application is already running (PID $($desktop.ProcessId))." Green
        Show-Status
        return
    }
    $desktopExe = if (Test-Path -LiteralPath $DesktopReleaseExe) {
        $DesktopReleaseExe
    }
    elseif (Test-Path -LiteralPath $DesktopDebugExe) {
        $DesktopDebugExe
    }
    else {
        $null
    }
    if ($null -eq $desktopExe) {
        Write-WorldState "No Tauri build is available; starting the verified BAT application." Yellow
        Start-WorldState
        return
    }
    $process = Start-Process -FilePath $desktopExe -WorkingDirectory $RepoRoot -PassThru
    Start-Sleep -Milliseconds 1200
    if ($process.HasExited) {
        Write-WorldState "The Tauri application exited during startup; using the BAT application." Yellow
        Start-WorldState
        return
    }
    Write-WorldState "Desktop application started (PID $($process.Id))." Green
    if (-not (Wait-ForEndpoint $ApiHealthUrl)) {
        throw "The desktop application is open, but its Research API did not become ready. See $DesktopLogRoot."
    }
    Show-Status
}

function Stop-WorldState {
    Stop-ManagedProcess "terminal-ui"
    Stop-ManagedProcess "research-api"
}

function Show-Status {
    $api = Get-ManagedProcess "research-api"
    $ui = Get-ManagedProcess "terminal-ui"
    $desktop = Get-DesktopProcess
    $apiListener = Get-PortListener $ApiPort
    $uiListener = Get-PortListener $UiPort
    $health = Get-WorldStateHealth

    if ($null -ne $api) {
        Write-WorldState "Research API: RUNNING (managed PID $($api.ProcessId), port $ApiPort)"
    }
    elseif ($null -ne $apiListener -and $null -ne $health) {
        Write-WorldState "Research API: RUNNING (desktop/external PID $($apiListener.ProcessId), port $ApiPort)"
    }
    elseif ($null -ne $apiListener) {
        Write-WorldState "Research API: FOREIGN LISTENER (PID $($apiListener.ProcessId), port $ApiPort)" Yellow
    }
    else {
        Write-WorldState "Research API: STOPPED (port $ApiPort)"
    }

    if ($null -ne $desktop) {
        Write-WorldState "Terminal UI:  RUNNING (Tauri PID $($desktop.ProcessId), embedded UI)"
    }
    elseif ($null -ne $ui) {
        Write-WorldState "Terminal UI:  RUNNING (managed PID $($ui.ProcessId), port $UiPort)"
    }
    elseif ($null -ne $uiListener) {
        Write-WorldState "Terminal UI:  UNMANAGED LISTENER (PID $($uiListener.ProcessId), port $UiPort)" Yellow
    }
    else {
        Write-WorldState "Terminal UI:  STOPPED (port $UiPort)"
    }

    Write-WorldState "BAT logs: $LogRoot"
    Write-WorldState "Desktop logs: $DesktopLogRoot"
    if ($null -ne $health) {
        Write-WorldState "Database: $($health.database.status) - Method: $($health.methodology_version)"
    }
    elseif ($null -ne $apiListener) {
        Write-WorldState "Health check did not identify WorldState Research API v2." Yellow
    }
}

switch ($Command) {
    "launch" { Start-WorldStateApp }
    "start" { Start-WorldState }
    "stop" { Stop-WorldState }
    "restart" { Stop-WorldState; Start-WorldState }
    "status" { Ensure-Runtime; Show-Status }
    "migrate" { Invoke-Migration }
    "bootstrap" {
        Invoke-Migration
        Push-Location $ServiceRoot
        try { & $ServicePython -m worldstate.cli bootstrap }
        finally { Pop-Location }
    }
    "build" {
        Import-Config
        Ensure-Dependencies
        & (Get-ToolPath "npm") run build --prefix $UiRoot
        if ($LASTEXITCODE -ne 0) { throw "Terminal UI build failed." }
    }
    "logs" { Ensure-Runtime; Start-Process explorer.exe $LogRoot }
    "doctor" {
        Import-Config
        Write-WorldState "Repository: $RepoRoot"
        Write-WorldState "Python: $(Get-ToolPath 'python')"
        Write-WorldState "Node: $(Get-ToolPath 'node')"
        Write-WorldState "Database: $DatabasePath"
        Write-WorldState "Research API files: $(Test-Path (Join-Path $ServiceRoot 'pyproject.toml'))"
        Write-WorldState "Terminal UI files: $(Test-Path (Join-Path $UiRoot 'package.json'))"
        Show-Status
    }
    { $_ -in @(
        "data-doctor",
        "sync-official",
        "sync-calendar",
        "snapshot-consensus",
        "estimate-backfill",
        "backfill",
        "sync-market",
        "reconcile-data",
        "data-status"
    ) } { Invoke-DataCommand }
}

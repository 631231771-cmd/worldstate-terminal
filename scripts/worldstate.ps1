param(
    [ValidateSet("start", "stop", "restart", "status", "doctor", "logs", "migrate", "bootstrap", "build")]
    [string]$Command = "start",
    [switch]$NoBrowser
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

function Ensure-Config {
    Ensure-Runtime
    if (Test-Path -LiteralPath $ConfigPath) { return }
    $databaseUrl = "sqlite+aiosqlite:///$($DatabasePath.Replace('\', '/'))"
    $lines = @(
        "# WorldState Macro Research Terminal local configuration"
        "WORLDSTATE_DATABASE_URL=$databaseUrl"
        "WORLDSTATE_API_URL=http://127.0.0.1:8000"
        "WORLDSTATE_DEFAULT_LOCALE=zh-CN"
        "WORLDSTATE_DEFAULT_TIMEZONE=Asia/Shanghai"
        "WORLDSTATE_STRICT_POINT_IN_TIME=true"
        "WORLDSTATE_AI_PROVIDER=auto"
        "WORLDSTATE_AI_MODEL=gpt-5.6-sol"
        "WORLDSTATE_AI_BASE_URL=https://api.openai.com/v1"
        "OPENAI_API_KEY="
        "OLLAMA_BASE_URL="
        "WORLDSTATE_OLLAMA_MODEL=qwen3:8b"
        "FRED_API_KEY="
    )
    Set-Content -LiteralPath $ConfigPath -Value $lines -Encoding UTF8
    Write-WorldState "Created local configuration: .runtime\worldstate.env" Green
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
    Invoke-Migration
    $api = Get-ManagedProcess "research-api"
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

function Stop-WorldState {
    Stop-ManagedProcess "terminal-ui"
    Stop-ManagedProcess "research-api"
}

function Show-Status {
    $api = Get-ManagedProcess "research-api"
    $ui = Get-ManagedProcess "terminal-ui"
    Write-WorldState "Research API: $(if ($api) { "RUNNING (PID $($api.ProcessId))" } else { "STOPPED" })"
    Write-WorldState "Terminal UI:  $(if ($ui) { "RUNNING (PID $($ui.ProcessId))" } else { "STOPPED" })"
    if ($api) {
        try {
            $health = Invoke-RestMethod -Uri $ApiHealthUrl -TimeoutSec 3
            Write-WorldState "Database: $($health.database.status) - Method: $($health.methodology_version)"
        }
        catch { Write-WorldState "Health check did not respond." Yellow }
    }
}

switch ($Command) {
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
}

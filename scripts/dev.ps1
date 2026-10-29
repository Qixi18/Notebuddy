$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir = Join-Path $repo 'apps\backend'
$frontendDir = Join-Path $repo 'apps\web'
$backendUrl = 'http://localhost:8000'
$frontendUrl = 'http://localhost:5173'
$startupTimeoutSeconds = 45
$backendReloadArgs = @()
if ([Environment]::GetEnvironmentVariable('NOTEBOOK_RELOAD') -eq '1') {
    $backendReloadArgs = @('--reload')
}
$startupTimeoutRaw = [Environment]::GetEnvironmentVariable('NOTEBOOK_STARTUP_TIMEOUT_SECONDS')
if ($startupTimeoutRaw) {
    $configuredTimeout = 0
    if (-not [int]::TryParse($startupTimeoutRaw, [ref] $configuredTimeout) -or $configuredTimeout -lt 1) {
        throw 'NOTEBOOK_STARTUP_TIMEOUT_SECONDS must be a positive integer.'
    }
    $startupTimeoutSeconds = $configuredTimeout
}
$backendPython = Join-Path $backendDir '.venv-document\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    $backendPython = Join-Path $backendDir '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw 'Backend Python environment is missing. Install the backend dependencies before starting NoteBuddy.'
}

Get-Command npm -ErrorAction Stop | Out-Null

function Assert-PortFree([int] $port) {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try {
        $probe.Start()
    } catch [System.Net.Sockets.SocketException] {
        $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 })
        $ownerText = if ($owners.Count) { $owners -join ', ' } else { 'unknown process' }
        throw "Port $port is already in use ($ownerText). Stop the owning service before starting NoteBuddy."
    } finally {
        $probe.Stop()
    }
}

function Stop-ProcessTree([int] $processId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree ([int] $child.ProcessId)
    }
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

function Stop-NoteBuddyProcesses {
    $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($repo) -and $_.Name -in @('python.exe', 'node.exe', 'cmd.exe')
    })
    foreach ($process in $running) {
        Stop-ProcessTree ([int] $process.ProcessId)
    }
}

Assert-PortFree 8000
Assert-PortFree 5173

if (Test-Path (Join-Path $repo '.env')) {
    Write-Host 'Found local .env configuration.'
} else {
    Write-Host 'No .env found. The backend will use safe local defaults; copy .env.example to enable DeepSeek or Embedding.'
}

$logDir = Join-Path $repo 'data\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$workerStdout = Join-Path $logDir 'material-worker.stdout.log'
$workerStderr = Join-Path $logDir 'material-worker.stderr.log'
$backendStdout = Join-Path $logDir 'backend.stdout.log'
$backendStderr = Join-Path $logDir 'backend.stderr.log'

function Get-LogTail([string] $path, [int] $count = 40) {
    if (Test-Path -LiteralPath $path) {
        return (Get-Content -LiteralPath $path -Tail $count -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    return '<no output captured>'
}

function Get-BackendDiagnostics {
    $stdout = Get-LogTail $backendStdout
    $stderr = Get-LogTail $backendStderr
    return "Backend stdout:`n$stdout`nBackend stderr:`n$stderr"
}

$backendProcess = $null
$workerProcess = $null
try {
    Write-Host "Using backend Python: $backendPython"
    Write-Host 'Checking database migrations and starting material worker ...'
    Push-Location $backendDir
    try {
        & $backendPython -c 'from app.db.migrate import migrate_database; migrate_database()'
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; services were not started.' }
    } finally {
        Pop-Location
    }
    $workerProcess = Start-Process `
        -FilePath $backendPython `
        -ArgumentList @('-u', '-m', 'app.workers.runner') `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $workerStdout `
        -RedirectStandardError $workerStderr `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "Starting NoteBuddy backend on $backendUrl ..."
    $backendProcess = Start-Process `
        -FilePath $backendPython `
        -ArgumentList (@('-u', '-m', 'uvicorn', 'app.main:app') + $backendReloadArgs + @('--host', '127.0.0.1', '--port', '8000')) `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $backendStdout `
        -RedirectStandardError $backendStderr `
        -WindowStyle Hidden `
        -PassThru

    $healthUrls = @(
        "$backendUrl/api/v1/health",
        'http://127.0.0.1:8000/api/v1/health'
    )
    $healthTimeout = (Get-Date).AddSeconds($startupTimeoutSeconds)
    $healthy = $false
    while ((Get-Date) -lt $healthTimeout) {
        foreach ($healthUrl in $healthUrls) {
            $healthRequest = @{ Uri = $healthUrl; TimeoutSec = 2 }
            if ((Get-Command Invoke-RestMethod).Parameters.ContainsKey('NoProxy')) {
                $healthRequest.NoProxy = $true
            }
            try {
                $health = Invoke-RestMethod @healthRequest
                if ($health.status -eq 'ok') {
                    $healthy = $true
                    break
                }
            } catch {
                if ($backendProcess.HasExited) {
                    $diagnostics = Get-BackendDiagnostics
                    throw "Backend process exited with code $($backendProcess.ExitCode) before becoming healthy.`n$diagnostics"
                }
            }
        }
        if ($healthy) { break }
        if ($workerProcess.HasExited) {
            Write-Warning "Material worker exited with code $($workerProcess.ExitCode). Worker stderr:`n$(Get-LogTail $workerStderr)"
            $workerProcess = $null
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy) {
        $diagnostics = Get-BackendDiagnostics
        throw "Backend did not become healthy within $startupTimeoutSeconds seconds. Backend process exited: $($backendProcess.HasExited).`n$diagnostics"
    }

    Write-Host "Backend is healthy: $backendUrl/api/v1/health"
    Write-Host "Starting NoteBuddy frontend on $frontendUrl ..."
    Push-Location $frontendDir
    try {
        npm run dev -- --host 127.0.0.1
    } finally {
        Pop-Location
    }
} finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-ProcessTree $backendProcess.Id
        Write-Host 'Backend process stopped.'
    }
    if ($workerProcess -and -not $workerProcess.HasExited) {
        Stop-ProcessTree $workerProcess.Id
        Write-Host 'Material worker stopped.'
    }
    Stop-NoteBuddyProcesses
}

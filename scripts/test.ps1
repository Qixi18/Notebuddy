[CmdletBinding()]
param([switch] $RealOcr, [switch] $Check)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backend = Join-Path $repo 'apps\backend'
$runtime = Join-Path $repo '.runtime'
$logDir = Join-Path $runtime 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir ('test-{0}-{1}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID)
$env:npm_config_cache = Join-Path $runtime 'cache\npm'
$env:ELECTRON_CACHE = Join-Path $runtime 'cache\electron'
$env:ELECTRON_BUILDER_CACHE = Join-Path $runtime 'cache\electron-builder'
if ($RealOcr) { $env:NOTEBOOK_RUN_REAL_OCR = '1' }

function Invoke-CheckStep([string] $Name, [string] $Command, [string[]] $CommandArguments, [string] $Directory) {
    Write-Host $Name
    Add-Content -LiteralPath $log -Value $Name
    Push-Location $Directory
    try {
        $global:LASTEXITCODE = 0
        & $Command @CommandArguments 2>&1 | Tee-Object -FilePath $log -Append | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE). See $log" }
    } finally { Pop-Location }
}
try {
    $python = Join-Path $backend '.venv-document\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $backend '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $python)) { throw 'Backend environment is missing. Run scripts/setup.ps1 first.' }
    $node = Join-Path $runtime 'node\node.exe'
    if (-not (Test-Path -LiteralPath $node)) {
        $installedNode = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $installedNode) { throw 'Node.js is missing. Run scripts/setup.ps1 first.' }
        $node = $installedNode.Source
    }
    $nodeDir = Split-Path -Parent $node
    $npmCli = Join-Path $nodeDir 'node_modules\npm\bin\npm-cli.js'
    if (-not (Test-Path -LiteralPath $npmCli)) { throw 'npm is missing from the selected Node installation. Run scripts/setup.ps1 first.' }
    $env:Path = "$nodeDir;$env:Path"
    $nodeVersion = & $node --version
    if ($LASTEXITCODE -ne 0 -or [version] ([string] $nodeVersion).Trim().TrimStart('v') -lt [version] '22.12.0') { throw 'Node.js 22.12 or newer is required. Run scripts/setup.ps1 with a supported Node installation.' }
    Write-Host "Using backend Python: $python"
    Write-Host "Using Node.js: $node"
    Invoke-CheckStep 'Checking backend test dependencies' $python @('-c', 'import pytest, ruff') $backend
    if ($Check) { Write-Host 'Test dependencies are ready; no tests or builds were started.'; exit 0 }
    Invoke-CheckStep 'Backend lint' $python @('-m', 'ruff', 'check', 'app', 'tests') $backend
    Invoke-CheckStep 'Backend tests' $python @('-m', 'pytest') $backend
    Invoke-CheckStep 'Web behavior tests' $node @($npmCli, 'test') (Join-Path $repo 'apps\web')
    Invoke-CheckStep 'Web production build' $node @($npmCli, 'run', 'build') (Join-Path $repo 'apps\web')
    Invoke-CheckStep 'Desktop main-process build' $node @($npmCli, 'run', 'build:main') (Join-Path $repo 'apps\desktop')
    Write-Host "Checks completed. Log: $log"
} catch {
    Write-Error "$($_.Exception.Message) If dependencies are missing, run scripts/setup.ps1." -ErrorAction Continue
    exit 1
}

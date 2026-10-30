[CmdletBinding()]
param(
    [string] $UvPath,
    [string] $NodeDirectory,
    [string] $PythonVersion = '3.12',
    [switch] $SkipWeb,
    [switch] $SkipDesktop
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $repo '.runtime'
$backend = Join-Path $repo 'apps\backend'
foreach ($folder in @('bin', 'node', 'python', 'logs', 'cache\uv', 'cache\npm', 'cache\electron', 'cache\electron-builder')) {
    New-Item -ItemType Directory -Path (Join-Path $runtime $folder) -Force | Out-Null
}
$log = Join-Path $runtime ('logs\setup-{0}-{1}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID)
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
$env:UV_PYTHON_BIN_DIR = Join-Path $runtime 'bin'
$env:UV_CACHE_DIR = Join-Path $runtime 'cache\uv'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $backend '.venv-document'
$env:npm_config_cache = Join-Path $runtime 'cache\npm'
$env:ELECTRON_CACHE = Join-Path $runtime 'cache\electron'
$env:ELECTRON_BUILDER_CACHE = Join-Path $runtime 'cache\electron-builder'

function Write-SetupLog([string] $Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Message
    Add-Content -LiteralPath $log -Value $line
    Write-Host $line
}
function Invoke-SetupStep([string] $Name, [string] $Command, [string[]] $CommandArguments, [string] $Directory = $repo, [switch] $Capture) {
    Write-SetupLog $Name
    Push-Location $Directory
    try {
        $global:LASTEXITCODE = 0
        $output = @(& $Command @CommandArguments 2>&1)
        $code = $LASTEXITCODE
        foreach ($line in $output) { Write-SetupLog ([string] $line) }
        if ($code -ne 0) { throw "$Name failed (exit $code). See $log" }
        if ($Capture) { return $output }
    } finally { Pop-Location }
}

try {
    $localUv = Join-Path $runtime 'bin\uv.exe'
    if ($UvPath) {
        $uv = (Resolve-Path -LiteralPath $UvPath).Path
        if ([IO.Path]::GetExtension($uv) -eq '.exe' -and $uv -ne $localUv) {
            Copy-Item -LiteralPath $uv -Destination $localUv
            $uv = $localUv
        }
    } elseif (Test-Path -LiteralPath $localUv) { $uv = $localUv }
    else {
        $installedUv = Get-Command uv.exe -ErrorAction SilentlyContinue
        if (-not $installedUv) { throw 'uv is missing. Install uv or supply -UvPath <uv.exe>, then rerun scripts/setup.ps1.' }
        Copy-Item -LiteralPath $installedUv.Source -Destination $localUv
        $uv = $localUv
    }
    $localNodeDir = Join-Path $runtime 'node'
    $localNode = Join-Path $localNodeDir 'node.exe'
    $localNpm = Join-Path $localNodeDir 'node_modules\npm\bin\npm-cli.js'
    if ($NodeDirectory) { $sourceNodeDir = (Resolve-Path -LiteralPath $NodeDirectory).Path }
    elseif ((Test-Path -LiteralPath $localNode) -and (Test-Path -LiteralPath $localNpm)) { $sourceNodeDir = $localNodeDir }
    else {
        $installedNode = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $installedNode) { throw 'Node.js 22.12+ with npm is missing. Supply -NodeDirectory <Node installation folder>, then rerun scripts/setup.ps1.' }
        $sourceNodeDir = Split-Path -Parent $installedNode.Source
    }
    if (-not (Test-Path -LiteralPath (Join-Path $sourceNodeDir 'node.exe')) -or -not (Test-Path -LiteralPath (Join-Path $sourceNodeDir 'node_modules\npm\bin\npm-cli.js'))) {
        throw 'The Node installation is incomplete: node.exe and node_modules/npm are required.'
    }
    if ($sourceNodeDir -ne $localNodeDir) {
        Write-SetupLog "Copying the existing Node distribution into $localNodeDir"
        foreach ($name in @('node.exe', 'npm', 'npm.cmd', 'npm.ps1', 'npx', 'npx.cmd', 'npx.ps1')) {
            $source = Join-Path $sourceNodeDir $name
            if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $localNodeDir $name) -Force }
        }
        New-Item -ItemType Directory -Path (Join-Path $localNodeDir 'node_modules') -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceNodeDir 'node_modules\npm') -Destination (Join-Path $localNodeDir 'node_modules') -Recurse -Force
    }
    $env:Path = "$localNodeDir;$(Join-Path $runtime 'bin');$env:Path"
    $versionText = @(Invoke-SetupStep 'Checking local Node.js' $localNode @('--version') -Capture)[-1]
    if ([version] ([string] $versionText).Trim().TrimStart('v') -lt [version] '22.12.0') { throw 'Node.js 22.12 or newer is required.' }
    Invoke-SetupStep 'Checking local uv' $uv @('--version')
    Invoke-SetupStep "Preparing project Python $PythonVersion" $uv @('python', 'install', $PythonVersion, '--no-bin', '--no-registry')
    $found = @(Invoke-SetupStep 'Finding project Python' $uv @('python', 'find', '--no-project', '--managed-python', '--no-python-downloads', $PythonVersion) -Capture)
    $python = ([string] $found[-1]).Trim()
    $pythonRoot = [IO.Path]::GetFullPath($env:UV_PYTHON_INSTALL_DIR).TrimEnd('\') + '\'
    if (-not (Test-Path -LiteralPath $python) -or -not [IO.Path]::GetFullPath($python).StartsWith($pythonRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'uv did not resolve Python inside .runtime/python; setup stopped without changing a global Python.'
    }
    Invoke-SetupStep 'Installing locked backend and CPU RapidOCR dependencies' $uv @('sync', '--locked', '--extra', 'rapidocr', '--python', $python) $backend
    if (-not (Test-Path -LiteralPath (Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'))) { throw 'Backend sync did not produce .venv-document/Scripts/python.exe.' }
    if (-not $SkipWeb) { Invoke-SetupStep 'Installing Web dependencies' $localNode @($localNpm, 'ci') (Join-Path $repo 'apps\web') }
    if (-not $SkipDesktop) { Invoke-SetupStep 'Installing Desktop dependencies and Electron' $localNode @($localNpm, 'ci') (Join-Path $repo 'apps\desktop') }
    Write-SetupLog 'Setup completed. Existing .env was left untouched. Run scripts/dev.ps1 -Check, then scripts/dev.ps1.'
    Write-SetupLog "Log: $log"
} catch {
    Write-SetupLog "ERROR: $($_.Exception.Message)"
    exit 1
}

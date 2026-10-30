param([string] $NodePath, [string] $PythonPath)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $NodePath) { $NodePath = (Get-Command node.exe -ErrorAction Stop).Source }
if (-not $PythonPath) { $PythonPath = Join-Path $repo 'apps\backend\.venv\Scripts\python.exe' }
$shell = Join-Path $PSHOME 'pwsh.exe'
if (-not (Test-Path -LiteralPath $shell)) { $shell = Join-Path $PSHOME 'powershell.exe' }
$testParent = Join-Path $repo '.runtime\script-tests'
$fixture = Join-Path $testParent ([guid]::NewGuid().ToString('N'))

function Assert-Behavior([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}
function Run-Script([string] $Name, [string[]] $Arguments = @()) {
    $output = & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture "scripts\$Name") @Arguments 2>&1
    return @{ Code = $LASTEXITCODE; Output = ($output -join "`n") }
}
function Read-Trace {
    if (Test-Path -LiteralPath $env:NOTEBOOK_SCRIPT_TEST_TRACE) {
        Get-Content -LiteralPath $env:NOTEBOOK_SCRIPT_TEST_TRACE | ForEach-Object { $_ | ConvertFrom-Json }
    }
}
function Clear-Trace {
    Set-Content -LiteralPath $env:NOTEBOOK_SCRIPT_TEST_TRACE -Value ''
}

try {
    foreach ($folder in @('scripts', 'apps\backend', 'apps\web\node_modules\vite\bin', 'apps\desktop', '.runtime\node\node_modules\npm\bin', '.runtime\python', 'tools')) {
        New-Item -ItemType Directory -Path (Join-Path $fixture $folder) -Force | Out-Null
    }
    foreach ($name in @('setup.ps1', 'dev.ps1', 'test.ps1')) {
        if (Test-Path -LiteralPath (Join-Path $repo "scripts\$name")) { Copy-Item -LiteralPath (Join-Path $repo "scripts\$name") -Destination (Join-Path $fixture "scripts\$name") }
    }
    Copy-Item -LiteralPath $NodePath -Destination (Join-Path $fixture '.runtime\node\node.exe')
    $venv = Join-Path $fixture 'apps\backend\.venv-document'
    & $PythonPath -m venv --without-pip $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated script-test interpreter.' }
    $managedPython = Join-Path $fixture '.runtime\python\python.exe'
    Set-Content -LiteralPath $managedPython -Value 'fixture-only; never executed'
    $env:NOTEBOOK_SCRIPT_TEST_TRACE = Join-Path $fixture 'trace.jsonl'
    $env:NOTEBOOK_SCRIPT_TEST_PYTHON = $managedPython
    $env:NOTEBOOK_SCRIPT_TEST_FAIL = ''
    Set-Content -LiteralPath (Join-Path $fixture '.env') -Value 'DEEPSEEK_API_KEY=keep-existing-secret'
    Set-Content -LiteralPath (Join-Path $fixture '.env.example') -Value 'DEEPSEEK_API_KEY='
    $originalEnv = Get-Content -LiteralPath (Join-Path $fixture '.env') -Raw
    foreach ($app in @('web', 'desktop')) { Set-Content -LiteralPath (Join-Path $fixture "apps\$app\package.json") -Value '{}' }
    Set-Content -LiteralPath (Join-Path $fixture 'apps\web\node_modules\vite\bin\vite.js') -Value '// dependency marker'
    Set-Content -LiteralPath (Join-Path $fixture '.runtime\node\node_modules\npm\bin\npm-cli.js') -Value @'
const fs = require('node:fs');
const path = require('node:path');
fs.appendFileSync(process.env.NOTEBOOK_SCRIPT_TEST_TRACE, JSON.stringify({ tool:'npm', args:process.argv.slice(2), cwd:process.cwd(), node:process.execPath, npmCache:process.env.npm_config_cache, electronCache:process.env.ELECTRON_CACHE })+'\n');
process.exit(process.env.NOTEBOOK_SCRIPT_TEST_FAIL === 'npm:'+path.basename(process.cwd()) ? 9 : 0);
'@
    $uvShim = Join-Path $fixture 'tools\uv.ps1'
    Set-Content -LiteralPath $uvShim -Value @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]] $CommandArgs)
@{ tool='uv'; args=@($CommandArgs); cwd=(Get-Location).Path; pythonDir=$env:UV_PYTHON_INSTALL_DIR; cache=$env:UV_CACHE_DIR; projectEnv=$env:UV_PROJECT_ENVIRONMENT } | ConvertTo-Json -Compress | Add-Content -LiteralPath $env:NOTEBOOK_SCRIPT_TEST_TRACE
$global:LASTEXITCODE = if ($env:NOTEBOOK_SCRIPT_TEST_FAIL -eq 'uv:sync' -and $CommandArgs[0] -eq 'sync') { 9 } else { 0 }
if ($CommandArgs[0] -eq 'python' -and $CommandArgs[1] -eq 'find') { Write-Output $env:NOTEBOOK_SCRIPT_TEST_PYTHON }
'@
    foreach ($module in @('fastapi', 'uvicorn', 'sqlalchemy', 'pymupdf', 'fontTools', 'rapidocr_onnxruntime')) { Set-Content -LiteralPath (Join-Path $fixture "apps\backend\$module.py") -Value '# isolated dependency stub' }
    foreach ($module in @('ruff', 'pytest')) {
        New-Item -ItemType Directory -Path (Join-Path $fixture "apps\backend\$module") -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $fixture "apps\backend\$module\__init__.py") -Value ''
        $main = @'
import json, os, sys
name = __package__
with open(os.environ['NOTEBOOK_SCRIPT_TEST_TRACE'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps({'tool':name, 'args':sys.argv[1:], 'python':sys.executable, 'realOcr':os.getenv('NOTEBOOK_RUN_REAL_OCR')})+'\n')
sys.exit(7 if os.getenv('NOTEBOOK_SCRIPT_TEST_FAIL') == name else 0)
'@
        Set-Content -LiteralPath (Join-Path $fixture "apps\backend\$module\__main__.py") -Value $main
    }

    $result = Run-Script 'setup.ps1' @('-UvPath', $uvShim)
    Assert-Behavior ($result.Code -eq 0) "Default setup failed: $($result.Output)"
    $trace = @(Read-Trace)
    $sync = @($trace | Where-Object { $_.tool -eq 'uv' -and $_.args[0] -eq 'sync' })
    Assert-Behavior ($sync.Count -eq 1 -and ($sync[0].args -join ' ') -eq "sync --locked --extra rapidocr --python $managedPython") 'Setup must install the locked RapidOCR environment with the project Python.'
    $install = @($trace | Where-Object { $_.tool -eq 'uv' -and $_.args[1] -eq 'install' })
    Assert-Behavior ($install.Count -eq 1 -and $install[0].args -contains '--no-registry' -and $install[0].args -contains '--no-bin') 'Python installation must not register global state.'
    $npm = @($trace | Where-Object tool -eq 'npm')
    Assert-Behavior ($npm.Count -eq 2 -and @($npm | Where-Object { ($_.args -join ' ') -ne 'ci' }).Count -eq 0) 'Default setup must prepare both Web and Desktop.'
    Assert-Behavior ($sync[0].projectEnv -eq $venv -and $sync[0].cache -eq (Join-Path $fixture '.runtime\cache\uv')) 'UV must remain inside the project.'
    Assert-Behavior ($npm[0].npmCache -eq (Join-Path $fixture '.runtime\cache\npm') -and $npm[0].electronCache -eq (Join-Path $fixture '.runtime\cache\electron')) 'Node and Electron caches must remain inside the project.'
    Assert-Behavior ((Get-Content -LiteralPath (Join-Path $fixture '.env') -Raw) -eq $originalEnv) 'Setup must preserve existing .env contents.'
    Write-Host 'PASS setup: local runtimes, locked extras, both frontends, caches, and .env preservation'

    Clear-Trace
    $result = Run-Script 'setup.ps1' @('-UvPath', $uvShim, '-SkipWeb', '-SkipDesktop')
    Assert-Behavior ($result.Code -eq 0 -and @((Read-Trace) | Where-Object tool -eq 'npm').Count -eq 0) 'Repeat setup must respect skipped frontend installs.'
    $env:NOTEBOOK_SCRIPT_TEST_FAIL = 'uv:sync'
    Clear-Trace
    $result = Run-Script 'setup.ps1' @('-UvPath', $uvShim)
    Assert-Behavior ($result.Code -ne 0 -and @((Read-Trace) | Where-Object tool -eq 'npm').Count -eq 0) 'Failed backend setup must stop before frontend installs.'
    Write-Host 'PASS setup: repeatability, skip flags, and fail-fast native exit handling'

    $env:NOTEBOOK_SCRIPT_TEST_FAIL = 'ruff'
    Clear-Trace
    $result = Run-Script 'test.ps1'
    Assert-Behavior ($result.Code -ne 0 -and @((Read-Trace) | Where-Object { $_.tool -in @('pytest', 'npm') }).Count -eq 0) 'A failed check must stop the test pipeline immediately.'
    $env:NOTEBOOK_SCRIPT_TEST_FAIL = ''
    Clear-Trace
    $result = Run-Script 'test.ps1' @('-RealOcr')
    Assert-Behavior ($result.Code -eq 0) "Test runner failed: $($result.Output)"
    $trace = @(Read-Trace)
    Assert-Behavior (@($trace | Where-Object tool -eq 'pytest')[0].realOcr -eq '1') 'Real OCR must be explicitly enabled for the backend test process.'
    Assert-Behavior (@($trace | Where-Object { $_.tool -eq 'npm' -and ($_.args -join ' ') -eq 'test' }).Count -eq 1) 'The test script must run frontend behavior tests.'
    Assert-Behavior (@($trace | Where-Object { $_.tool -eq 'npm' -and ($_.args -join ' ') -eq 'run build:main' }).Count -eq 1) 'The test script must build the desktop main process.'
    Write-Host 'PASS test: local Python/Node, real OCR switch, frontend tests, builds, and fail-fast behavior'

    $result = Run-Script 'dev.ps1' @('-Check')
    Assert-Behavior ($result.Code -eq 0 -and $result.Output.Contains($venv)) "Development preflight failed: $($result.Output)"
    Remove-Item -LiteralPath (Join-Path $venv 'Scripts\python.exe')
    $result = Run-Script 'dev.ps1' @('-Check')
    Assert-Behavior ($result.Code -ne 0 -and $result.Output.Contains('setup.ps1')) 'Missing dependencies must explain how to prepare the local environment.'
    Write-Host 'PASS dev: dependency-only preflight and actionable missing-environment errors'
} finally {
    $env:NOTEBOOK_SCRIPT_TEST_TRACE = $null
    $env:NOTEBOOK_SCRIPT_TEST_PYTHON = $null
    $env:NOTEBOOK_SCRIPT_TEST_FAIL = $null
    $absoluteFixture = [IO.Path]::GetFullPath($fixture)
    $absoluteParent = [IO.Path]::GetFullPath($testParent).TrimEnd('\') + '\'
    if ($absoluteFixture.StartsWith($absoluteParent, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $absoluteFixture)) {
        Remove-Item -LiteralPath $absoluteFixture -Recurse -Force
    }
}

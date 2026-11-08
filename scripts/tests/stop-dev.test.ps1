$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repo 'scripts\stop-dev.ps1')

$processes = @(
    [pscustomobject]@{ ProcessId=101; ParentProcessId=1; Name='python.exe'; ExecutablePath="$repo\apps\backend\.venv-document\Scripts\python.exe"; CommandLine='python -m uvicorn app.main:app --port 8000' },
    [pscustomobject]@{ ProcessId=102; ParentProcessId=101; Name='python.exe'; ExecutablePath='C:\Python\python.exe'; CommandLine='python -m uvicorn app.main:app --port 8000' },
    [pscustomobject]@{ ProcessId=103; ParentProcessId=1; Name='python.exe'; ExecutablePath="$repo\.runtime\python\python.exe"; CommandLine='python -m app.workers.runner' },
    [pscustomobject]@{ ProcessId=104; ParentProcessId=1; Name='node.exe'; ExecutablePath='C:\Node\node.exe'; CommandLine="node `"$repo\apps\web\node_modules\.bin\..\vite\bin\vite.js`" --port 5173" },
    [pscustomobject]@{ ProcessId=201; ParentProcessId=1; Name='python.exe'; ExecutablePath='C:\Other\python.exe'; CommandLine='python -m uvicorn app.main:app --port 8000' },
    [pscustomobject]@{ ProcessId=202; ParentProcessId=1; Name='python.exe'; ExecutablePath="$repo\.runtime\python\python.exe"; CommandLine='python -m pytest' },
    [pscustomobject]@{ ProcessId=203; ParentProcessId=1; Name='node.exe'; ExecutablePath="$repo\.runtime\node\node.exe"; CommandLine='node C:\Other\apps\web\node_modules\vite\bin\vite.js' }
)
$found = @(Get-NoteBuddyServiceProcessIds -Processes $processes -Repo $repo | Sort-Object)
if (($found -join ',') -ne '101,102,103,104') { throw "Unsafe service selection: $found" }
Write-Host 'PASS: selects only project API/Worker/Vite and their children; preserves unrelated Python/Node.'

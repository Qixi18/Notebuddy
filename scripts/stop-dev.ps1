[CmdletBinding()]
param([switch] $Check)
$ErrorActionPreference = 'Stop'

function Get-NoteBuddyServiceProcessIds {
    param([object[]] $Processes, [string] $Repo)
    $prefix = [IO.Path]::GetFullPath($Repo).TrimEnd('\') + '\'
    $webPrefix = $prefix + 'apps\web\node_modules\'
    $owned = [Collections.Generic.HashSet[int]]::new()
    foreach ($process in $Processes) {
        $executable = [string] $process.ExecutablePath
        $command = [string] $process.CommandLine
        $backend = $process.Name -eq 'python.exe' -and
            $executable.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and
            $command -match '(?:^|\s)-m\s+(?:uvicorn\s+app\.main:app(?:\s|$)|app\.workers\.runner(?:\s|$))'
        $frontend = $process.Name -eq 'node.exe' -and
            $command.IndexOf($webPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $command -match '[\\/]vite[\\/]bin[\\/]vite\.js'
        if ($backend -or $frontend) { [void] $owned.Add([int] $process.ProcessId) }
    }
    do {
        $changed = $false
        foreach ($process in $Processes) {
            if ($owned.Contains([int] $process.ParentProcessId) -and $owned.Add([int] $process.ProcessId)) {
                $changed = $true
            }
        }
    } while ($changed)
    return @($owned)
}

# Dot-sourcing exposes the pure selector for isolated tests, without inspecting
# or stopping any live process.
if ($MyInvocation.InvocationName -eq '.') { return }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ids = @(Get-NoteBuddyServiceProcessIds -Processes @(Get-CimInstance Win32_Process) -Repo $repo)
if ($Check) {
    Write-Host "NoteBuddy service process IDs: $($ids -join ', ')"
    exit 0
}
if ($ids.Count) {
    Write-Host "Stopping only this project's API, Worker and Vite: $($ids -join ', ')"
    Stop-Process -Id $ids -Force -ErrorAction SilentlyContinue
    foreach ($processId in $ids) { Wait-Process -Id $processId -Timeout 5 -ErrorAction SilentlyContinue }
} else {
    Write-Host 'No running NoteBuddy services found for this project.'
}

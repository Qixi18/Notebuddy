param([Parameter(Mandatory=$true)][string]$OwnerProcessFile)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OwnerProcessFile)) { exit 0 }
$owned = Get-Content -LiteralPath $OwnerProcessFile -Raw | ConvertFrom-Json
$ownedProcess = Get-Process -Id ([int]$owned.ProcessId) -ErrorAction SilentlyContinue
if ($null -eq $ownedProcess) { exit 0 }
if ($ownedProcess.ProcessName -notin @('WINWORD', 'POWERPNT')) { exit 0 }
if ($ownedProcess.StartTime.Ticks.ToString() -ne $owned.StartTicks) { exit 0 }
# Identity includes the process start time, so a recycled PID is never stopped.
Stop-Process -InputObject $ownedProcess -Force

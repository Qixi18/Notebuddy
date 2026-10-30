param([Parameter(Mandatory=$true)][string]$Source, [Parameter(Mandatory=$true)][string]$Target,
      [Parameter(Mandatory=$true)][string]$OwnerProcessFile)
$ErrorActionPreference = 'Stop'
$officeApp = $null
$sourceDocument = $null
$ownsOffice = $false
$processName = if ([IO.Path]::GetExtension($Source) -eq '.pptx') { 'POWERPNT' } else { 'WINWORD' }
$existingOfficeIds = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class OfficeWindowProcess { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId); }'
function Confirm-OwnedOffice($application) {
    [uint32]$officeProcessId = 0
    $windowHandle = $application.HWND
    if ($null -eq $windowHandle) {
        # Word exposes HWND on document windows, not Application. A fresh COM
        # server must have exactly one new process before opening any document.
        $newOfficeProcesses = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $existingOfficeIds -notcontains $_.Id })
        if ($newOfficeProcesses.Count -eq 1) { return $newOfficeProcesses[0].Id }
        throw 'Cannot identify a separate Office process; configure LibreOffice for conversion.'
    }
    [void][OfficeWindowProcess]::GetWindowThreadProcessId([IntPtr]$windowHandle, [ref]$officeProcessId)
    if ($officeProcessId -eq 0 -or $existingOfficeIds -contains $officeProcessId) {
        throw 'Office reused an existing instance; close it or configure LibreOffice for isolated conversion.'
    }
    return $officeProcessId
}
function Record-OwnedOffice($ownedProcessId) {
    $ownedProcess = Get-Process -Id $ownedProcessId
    @{ ProcessId = $ownedProcessId; StartTicks = $ownedProcess.StartTime.Ticks.ToString() } |
        ConvertTo-Json | Set-Content -LiteralPath $OwnerProcessFile -Encoding UTF8
}
try {
    if ($processName -eq 'POWERPNT') {
        $officeApp = New-Object -ComObject PowerPoint.Application
        $ownedProcessId = Confirm-OwnedOffice $officeApp
        $ownsOffice = $true
        Record-OwnedOffice $ownedProcessId
        $officeApp.AutomationSecurity = 3
        $sourceDocument = $officeApp.Presentations.Open($Source, $true, $false, $false)
        $sourceDocument.SaveAs($Target, 32)
    } else {
        $officeApp = New-Object -ComObject Word.Application
        $ownedProcessId = Confirm-OwnedOffice $officeApp
        $ownsOffice = $true
        Record-OwnedOffice $ownedProcessId
        $officeApp.Visible = $false
        $officeApp.DisplayAlerts = 0
        $officeApp.AutomationSecurity = 3
        $officeApp.Options.UpdateLinksAtOpen = $false
        $sourceDocument = $officeApp.Documents.Open($Source, $false, $true, $false)
        $sourceDocument.ExportAsFixedFormat($Target, 17)
    }
} finally {
    if ($null -ne $sourceDocument) { $sourceDocument.Close() }
    # A COM server may share an existing application: never quit the user's instance.
    if ($null -ne $officeApp -and $ownsOffice) { $officeApp.Quit() }
    if ($null -ne $sourceDocument) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sourceDocument) }
    if ($null -ne $officeApp) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($officeApp) }
}

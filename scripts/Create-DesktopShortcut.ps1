#requires -Version 5.1
[CmdletBinding()]
param([string]$ProjectRoot = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$target = Join-Path $ProjectRoot 'Launch.cmd'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Launch.cmd was not found in ProjectRoot.' }
$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'The Windows desktop folder could not be located.' }
$destination = Join-Path $desktop 'Agent Workbench.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $null
try {
    $shortcut = $shell.CreateShortcut($destination)
    if (Test-Path -LiteralPath $destination) {
        if ([string]::Equals($shortcut.TargetPath, $target, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host ('The desktop shortcut already points to this project: ' + $destination)
            return
        }
        throw 'A different Agent Workbench.lnk already exists on the desktop. It has not been changed.'
    }
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description = 'Start Agent Workbench on this computer'
    $shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',20'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host ('Desktop shortcut created: ' + $destination)
} finally {
    if ($null -ne $shortcut) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
}

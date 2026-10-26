#requires -Version 5.1
[CmdletBinding()]
param([string]$ProjectRoot = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$target = Join-Path $ProjectRoot 'Launch.bat'
$legacyTarget = Join-Path $ProjectRoot 'Launch.cmd'
$icon = Join-Path $ProjectRoot 'static\agent-workbench.ico'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Launch.bat was not found in ProjectRoot.' }
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw 'static\agent-workbench.ico was not found in ProjectRoot.' }
$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'The Windows desktop folder could not be located.' }
$destination = Join-Path $desktop 'Agent Workbench.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $null
try {
    $shortcut = $shell.CreateShortcut($destination)
    if (Test-Path -LiteralPath $destination) {
        if ([string]::Equals($shortcut.TargetPath, $target, [StringComparison]::OrdinalIgnoreCase) -or
            [string]::Equals($shortcut.TargetPath, $legacyTarget, [StringComparison]::OrdinalIgnoreCase)) {
            # Keep the user's target, arguments and other launch customizations.
            # In particular, do not reinterpret a legacy CMD link's arguments.
            $shortcut.IconLocation = $icon + ',0'
            $shortcut.Save()
            Write-Host ('Desktop shortcut icon updated; launch settings preserved: ' + $destination)
            return
        }
        throw 'A different Agent Workbench.lnk already exists on the desktop. It has not been changed.'
    }
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description = 'Start Agent Workbench on this computer'
    $shortcut.IconLocation = $icon + ',0'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host ('Desktop shortcut created: ' + $destination)
} finally {
    if ($null -ne $shortcut) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
}

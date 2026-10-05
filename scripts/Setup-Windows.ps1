#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$PythonExecutable = '',
    [string]$ProxyUrl = '',
    [string]$CertificatePath = '',
    [string]$Wheelhouse = '',
    [ValidateRange(5, 600)][int]$TimeoutSeconds = 60,
    [ValidateRange(0, 10)][int]$Retries = 3,
    [switch]$CheckOnly,
    [switch]$CreateDesktopShortcut
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$launcherArgs = @()
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $launcher = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        foreach ($version in @('-3.13', '-3.12', '-3.11')) {
            try { & $launcher.Source $version -c 'import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)' 2>$null }
            catch { continue }
            if ($LASTEXITCODE -eq 0) { $PythonExecutable = $launcher.Source; $launcherArgs = @($version); break }
        }
    }
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $command = Get-Command 'python.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw 'Use approved 64-bit Python 3.11-3.13, or specify -PythonExecutable.' }
        $PythonExecutable = $command.Source
    }
} else { $PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).ProviderPath }
$arguments = @((Join-Path $PSScriptRoot 'setup_windows.py'), '--project-root', $ProjectRoot, '--timeout', [string]$TimeoutSeconds, '--retries', [string]$Retries)
if ($ProxyUrl) { $arguments += @('--proxy', $ProxyUrl) }
if ($CertificatePath) { $arguments += @('--certificate', $CertificatePath) }
if ($Wheelhouse) { $arguments += @('--wheelhouse', $Wheelhouse) }
if ($CheckOnly) { $arguments += '--check' }
& $PythonExecutable @launcherArgs @arguments
if ($LASTEXITCODE -ne 0) { throw 'Setup failed. Review the preceding error and docs\WINDOWS_SETUP.md.' }
if ($CreateDesktopShortcut -and -not $CheckOnly) {
    & (Join-Path $PSScriptRoot 'Create-DesktopShortcut.ps1') -ProjectRoot $ProjectRoot
}

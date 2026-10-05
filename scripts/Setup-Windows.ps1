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
# Never invoke install-capable py/python aliases or discover a runtime by launching them.
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) { $PythonExecutable = $env:WORKBENCH_PYTHON }
if ([string]::IsNullOrWhiteSpace($PythonExecutable) -or $PythonExecutable -notmatch '^[A-Za-z]:[\\/]') {
    throw 'Python must be approved and installed separately. Set -PythonExecutable or WORKBENCH_PYTHON to the full local path of the actual approved python.exe, not a launcher alias.'
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).ProviderPath
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) -or [IO.Path]::GetFileName($PythonExecutable) -ine 'python.exe') {
    throw 'Specify the existing, organization-approved python.exe. Setup never downloads or installs Python.'
}
# A standard installed CPython layout is required before any executable is invoked.
$pythonHome = Split-Path -Parent $PythonExecutable
foreach ($relative in @('Lib\os.py', 'Lib\venv\__init__.py', 'Lib\ensurepip\__init__.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $pythonHome $relative) -PathType Leaf)) {
        throw 'Specify the actual standard CPython installation, not a launcher alias or a copied virtual environment. Ask IT for the approved interpreter path.'
    }
}
$arguments = @((Join-Path $PSScriptRoot 'setup_windows.py'), '--project-root', $ProjectRoot, '--timeout', [string]$TimeoutSeconds, '--retries', [string]$Retries)
if ($ProxyUrl) { $arguments += @('--proxy', $ProxyUrl) }
if ($CertificatePath) { $arguments += @('--certificate', $CertificatePath) }
if ($Wheelhouse) { $arguments += @('--wheelhouse', $Wheelhouse) }
if ($CheckOnly) { $arguments += '--check' }
& $PythonExecutable @arguments
if ($LASTEXITCODE -ne 0) { throw 'Setup failed. Review the preceding error and docs\WINDOWS_SETUP.md.' }
if ($CreateDesktopShortcut -and -not $CheckOnly) {
    & (Join-Path $PSScriptRoot 'Create-DesktopShortcut.ps1') -ProjectRoot $ProjectRoot
}

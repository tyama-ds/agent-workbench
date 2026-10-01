#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$PythonExecutable = '',
    [switch]$CreateDesktopShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$lock = Join-Path $ProjectRoot 'requirements.lock'
if (-not (Test-Path -LiteralPath $lock -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'pyproject.toml') -PathType Leaf)) {
    throw 'ProjectRoot must contain pyproject.toml and requirements.lock.'
}
$environment = Join-Path $ProjectRoot '.venv'
$python = Join-Path $environment 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (Test-Path -LiteralPath $environment) {
        throw 'An incomplete .venv already exists. Inspect it manually; setup will not replace or delete it.'
    }
    $launcherArgs = @()
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $command = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            $PythonExecutable = $command.Source
            $launcherArgs = @('-3')
        } else {
            $command = Get-Command 'python.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $command) { throw 'Install Python 3.11 or newer, or specify -PythonExecutable with its full path.' }
            $PythonExecutable = $command.Source
        }
    } else {
        $PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).ProviderPath
    }
    & $PythonExecutable @launcherArgs -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    & $PythonExecutable @launcherArgs -m venv $environment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& $python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'The existing .venv requires Python 3.11 or newer. Setup will not replace it.' }

Push-Location -LiteralPath $ProjectRoot
try {
    & $python -m pip install --disable-pip-version-check --require-hashes -r $lock
    if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed.' }
    & $python -m pip install --disable-pip-version-check -e . --no-deps --no-build-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Editable project installation failed.' }
    if ($CreateDesktopShortcut) {
        & (Join-Path $PSScriptRoot 'Create-DesktopShortcut.ps1') -ProjectRoot $ProjectRoot
    }
} finally { Pop-Location }
Write-Host 'Setup complete. Double-click Launch.cmd to start Agent Workbench.'

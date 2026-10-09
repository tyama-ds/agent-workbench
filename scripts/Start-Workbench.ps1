#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [ValidateRange(0, 65535)][int]$Port = 8818,
    [string]$StateDir = '',
    [switch]$NoBrowser
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Double-click Setup.cmd first.' }
$arguments = @((Join-Path $PSScriptRoot 'start_workbench.py'), '--project-root', $ProjectRoot, '--port', [string]$Port)
if ($StateDir) { $arguments += @('--state-dir', $StateDir) }
if ($NoBrowser) { $arguments += '--no-browser' }
& $python @arguments
exit $LASTEXITCODE

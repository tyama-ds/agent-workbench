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
# Resolve script-dependent defaults after parameter binding (Windows PowerShell 5.1).
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The local Python environment is missing. Run scripts\Setup-Windows.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'workbench\server.py') -PathType Leaf)) {
    throw 'ProjectRoot is not an Agent Workbench project.'
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$stateIdentity = 'default-state-directory'
if (-not [string]::IsNullOrWhiteSpace($StateDir)) {
    # A launch with different settings must not silently reopen the other state.
    $StateDir = [System.IO.Path]::GetFullPath($StateDir)
    $stateIdentity = $StateDir.ToLowerInvariant()
}
$hash = [System.Security.Cryptography.SHA256]::Create()
try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($identity + '|' + $ProjectRoot.ToLowerInvariant() + '|' + $Port + '|' + $stateIdentity)
    $digest = [System.BitConverter]::ToString($hash.ComputeHash($bytes)).Replace('-', '')
} finally {
    $hash.Dispose()
}
$guard = [System.Threading.Mutex]::new($false, ('Local\AgentWorkbench-' + $digest))
$owned = $false
$resultCode = 0
try {
    try { $owned = $guard.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) {
        if ($Port -eq 0) {
            Write-Host 'Agent Workbench is already starting/running with a dynamic port. Use its existing browser or console URL.'
        } else {
            $existingUrl = 'http://127.0.0.1:' + $Port + '/'
            # A second click can occur before Python has bound the listener.
            $ready = $false
            $deadline = [DateTime]::UtcNow.AddSeconds(5)
            while (-not $ready -and [DateTime]::UtcNow -lt $deadline) {
                $connection = [System.Net.Sockets.TcpClient]::new()
                try {
                    $pending = $connection.ConnectAsync('127.0.0.1', $Port)
                    if ($pending.Wait(200) -and $connection.Connected) { $ready = $true }
                } catch { } finally { $connection.Dispose() }
                if (-not $ready) { Start-Sleep -Milliseconds 200 }
            }
            Write-Host ('Agent Workbench is already starting/running: ' + $existingUrl)
            if (-not $NoBrowser -and $ready) { Start-Process -FilePath $existingUrl | Out-Null }
            if (-not $ready) { Write-Host 'The listener is still starting. Check the existing console window.' }
            Write-Host 'Reopening uses the existing browser session. If authentication was lost, stop that console with Ctrl+C and start again.'
        }
    } else {
        $arguments = @('-m', 'workbench.server', '--port', [string]$Port)
        if ($NoBrowser) { $arguments += '--no-browser' }
        if (-not [string]::IsNullOrWhiteSpace($StateDir)) { $arguments += @('--state-dir', $StateDir) }
        Write-Host 'Starting Agent Workbench. Keep this console open; Ctrl+C stops the server.'
        Push-Location -LiteralPath $ProjectRoot
        try {
            & $python @arguments
            $resultCode = $LASTEXITCODE
        } finally { Pop-Location }
    }
} finally {
    if ($owned) { $guard.ReleaseMutex() }
    $guard.Dispose()
}
exit $resultCode

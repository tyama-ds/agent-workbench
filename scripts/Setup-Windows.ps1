#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$PythonExecutable = '',
    [string]$ProxyUrl = '',
    [string]$CertificatePath = '',
    [ValidateRange(5, 600)][int]$TimeoutSeconds = 60,
    [ValidateRange(0, 10)][int]$Retries = 3,
    [switch]$CreateDesktopShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$pipNetworkArgs = @('--timeout', [string]$TimeoutSeconds, '--retries', [string]$Retries)
if (-not [string]::IsNullOrWhiteSpace($ProxyUrl)) {
    $proxyUri = $null
    if ($ProxyUrl -match '[\x00-\x20\x7f\\]' -or
        -not [Uri]::TryCreate($ProxyUrl, [UriKind]::Absolute, [ref]$proxyUri) -or
        $proxyUri.Scheme -notin @('http', 'https') -or
        [string]::IsNullOrWhiteSpace($proxyUri.Host) -or
        $proxyUri.Port -lt 1 -or
        -not [string]::IsNullOrEmpty($proxyUri.UserInfo) -or
        $proxyUri.AbsolutePath -notin @('', '/') -or
        -not [string]::IsNullOrEmpty($proxyUri.Query) -or
        -not [string]::IsNullOrEmpty($proxyUri.Fragment)) {
        throw 'ProxyUrl must be an HTTP(S) proxy origin such as http://proxy.example.local:8080, without credentials or a PAC URL.'
    }
    $pipNetworkArgs += @('--proxy', $proxyUri.AbsoluteUri.TrimEnd('/'))
    Write-Host 'Using the explicit proxy for package installation only.'
} else {
    Write-Host 'Package installation uses existing pip/proxy settings. If a proxy is required, specify -ProxyUrl.'
}
if (-not [string]::IsNullOrWhiteSpace($CertificatePath)) {
    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
        throw 'CertificatePath must name an existing PEM certificate bundle supplied by your organization.'
    }
    $CertificatePath = (Resolve-Path -LiteralPath $CertificatePath).ProviderPath
    $pipNetworkArgs += @('--cert', $CertificatePath)
}
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
    & $python -m pip install --disable-pip-version-check @pipNetworkArgs --require-hashes -r $lock
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency download/install failed. For ConnectTimeout/ProxyError, check the proxy host and port (-ProxyUrl). HTTP 407 needs proxy authentication. CERTIFICATE_VERIFY_FAILED needs a trusted organization CA, optionally -CertificatePath. The existing .venv is retained; rerun setup after correcting the connection.'
    }
    & $python -m pip install --disable-pip-version-check @pipNetworkArgs -e . --no-deps --no-build-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Editable project installation failed.' }
    if ($CreateDesktopShortcut) {
        & (Join-Path $PSScriptRoot 'Create-DesktopShortcut.ps1') -ProjectRoot $ProjectRoot
    }
} finally { Pop-Location }
Write-Host 'Setup complete. Double-click Launch.cmd to start Agent Workbench.'

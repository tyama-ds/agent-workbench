@echo off
setlocal DisableDelayedExpansion
if /i "%~1"=="--help" goto configured_help
if /i "%~1"=="--check" goto configured_check
if not [%1]==[] goto configured_arguments
set "WORKBENCH_CONFIGURED_CHECK="
goto configured_run
:configured_check
if not [%2]==[] goto configured_arguments
set "WORKBENCH_CONFIGURED_CHECK=1"
:configured_run
rem Read local JSON as data. Never evaluate its contents or override execution policy.
set "WORKBENCH_CONFIGURED_ROOT=%~dp0"
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" goto configured_powershell_missing
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $failure='Cannot read runtime.local.json. Copy runtime.example.json to runtime.local.json and edit its paths.'; try { $root=$env:WORKBENCH_CONFIGURED_ROOT; $configPath=Join-Path $root 'runtime.local.json'; if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'missing' }; if ((Get-Item -LiteralPath $configPath).Length -gt 65536) { throw 'large' }; $raw=[IO.File]::ReadAllText($configPath,[Text.Encoding]::UTF8); $failure='runtime.local.json must contain valid JSON with a python_executable string.'; $config=ConvertFrom-Json -InputObject $raw; $python=$config.python_executable; if (-not ($python -is [string]) -or $python -notmatch '^[A-Za-z]:[\\/]' -or $python -match '[\x00-\x1f\x7f]') { throw 'path' }; $failure='Set python_executable to an existing, separately installed standard python.exe using its full local path. Launcher aliases and copied virtual environments are not supported.'; if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or [IO.Path]::GetFileName($python) -ine 'python.exe') { throw 'python' }; $python=(Resolve-Path -LiteralPath $python).ProviderPath; $pythonHome=Split-Path -Parent $python; foreach ($relative in @('Lib\os.py','Lib\venv\__init__.py','Lib\ensurepip\__init__.py')) { if (-not (Test-Path -LiteralPath (Join-Path $pythonHome $relative) -PathType Leaf)) { throw 'layout' } }; $failure='Cannot start the configured Python. Check the approved interpreter and scripts/configured_runtime.py.'; $arguments=@('-I','-S','-B',(Join-Path $root 'scripts\configured_runtime.py'),'--config',$configPath); if ($env:WORKBENCH_CONFIGURED_CHECK -eq '1') { $arguments+='--check' }; & $python @arguments; exit $LASTEXITCODE } catch { [Console]::Error.WriteLine('Configured launch stopped: '+$failure); exit 1 }"
set "workbench_configured_exit=%ERRORLEVEL%"
if defined WORKBENCH_CONFIGURED_CHECK exit /b %workbench_configured_exit%
if not "%workbench_configured_exit%"=="0" pause
exit /b %workbench_configured_exit%
:configured_powershell_missing
echo Windows PowerShell is required to read runtime.local.json. No Python was started.
if not defined WORKBENCH_CONFIGURED_CHECK pause
exit /b 1
:configured_help
if not [%2]==[] goto configured_arguments
echo Agent Workbench configured launch
echo Usage: Launch-Configured.cmd
echo Check: Launch-Configured.cmd --check
echo Help:  Launch-Configured.cmd --help
echo Use --check or --help as the only argument.
echo Copy runtime.example.json to runtime.local.json and set your Python and library paths.
echo Port, state directory, and browser settings also belong in runtime.local.json.
echo This launcher does not download or install Python or packages.
echo Configured launch uses built-in Windows PowerShell to read JSON without changing policy.
echo Help does not read JSON, start Python, or require PowerShell.
exit /b 0
:configured_arguments
echo Use no arguments, --check alone, or --help alone.
echo Edit runtime.local.json for paths and launch settings. Nothing was started.
exit /b 2

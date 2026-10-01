@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-Workbench.ps1" %*
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" pause
exit /b %workbench_exit%

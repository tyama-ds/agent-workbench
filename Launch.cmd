@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Setup is missing. Double-click Setup.cmd first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_workbench.py" %*
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" pause
exit /b %workbench_exit%

@echo off
setlocal DisableDelayedExpansion
rem Uses an already approved Python without elevation or policy changes.
if defined WORKBENCH_PYTHON (
  "%WORKBENCH_PYTHON%" "%~dp0scripts\setup_windows.py" %*
  goto finished
)
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys,struct; sys.exit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>nul
  if not errorlevel 1 (
    py -%%V "%~dp0scripts\setup_windows.py" %*
    goto finished
  )
)
python -c "import sys,struct; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11-3.13 64-bit was not found. Ask IT for approved Python 3.13.
  echo Or set WORKBENCH_PYTHON to the full path of an approved python.exe.
  pause
  exit /b 1
)
python "%~dp0scripts\setup_windows.py" %*
:finished
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" echo Setup failed. See the error above and docs\WINDOWS_SETUP.md.
pause
exit /b %workbench_exit%

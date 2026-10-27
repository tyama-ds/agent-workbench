@echo off
setlocal DisableDelayedExpansion
if /i "%~1"=="--help" goto update_help
if /i "%~1"=="-h" goto update_help
if "%~1"=="/?" goto update_help
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo This folder has not been set up. Run Setup.bat once before using Update.bat.
  echo Keep the application in the same folder when updating. Do not copy a .venv.
  pause
  exit /b 1
)
echo Agent Workbench update
echo Close Agent Workbench before updating. Saved settings and history are kept.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\update_workbench.py" %*
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" echo Update did not complete. See the error above.
pause
exit /b %workbench_exit%

:update_help
if not [%2]==[] goto help_arguments
echo Agent Workbench update in the existing application folder
echo 1. Stop Agent Workbench and extract the new official source ZIP.
echo 2. Copy the new source contents into this folder, keeping the existing .venv.
echo 3. Run Update.bat, then Launch.bat after Update complete.
echo The folder, Python environment and shortcuts keep their current locations.
echo Application source is not downloaded by this command. Python is not installed.
echo Existing pip/environment proxy settings are reused.
echo Optional network input: Update.bat --interactive
echo Other options: --check, --proxy URL, --certificate FILE, --wheelhouse FOLDER,
echo                --timeout 5..600, --retries 0..10
echo See docs\WINDOWS_SETUP.md for the first migration from an old installation.
exit /b 0

:help_arguments
echo Help must be used alone: Update.bat --help
exit /b 2

@echo off
setlocal DisableDelayedExpansion
rem Never invoke py/python aliases: install managers may install a missing runtime.
rem IT must approve and install the actual interpreter before this source setup.
if not defined WORKBENCH_PYTHON goto python_required
if not "%WORKBENCH_PYTHON:~1,2%"==":\" goto python_required
if not exist "%WORKBENCH_PYTHON%" goto python_required
for %%I in ("%WORKBENCH_PYTHON%") do (
  if /i not "%%~nxI"=="python.exe" goto python_required
  rem A standard installed CPython layout is required, not an app-execution alias.
  if not exist "%%~dpILib\os.py" goto python_required
  if not exist "%%~dpILib\venv\__init__.py" goto python_required
  if not exist "%%~dpILib\ensurepip\__init__.py" goto python_required
)
"%WORKBENCH_PYTHON%" "%~dp0scripts\setup_windows.py" %*
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" echo Setup failed. See the error above and docs\WINDOWS_SETUP.md.
pause
exit /b %workbench_exit%
:python_required
echo Python must be approved and installed separately by your organization.
echo This application does not bundle, download, or install Python.
echo Set WORKBENCH_PYTHON to the full local path of the approved python.exe.
echo Example: set "WORKBENCH_PYTHON=C:\Approved Python\python.exe"
echo Then run Setup.cmd in the same Command Prompt. Do not use a launcher alias.
pause
exit /b 1

@echo off
setlocal DisableDelayedExpansion
rem Help works before Python has been selected or installed.
if /i "%~1"=="--help" goto setup_help
if /i "%~1"=="-h" goto setup_help
if "%~1"=="/?" goto setup_help
if defined WORKBENCH_PYTHON goto validate_python
echo Agent Workbench setup
echo Paste the full path of your separately installed, approved python.exe.
echo Example: C:\Approved Python\python.exe
echo Python itself will not be downloaded or installed. Blank input cancels.
set /p "WORKBENCH_PYTHON=Python path: "
if not defined WORKBENCH_PYTHON goto python_required

:validate_python
rem Delayed expansion treats pasted quotes/metacharacters as data, not commands.
rem Accept one surrounding quote pair from Explorer's Copy as path.
setlocal EnableDelayedExpansion
set workbench_quote="
if "!WORKBENCH_PYTHON:~0,1!"=="!workbench_quote!" if "!WORKBENCH_PYTHON:~-1!"=="!workbench_quote!" set "WORKBENCH_PYTHON=!WORKBENCH_PYTHON:~1,-1!"
if not defined WORKBENCH_PYTHON goto python_required
set "workbench_unquoted=!WORKBENCH_PYTHON:"=!"
if not "!WORKBENCH_PYTHON!"=="!workbench_unquoted!" goto python_required
setlocal DisableDelayedExpansion
rem Never invoke py/python aliases: install managers may install a runtime.
if not "%WORKBENCH_PYTHON:~1,2%"==":\" goto python_required
if not exist "%WORKBENCH_PYTHON%" goto python_required
for %%I in ("%WORKBENCH_PYTHON%") do (
  if /i not "%%~nxI"=="python.exe" goto python_required
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
echo Setup did not run. Select an existing standard Python installation.
echo Use the full local path of its python.exe, not py, python, or a .venv copy.
echo Python must be approved and installed separately by your organization.
echo Run Setup.bat again and paste that path. No set command is needed.
pause
exit /b 1

:setup_help
if not [%2]==[] goto help_arguments
echo Agent Workbench source setup
echo Double-click Setup.bat and paste the path of your installed python.exe.
echo After Setup complete, double-click Launch.bat.
echo No environment-variable command is needed; the path is not saved globally.
echo.
echo Usage: Setup.bat [options]
echo Help: Setup.bat --help  or  Setup.bat -h  or  Setup.bat /?
echo Use a help alias as the first and only argument. Help does not run Python.
echo Python must be approved and installed separately by your organization.
echo This application does not bundle, download, or install Python.
echo Use actual standard 64-bit CPython 3.11-3.13, not launcher aliases.
echo If WORKBENCH_PYTHON is already set, its path is used without prompting.
echo.
echo Options:
echo   --check                 Check prerequisites without installing or network.
echo   --proxy URL             IT-approved HTTP/HTTPS proxy origin; no credentials.
echo   --certificate FILE      Existing IT-approved PEM CA bundle.
echo   --wheelhouse FOLDER     Offline wheels; cannot combine with proxy or CA.
echo   --timeout 5..600        Connection timeout in seconds; default 60.
echo   --retries 0..10         Connection retries; default 3.
echo   --project-root FOLDER   Source folder; default is this script's folder.
echo.
echo Examples:
echo   Setup.bat --check
echo   Setup.bat --proxy "http://proxy.example.local:8080" --certificate "C:\Certificates\company-ca.pem"
echo   Setup.bat --wheelhouse "C:\Approved Packages\wheelhouse"
echo Help displays instructions only; it does not validate prerequisites.
echo See docs\WINDOWS_SETUP.md for details.
exit /b 0
:help_arguments
echo Help must be used alone: Setup.bat --help
echo No setup was performed. Put setup options in a separate invocation.
exit /b 2

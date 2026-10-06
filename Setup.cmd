@echo off
setlocal DisableDelayedExpansion
rem Only a first-position help alias selects the Python-independent help path.
if /i "%~1"=="--help" goto setup_help
if /i "%~1"=="-h" goto setup_help
if "%~1"=="/?" goto setup_help
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
:setup_help
rem Keep surrounding quotes so an explicitly empty second argument is rejected.
if not [%2]==[] goto help_arguments
echo Agent Workbench source setup
echo Usage: Setup.cmd [options]
echo Help: Setup.cmd --help  or  Setup.cmd -h  or  Setup.cmd /?
echo Use a help alias as the first and only argument. Help does not run Python.
echo.
echo Python must be approved and installed separately by your organization.
echo This application does not bundle, download, or install Python.
echo Use the full local path of the actual standard 64-bit CPython 3.11-3.13.
echo Do not use py/python launcher aliases or a copied virtual environment.
echo Example in the same Command Prompt, using your IT-approved path:
echo   set "WORKBENCH_PYTHON=C:\Approved Python\python.exe"
echo   Setup.cmd --check
echo   Setup.cmd
echo The set command applies only to that Command Prompt, not persistent settings.
echo After Setup complete, double-click Launch.cmd.
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
echo Examples after setting WORKBENCH_PYTHON:
echo   Setup.cmd --proxy "http://proxy.example.local:8080" --certificate "C:\Certificates\company-ca.pem"
echo   Setup.cmd --wheelhouse "C:\Approved Packages\wheelhouse"
echo Help only displays these instructions. It does not validate prerequisites.
echo See docs\WINDOWS_SETUP.md for approval, setup, and troubleshooting details.
exit /b 0
:help_arguments
echo Help must be used alone: Setup.cmd --help
echo No setup was performed. Put setup options in a separate invocation.
exit /b 2

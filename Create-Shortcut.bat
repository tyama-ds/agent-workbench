@echo off
setlocal DisableDelayedExpansion
if /i "%~1"=="--help" goto shortcut_help
if /i "%~1"=="-h" goto shortcut_help
if "%~1"=="/?" goto shortcut_help
if not [%1]==[] goto shortcut_arguments
if not exist "%~dp0scripts\Create-DesktopShortcut.js" (
  echo Shortcut helper is missing. Extract the complete Agent Workbench folder first.
  pause
  exit /b 1
)
"%SystemRoot%\System32\cscript.exe" //nologo "%~dp0scripts\Create-DesktopShortcut.js" "%~dp0."
set "workbench_exit=%ERRORLEVEL%"
if not "%workbench_exit%"=="0" echo Shortcut creation failed. See the error above.
pause
exit /b %workbench_exit%

:shortcut_help
if not [%2]==[] goto shortcut_arguments
echo Agent Workbench desktop shortcut
echo Usage: Double-click Create-Shortcut.bat to create or update the desktop icon.
echo Existing shortcut arguments and launch settings are preserved for this project.
echo No installation, model download, or settings change is performed.
exit /b 0

:shortcut_arguments
echo Create-Shortcut.bat takes no arguments. Use --help for details.
pause
exit /b 2

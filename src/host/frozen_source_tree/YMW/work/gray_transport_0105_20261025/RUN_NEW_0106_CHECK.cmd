@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_NEW_0106_CHECK.ps1"
set "probeExit=%ERRORLEVEL%"
echo.
echo New 0106 check exit code: %probeExit%
pause
exit /b %probeExit%

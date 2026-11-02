@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_0106_TRANSPORT_CHECK.ps1"
set "checkExit=%ERRORLEVEL%"
echo.
echo Engineering RGB/GRAY transport check exit code: %checkExit%
pause
exit /b %checkExit%

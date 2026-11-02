@echo off
setlocal
echo START: Guangjian P0 console
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_P0_CONSOLE.ps1"
set "RESULT_CODE=%ERRORLEVEL%"
echo Exit code: %RESULT_CODE%
pause
exit /b %RESULT_CODE%

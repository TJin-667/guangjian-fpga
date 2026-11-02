@echo off
setlocal
echo START: 0107 resume. Progress will be shown. Do not close this window.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_ACCEPTANCE_0107.ps1"
set "RESULT=%ERRORLEVEL%"
echo Exit code: %RESULT%
pause
exit /b %RESULT%

@echo off
setlocal
echo START: P0 sample004 A_v1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_P0_PAIR.ps1" -Specimen sample004
set "RESULT_CODE=%ERRORLEVEL%"
echo Exit code: %RESULT_CODE%
pause
exit /b %RESULT_CODE%

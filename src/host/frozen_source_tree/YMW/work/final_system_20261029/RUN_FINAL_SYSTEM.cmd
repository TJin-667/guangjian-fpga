@echo off
setlocal
echo START: Guangjian capture / frozen detection / local review
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_FINAL_SYSTEM.ps1"
set "RESULT_CODE=%ERRORLEVEL%"
echo Exit code: %RESULT_CODE%
pause
exit /b %RESULT_CODE%

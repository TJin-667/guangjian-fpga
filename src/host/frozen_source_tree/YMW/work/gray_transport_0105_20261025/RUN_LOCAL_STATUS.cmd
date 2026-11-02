@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_LOCAL_STATUS.ps1" %*
echo.
echo Local status check finished. Results are printed above.
pause

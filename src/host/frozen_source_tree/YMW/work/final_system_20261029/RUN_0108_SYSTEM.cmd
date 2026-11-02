@echo off
setlocal
echo START: Guangjian 0108 focus / positioning / eight-frame acceptance
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\GuangjianData\software\FinalSystem_20261029\RUN_FINAL_SYSTEM.ps1" -HardwareMode 0108
set "RESULT_CODE=%ERRORLEVEL%"
echo Exit code: %RESULT_CODE%
pause
exit /b %RESULT_CODE%

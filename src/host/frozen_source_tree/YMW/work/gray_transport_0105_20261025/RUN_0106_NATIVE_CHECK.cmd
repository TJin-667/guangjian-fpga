@echo off
setlocal
"C:\Users\yue\.codex\.chatgpt-projects\g-p-6aacf33115048191845c3025390bb3cd\output\BX72_FourLight_ROI_20261012\.venv_demo\Scripts\python.exe" -B "%~dp0engineering_native_check.py" --run
set "checkExit=%ERRORLEVEL%"
echo.
echo Native RGB/GRAY check exit code: %checkExit%
pause
exit /b %checkExit%

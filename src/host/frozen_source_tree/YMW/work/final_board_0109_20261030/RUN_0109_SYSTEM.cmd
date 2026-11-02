@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PY=C:\Users\yue\.codex\.chatgpt-projects\g-p-6aacf33115048191845c3025390bb3cd\output\BX72_FourLight_ROI_20261012\.venv_demo\Scripts\python.exe"
"%PY%" -B -u "%~dp0runtime\continuous_app.py" %*
if errorlevel 1 (
 echo.
 echo 0109 candidate startup failed. Keep this window and report the error above.
 pause
)
endlocal

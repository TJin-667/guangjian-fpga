param([switch]$CheckOnly,[ValidateSet('0107','0108')][string]$HardwareMode='0107',[string]$EngineeringPlan='')
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
Write-Host 'STARTED: Guangjian final system. Startup is offline; 0108 is engineering only.'
$python='C:/Users/yue/.codex/.chatgpt-projects/g-p-6aacf33115048191845c3025390bb3cd/output/BX72_FourLight_ROI_20261012/.venv_demo/Scripts/python.exe'
$entry='C:/bx72_ymw_0105_20261015/repo/YMW/work/final_system_20261029/app.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Existing camera Python runtime missing.' }
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'Final system source missing.' }
if ($CheckOnly) { & $python -B -u $entry --check-only --hardware-mode $HardwareMode; exit $LASTEXITCODE }
if ($EngineeringPlan) { & $python -B -u $entry --hardware-mode $HardwareMode --engineering-plan $EngineeringPlan }
else { & $python -B -u $entry --hardware-mode $HardwareMode }
exit $LASTEXITCODE

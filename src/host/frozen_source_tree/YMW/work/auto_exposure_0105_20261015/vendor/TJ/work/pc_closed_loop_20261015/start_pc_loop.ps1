param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Dependencies,
    [Parameter(Mandatory=$true)][string]$Out,
    [ValidateSet('peer','verify','audit')][string]$Action='peer'
)
$ErrorActionPreference='Stop'
$taskScript = switch ($Action) {
    'peer'   { Join-Path $PSScriptRoot 'run_closed_loop.py' }
    'verify' { Join-Path $PSScriptRoot 'run_verification.py' }
    'audit'  { Join-Path $PSScriptRoot 'audit_closed_loop.py' }
}
$taskArguments=@('-B',$taskScript,'--dependencies',$Dependencies)
if ($Action -eq 'verify') {
    $taskArguments+=@('--work',$Out)
} else {
    $taskArguments+=@('--out',$Out)
}
if ($Action -eq 'peer') { $taskArguments+='--software-peer' }
& $Python @taskArguments
exit $LASTEXITCODE

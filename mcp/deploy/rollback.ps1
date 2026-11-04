param(
    [Parameter(Mandatory)][string]$Plan,
    [string]$ApprovalHash,
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'rollout.py'), '--phase', 'rollback', '--plan', $Plan)
if ($ApprovalHash) { $arguments += @('--rollback-approval-hash', $ApprovalHash) }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "Pilot rollback stopped (exit $LASTEXITCODE); no automatic retries." }

param(
    [ValidateSet('plan','preflight','identity','secret','foundation','publish','application','connection')]
    [string]$Phase = 'plan',
    [string]$Plan,
    [string]$Release,
    [string]$BaseConfig,
    [string]$McpImage,
    [string]$ApiImage,
    [string]$ApprovalHash,
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'rollout.py'), '--phase', $Phase)
foreach ($entry in @{
    '--plan'=$Plan; '--release'=$Release; '--base-config'=$BaseConfig
    '--mcp-image'=$McpImage; '--api-image'=$ApiImage; '--approval-hash'=$ApprovalHash
}.GetEnumerator()) {
    if ($entry.Value) { $arguments += @($entry.Key, $entry.Value) }
}
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "Pilot rollout stopped (exit $LASTEXITCODE); inspect the journal before retrying." }

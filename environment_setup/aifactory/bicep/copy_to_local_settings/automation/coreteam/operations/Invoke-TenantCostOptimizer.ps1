#Requires -Version 7.6
param(
    [Parameter(Position = 0)]
    [ValidateSet('STOP', 'START', 'STATUS')]
    [string]$Action = 'STATUS',
    [Parameter(Mandatory)][string]$ConfigurationPath,
    [switch]$Preview,
    [switch]$NoWait
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Azure-Control.ps1"
. "$PSScriptRoot\Tenant-Cost-Optimizer.ps1" -Action $Action
$configuration = Get-Content -LiteralPath $ConfigurationPath -Raw | ConvertFrom-Json -AsHashtable -DateKind String
Assert-OptimizerConfiguration $configuration
$mode = if ($Preview -or $Action -eq 'STATUS') { 'Preview' } else { 'Live' }
Invoke-HostedOptimizerJob -Configuration $configuration -Action $Action -Mode $mode -NoWait:$NoWait

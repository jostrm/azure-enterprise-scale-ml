[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $ConfigFile = (Join-Path (Get-Location).Path 'variables.json'),
    [ValidateSet('dev', 'stage', 'test', 'prod')] [string] $Environment = 'dev',
    [string] $AgentName,
    [string] $ProjectResourceId,
    [string] $ProfileFile,
    [ValidateSet('Shared', 'Tenant')] [string] $Scope,
    [switch] $NonInteractive,
    [switch] $RetryUncertain,
    [string] $RepositoryRoot
)

Import-Module (Join-Path $PSScriptRoot 'FoundryPublishing.psm1') -Force
Invoke-FoundryPublishing -Surface Teams @PSBoundParameters

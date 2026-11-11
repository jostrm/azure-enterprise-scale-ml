#Requires -Version 7.0
<#
.SYNOPSIS
    Creates (or updates) the ESAF region policy: AI Search in Sweden Central, France Central and Italy North;
    every other regional resource type, and resource groups, only in Sweden Central.

.DESCRIPTION
    Creates three custom policy definitions, one policy set (initiative) and one assignment, all marked with
    metadata.createdBy = 'esaf-region-policy'. Running it again updates them in place. It refuses to
    overwrite an object with the same name that this kit did not create, and checks that the az login
    reaches the subscription in the given tenant before it writes anything.

    There are no subscription or tenant defaults: pass them, or keep them in a settings file (see
    region-policy.settings.example.psd1 and README.md).

.EXAMPLE
    ./New-EsafRegionPolicy.ps1 -TenantId <tenant-guid> -SubscriptionId <subscription-guid> -EnforcementMode DoNotEnforce

.EXAMPLE
    $settings = Import-PowerShellDataFile ./region-policy.settings.psd1
    ./New-EsafRegionPolicy.ps1 @settings
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F-]{36}$')][string] $TenantId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F-]{36}$')][string] $SubscriptionId,

    # Store the definitions and the policy set at this management group (for reuse across subscriptions).
    [string] $ManagementGroupId,
    # Defaults to the subscription. A resource group ID limits the policy to that resource group.
    [string] $AssignmentScope,
    [ValidateLength(1, 24)][string] $AssignmentName = 'esaf-region-policy',

    [string[]] $BaselineLocations = @('swedencentral'),
    [string[]] $MultiRegionResourceTypes = @('Microsoft.Search/searchServices'),
    [string[]] $MultiRegionLocations = @('swedencentral', 'francecentral', 'italynorth'),
    [bool] $RestrictResourceGroupLocation = $true,

    # DoNotEnforce = audit only (shows compliance, denies nothing). Use it for the first rollout.
    [ValidateSet('Default', 'DoNotEnforce')][string] $EnforcementMode = 'Default',
    [ValidateSet('Deny', 'Audit', 'Disabled')][string] $Effect = 'Deny'
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'EsafRegionPolicy.psm1') -Force

# Accept comma-separated values too, for callers that pass one string (pipelines, cmd).
$split = { param($values) @($values | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
$BaselineLocations = & $split $BaselineLocations
$MultiRegionResourceTypes = & $split $MultiRegionResourceTypes
$MultiRegionLocations = & $split $MultiRegionLocations

$context = Get-EsafRegionPolicyContext -SubscriptionId $SubscriptionId -ManagementGroupId $ManagementGroupId `
    -AssignmentScope $AssignmentScope -AssignmentName $AssignmentName -IncludeResourceGroupRule $RestrictResourceGroupLocation

Assert-EsafAzTenant -SubscriptionId $SubscriptionId -TenantId $TenantId

$plan = @(Get-EsafRegionPolicyPlan -Context $context)
$foreign = @($plan | Where-Object State -EQ 'Foreign')
if ($foreign) {
    throw "Not created by this kit, so not overwritten: $(($foreign | ForEach-Object { "$($_.Kind) $($_.Name)" }) -join '; '). Rename or remove them first."
}
$plan | Format-Table Kind, Name, State -AutoSize | Out-String | Write-Host

$target = "assignment '$AssignmentName' at $($context.AssignmentScope) (definitions at $($context.DefinitionScope))"
if ($PSCmdlet.ShouldProcess($target, "Create or update ESAF region policy, enforcement $EnforcementMode")) {
    $assignment = Install-EsafRegionPolicy -Context $context -BaselineLocations $BaselineLocations `
        -MultiRegionResourceTypes $MultiRegionResourceTypes -MultiRegionLocations $MultiRegionLocations `
        -EnforcementMode $EnforcementMode -Effect $Effect
    Write-Host "ESAF region policy is in place: $target, enforcement $EnforcementMode."
    Write-Host "Baseline: $($BaselineLocations -join ', '). $($MultiRegionResourceTypes -join ', '): $($MultiRegionLocations -join ', ')."
    $assignment
}

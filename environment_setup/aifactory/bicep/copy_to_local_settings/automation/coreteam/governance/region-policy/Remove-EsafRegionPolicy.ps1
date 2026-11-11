#Requires -Version 7.0
<#
.SYNOPSIS
    Removes the ESAF region policy that New-EsafRegionPolicy.ps1 created.

.DESCRIPTION
    Deletes, in this order, the assignment, the policy set and the three policy definitions. Only objects
    marked metadata.createdBy = 'esaf-region-policy' are deleted; anything else with the same name is
    reported as skipped. Missing objects are reported as not found. Checks the tenant before any delete.

    Use the same -SubscriptionId, -ManagementGroupId, -AssignmentScope and -AssignmentName as when you
    created it. There are no subscription or tenant defaults.

.EXAMPLE
    ./Remove-EsafRegionPolicy.ps1 -TenantId <tenant-guid> -SubscriptionId <subscription-guid> -WhatIf

.EXAMPLE
    ./Remove-EsafRegionPolicy.ps1 -TenantId <tenant-guid> -SubscriptionId <subscription-guid> -Force
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F-]{36}$')][string] $TenantId,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F-]{36}$')][string] $SubscriptionId,
    [string] $ManagementGroupId,
    [string] $AssignmentScope,
    [ValidateLength(1, 24)][string] $AssignmentName = 'esaf-region-policy',
    # Remove only the assignment; keep the policy set and definitions for another assignment.
    [switch] $KeepDefinitions,
    # Skip the confirmation prompt (pipelines).
    [switch] $Force
)
$ErrorActionPreference = 'Stop'
if ($Force -and -not $WhatIfPreference) { $ConfirmPreference = 'None' }
Import-Module (Join-Path $PSScriptRoot 'EsafRegionPolicy.psm1') -Force

$context = Get-EsafRegionPolicyContext -SubscriptionId $SubscriptionId -ManagementGroupId $ManagementGroupId `
    -AssignmentScope $AssignmentScope -AssignmentName $AssignmentName

Assert-EsafAzTenant -SubscriptionId $SubscriptionId -TenantId $TenantId

$plan = @(Get-EsafRegionPolicyPlan -Context $context -AllDefinitions)
if ($KeepDefinitions) { $plan = @($plan | Where-Object Kind -EQ 'assignment') }

$summary = foreach ($item in $plan) {
    $result = switch ($item.State) {
        'Missing' { 'not found' }
        'Foreign' { 'skipped (not created by this kit)' }
        default {
            if ($PSCmdlet.ShouldProcess("$($item.Kind) $($item.Name)", 'Delete')) {
                Remove-EsafPolicyObject -Item $item -Context $context
                'removed'
            }
            else { 'kept (WhatIf or not confirmed)' }
        }
    }
    [pscustomobject]@{ Kind = $item.Kind; Name = $item.Name; Result = $result }
}
$summary | Format-Table -AutoSize | Out-String | Write-Output

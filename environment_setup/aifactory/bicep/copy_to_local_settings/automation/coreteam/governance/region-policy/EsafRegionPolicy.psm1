#Requires -Version 7.0
<#
.SYNOPSIS
    Shared logic for the ESAF region policy kit (New-EsafRegionPolicy.ps1, Remove-EsafRegionPolicy.ps1).

.DESCRIPTION
    The policy rules live only in ./policies/*.json. This module reads them, talks to Azure through the
    Azure CLI (az) and marks every object it creates with metadata.createdBy = 'esaf-region-policy', so
    the removal script only deletes what this kit made. Every az call names its subscription explicitly
    (several shells and pipelines may share one az login).
#>
Set-StrictMode -Version Latest

$script:Marker = 'esaf-region-policy'
$script:KitVersion = '1.0.0'
$script:PoliciesDir = Join-Path $PSScriptRoot 'policies'
$script:SetName = 'esaf-region-policy'
$script:DefinitionNames = [ordered]@{
    baselineLocations      = 'esaf-allowed-locations-except-types'
    multiRegionTypes       = 'esaf-allowed-locations-for-types'
    resourceGroupLocations = 'esaf-allowed-locations-resource-groups'
}

function Invoke-EsafAz {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string[]] $Arguments,
        [switch] $AllowNotFound
    )
    $all = @($Arguments) + @('--only-show-errors', '-o', 'json')
    $output = & az @all 2>&1
    $exitCode = $LASTEXITCODE
    $stdout = ($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n"
    $stderr = ($output | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() }) -join "`n"
    if ($exitCode -ne 0) {
        if ($AllowNotFound -and $stderr -match 'NotFound|could not be found|was not found|does not exist') { return $null }
        throw "az $($Arguments -join ' ') failed (exit $exitCode): $stderr"
    }
    if ([string]::IsNullOrWhiteSpace($stdout)) { return $null }
    return $stdout | ConvertFrom-Json -Depth 64
}

function Get-EsafRegionPolicyContext {
    <# Resolves names, scopes and the az arguments every call needs. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $SubscriptionId,
        [string] $ManagementGroupId,
        [string] $AssignmentScope,
        [Parameter(Mandatory)][string] $AssignmentName,
        [bool] $IncludeResourceGroupRule = $true
    )
    $subscriptionArgs = @('--subscription', $SubscriptionId)
    if ($ManagementGroupId) {
        $definitionScope = "/providers/Microsoft.Management/managementGroups/$ManagementGroupId"
        $definitionScopeArgs = @('--management-group', $ManagementGroupId)
    }
    else {
        $definitionScope = "/subscriptions/$SubscriptionId"
        $definitionScopeArgs = $subscriptionArgs
    }
    $references = @($script:DefinitionNames.Keys | Where-Object { $IncludeResourceGroupRule -or $_ -ne 'resourceGroupLocations' })
    [pscustomobject]@{
        SubscriptionArgs    = $subscriptionArgs
        DefinitionScope     = $definitionScope
        DefinitionScopeArgs = $definitionScopeArgs
        AssignmentScope     = if ($AssignmentScope) { $AssignmentScope } else { "/subscriptions/$SubscriptionId" }
        AssignmentName      = $AssignmentName
        SetName             = $script:SetName
        SetId               = "$definitionScope/providers/Microsoft.Authorization/policySetDefinitions/$($script:SetName)"
        References          = $references
        DefinitionNames     = @($references | ForEach-Object { $script:DefinitionNames[$_] })
        AllDefinitionNames  = @($script:DefinitionNames.Values)
    }
}

function Assert-EsafAzTenant {
    <# Stops before any write when the az login does not reach the subscription in the expected tenant. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $SubscriptionId, [Parameter(Mandatory)][string] $TenantId)
    $account = Invoke-EsafAz -Arguments @('account', 'show', '--subscription', $SubscriptionId)
    if (-not $account -or $account.tenantId -ne $TenantId) {
        $actual = if ($account) { $account.tenantId } else { 'none' }
        throw "Subscription $SubscriptionId is in tenant '$actual', not the expected tenant '$TenantId'. Run: az login --tenant $TenantId"
    }
}

function Get-EsafPolicyObject {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('definition', 'set-definition', 'assignment')][string] $Kind,
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)] $Context
    )
    $arguments = @('policy', $Kind, 'show', '--name', $Name)
    $arguments += if ($Kind -eq 'assignment') { @('--scope', $Context.AssignmentScope) + $Context.SubscriptionArgs } else { $Context.DefinitionScopeArgs }
    Invoke-EsafAz -Arguments $arguments -AllowNotFound
}

function Test-EsafOwned {
    <# True when the object carries this kit's metadata marker (az returns it flat or under properties). #>
    param($PolicyObject)
    $holders = @($PolicyObject, (Get-EsafMember $PolicyObject 'properties'))
    foreach ($holder in $holders) {
        if ((Get-EsafMember (Get-EsafMember $holder 'metadata') 'createdBy') -eq $script:Marker) { return $true }
    }
    return $false
}

function Get-EsafMember {
    param($Object, [string] $Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Get-EsafRegionPolicyPlan {
    <# Lists every object the kit manages, with its current state: Missing, Owned or Foreign. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] $Context, [switch] $AllDefinitions)
    $items = @([pscustomobject]@{ Kind = 'assignment'; Name = $Context.AssignmentName })
    $items += [pscustomobject]@{ Kind = 'set-definition'; Name = $Context.SetName }
    $names = if ($AllDefinitions) { $Context.AllDefinitionNames } else { $Context.DefinitionNames }
    $items += $names | ForEach-Object { [pscustomobject]@{ Kind = 'definition'; Name = $_ } }
    foreach ($item in $items) {
        $existing = Get-EsafPolicyObject -Kind $item.Kind -Name $item.Name -Context $Context
        $state = if ($null -eq $existing) { 'Missing' } elseif (Test-EsafOwned $existing) { 'Owned' } else { 'Foreign' }
        $item | Add-Member -NotePropertyName State -NotePropertyValue $state -PassThru
    }
}

function Write-EsafJsonFile {
    param([Parameter(Mandatory)] $Value, [Parameter(Mandatory)][string] $Directory, [Parameter(Mandatory)][string] $Name)
    $path = Join-Path $Directory $Name
    $Value | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $path -Encoding utf8NoBOM
    return "@$path"
}

function Read-EsafPolicyFile {
    param([Parameter(Mandatory)][string] $Name)
    Get-Content -Raw -LiteralPath (Join-Path $script:PoliciesDir $Name) | ConvertFrom-Json -Depth 64 -AsHashtable
}

function Install-EsafRegionPolicy {
    <# Creates or updates the definitions, the policy set and the assignment (az create is a PUT). #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Context,
        [Parameter(Mandatory)][string[]] $BaselineLocations,
        [string[]] $MultiRegionResourceTypes = @(),
        [string[]] $MultiRegionLocations = @(),
        [Parameter(Mandatory)][string] $EnforcementMode,
        [Parameter(Mandatory)][string] $Effect
    )
    $work = Join-Path ([System.IO.Path]::GetTempPath()) "esaf-region-policy-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $metadata = Write-EsafJsonFile -Value @{ createdBy = $script:Marker; version = $script:KitVersion } -Directory $work -Name 'metadata.json'
        foreach ($name in $Context.DefinitionNames) {
            $definition = (Read-EsafPolicyFile "$name.json").properties
            $rules = Write-EsafJsonFile -Value $definition.policyRule -Directory $work -Name "$name.rules.json"
            $params = Write-EsafJsonFile -Value $definition.parameters -Directory $work -Name "$name.params.json"
            Invoke-EsafAz -Arguments (@('policy', 'definition', 'create', '--name', $name, '--mode', $definition.mode,
                    '--display-name', $definition.displayName, '--description', $definition.description,
                    '--rules', $rules, '--params', $params, '--metadata', $metadata) + $Context.DefinitionScopeArgs) | Out-Null
        }

        $policySet = (Read-EsafPolicyFile 'esaf-region-policy.policyset.json').properties
        $references = @($policySet.policyDefinitions | Where-Object { $Context.References -contains $_.policyDefinitionReferenceId } | ForEach-Object {
                $_.policyDefinitionId = $_.policyDefinitionId.Replace('{definitionScope}', $Context.DefinitionScope); $_ })
        $definitions = Write-EsafJsonFile -Value $references -Directory $work -Name 'set.definitions.json'
        $setParams = Write-EsafJsonFile -Value $policySet.parameters -Directory $work -Name 'set.params.json'
        Invoke-EsafAz -Arguments (@('policy', 'set-definition', 'create', '--name', $Context.SetName,
                '--display-name', $policySet.displayName, '--description', $policySet.description,
                '--definitions', $definitions, '--params', $setParams, '--metadata', $metadata) + $Context.DefinitionScopeArgs) | Out-Null

        $values = [ordered]@{
            baselineLocations        = @{ value = @($BaselineLocations) }
            multiRegionResourceTypes = @{ value = @($MultiRegionResourceTypes) }
            multiRegionLocations     = @{ value = @($MultiRegionLocations) }
            effect                   = @{ value = $Effect }
        }
        $assignmentParams = Write-EsafJsonFile -Value $values -Directory $work -Name 'assignment.params.json'
        $message = "Allowed regions: $($BaselineLocations -join ', ')."
        if ($MultiRegionResourceTypes) { $message += " $($MultiRegionResourceTypes -join ', ') may also use: $($MultiRegionLocations -join ', ')." }
        $nonCompliance = Write-EsafJsonFile -Value @(@{ message = $message }) -Directory $work -Name 'assignment.messages.json'
        Invoke-EsafAz -Arguments (@('policy', 'assignment', 'create', '--name', $Context.AssignmentName,
                '--display-name', 'ESAF: region policy', '--description', $message,
                '--scope', $Context.AssignmentScope, '--policy-set-definition', $Context.SetId,
                '--params', $assignmentParams, '--enforcement-mode', $EnforcementMode,
                '--non-compliance-messages', $nonCompliance, '--metadata', $metadata) + $Context.SubscriptionArgs)
    }
    finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Remove-EsafPolicyObject {
    [CmdletBinding()]
    param([Parameter(Mandatory)] $Item, [Parameter(Mandatory)] $Context)
    $arguments = @('policy', $Item.Kind, 'delete', '--name', $Item.Name)
    $arguments += if ($Item.Kind -eq 'assignment') { @('--scope', $Context.AssignmentScope) + $Context.SubscriptionArgs } else { $Context.DefinitionScopeArgs }
    Invoke-EsafAz -Arguments $arguments | Out-Null
}

Export-ModuleMember -Function Invoke-EsafAz, Get-EsafRegionPolicyContext, Assert-EsafAzTenant, Get-EsafPolicyObject,
    Test-EsafOwned, Get-EsafRegionPolicyPlan, Install-EsafRegionPolicy, Remove-EsafPolicyObject

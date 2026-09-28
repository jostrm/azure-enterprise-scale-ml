[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ContractPath,
    [string]$ContractReady = $env:PROJECT_LAKE_CONTRACT_READY,
    [string]$Enabled = $env:PROJECT_LAKE_ACCESS_ENABLED,
    [string]$GatewayOnly = $env:PROJECT_LAKE_GATEWAY_ONLY,
    [string]$LegacyLayout = $env:PROJECT_LAKE_LEGACY_LAYOUT,
    [string]$AzureMachineLearningEnabled = $env:PROJECT_LAKE_AML_ENABLED,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-Flag([string]$Value, [bool]$Default, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '^\$\([A-Za-z_]\w*\)$') { return $Default }
    if ($Value -notin @('true', 'false')) { throw "$Name must be true or false." }
    return $Value -eq 'true'
}

$enabledFlag = Read-Flag $Enabled $true 'enableProjectLakeAccess'
$gatewayOnlyFlag = Read-Flag $GatewayOnly $false 'deployOnlyAIGatewayNetworking'
$legacyFlag = Read-Flag $LegacyLayout $false 'projectLakeAccessLegacyLayout'
$amlRequired = Read-Flag $AzureMachineLearningEnabled $false 'enableAzureMachineLearning'
if (-not $enabledFlag -or $gatewayOnlyFlag) {
    Write-Host 'Project lake access disabled explicitly or common deployment is gateway-only.'
    return
}
if (-not (Read-Flag $ContractReady $false 'projectLakeAccessContractReady')) {
    throw 'Project lake access requires successful current-run task 101 outputs; stale deployment outputs are not accepted.'
}
if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) { throw "Missing project lake access contract: $ContractPath" }
$contract = Get-Content -LiteralPath $ContractPath -Raw | ConvertFrom-Json
foreach ($field in @('subscriptionId', 'tenantId', 'storageResourceGroup', 'projectResourceGroup', 'fileSystem', 'project', 'environment', 'projectManagedIdentityObjectId')) {
    if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) { throw "Project lake access contract is missing $field." }
}
if ($contract.enabled -ne $true) { throw 'Project lake access flags do not match the deployment contract.' }
foreach ($id in @($contract.subscriptionId, $contract.tenantId, $contract.projectManagedIdentityObjectId) +
    @($contract.managedIdentityObjectIds) + @($contract.userObjectIds) + @($contract.groupObjectIds) + @($contract.readOnlyObjectIds)) {
    $parsed = [guid]::Empty
    if (-not [guid]::TryParse([string]$id, [ref]$parsed) -or $parsed -eq [guid]::Empty) {
        throw "Invalid principal/subscription/tenant GUID in project lake access contract: $id"
    }
}
if ($contract.projectManagedIdentityObjectId -notin @($contract.managedIdentityObjectIds)) {
    throw 'The resolved project managed identity must be included in the lake ACL principals.'
}

function Invoke-AzJson([string[]]$Arguments) {
    $json = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed while resolving project lake access ($($Arguments[0..1] -join ' '))." }
    return ($json -join "`n" | ConvertFrom-Json)
}

function Get-IdentityProperty($Object, [string[]]$Names) {
    foreach ($name in $Names) {
        if ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$name]) {
            return ,($Object.$name)
        }
    }
    return $null
}

function Assert-PrincipalId([string]$Value, [string]$Resource) {
    $parsed = [guid]::Empty
    if (-not [guid]::TryParse($Value, [ref]$parsed) -or $parsed -eq [guid]::Empty) {
        throw "Missing or invalid managed identity principal ID for '$Resource'."
    }
    return $parsed.ToString()
}

function Resolve-ResourceIdentity($Identity, [string]$Resource, [bool]$Required) {
    $type = [string](Get-IdentityProperty $Identity @('type'))
    if ([string]::IsNullOrWhiteSpace($type) -or $type -eq 'None') {
        if ($Required) { throw "Workspace '$Resource' has no managed identity; lake reader ACLs cannot be provisioned." }
        Write-Host "Compute '$Resource' has no managed identity; no identity ACL to add."
        return
    }
    $normalizedType = $type.ToLowerInvariant() -replace '[^a-z]', ''
    if ($normalizedType -notin @('systemassigned', 'userassigned', 'systemassigneduserassigned')) {
        throw "Unsupported identity type '$type' on '$Resource'."
    }
    if ($normalizedType.Contains('systemassigned')) {
        Assert-PrincipalId (Get-IdentityProperty $Identity @('principalId', 'principal_id')) $Resource
    }
    if ($normalizedType.Contains('userassigned')) {
        $assigned = Get-IdentityProperty $Identity @('userAssignedIdentities', 'user_assigned_identities')
        if ($null -eq $assigned) { throw "No user-assigned identity references returned for '$Resource'." }
        # ARM returns an object keyed by resource ID; az ml returns an array.
        $references = if ($assigned -is [array]) { @($assigned) } else {
            @($assigned.PSObject.Properties | ForEach-Object {
                [pscustomobject]@{
                    resource_id = $_.Name
                    principal_id = Get-IdentityProperty $_.Value @('principalId', 'principal_id')
                }
            })
        }
        if (@($references).Count -eq 0) { throw "No user-assigned identities returned for '$Resource'." }
        foreach ($reference in $references) {
            $principal = Get-IdentityProperty $reference @('principalId', 'principal_id')
            if ([string]::IsNullOrWhiteSpace([string]$principal)) {
                $resourceId = [string](Get-IdentityProperty $reference @('resourceId', 'resource_id'))
                if ($resourceId -notmatch '^/subscriptions/([0-9a-f-]{36})/resourceGroups/[^/]+/providers/Microsoft.ManagedIdentity/userAssignedIdentities/[^/]+$') {
                    throw "Invalid user-assigned identity resource reference on '$Resource': $resourceId"
                }
                $identitySubscription = $Matches[1]
                $resolved = Invoke-AzJson @('identity', 'show', '--ids', $resourceId, '--subscription', $identitySubscription)
                $principal = Get-IdentityProperty $resolved @('principalId', 'principal_id')
            }
            Assert-PrincipalId $principal $Resource
        }
    }
}

$subscription = [string]$contract.subscriptionId
$storageRg = [string]$contract.storageResourceGroup
$account = [string]$contract.storageAccount
if ([string]::IsNullOrWhiteSpace($account)) {
    $candidates = @(Invoke-AzJson @('storage', 'account', 'list', '--subscription', $subscription, '--resource-group', $storageRg) |
        Where-Object { $_.isHnsEnabled -eq $true })
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one HNS-enabled common lake in '$storageRg'; found $($candidates.Count). Set datalakeName_param to the exact existing lake account."
    }
    $account = [string]$candidates[0].name
}
$storage = Invoke-AzJson @('storage', 'account', 'show', '--subscription', $subscription, '--resource-group', $storageRg, '--name', $account)
if ($storage.isHnsEnabled -ne $true) { throw "Storage account '$account' is not an ADLS Gen2 account." }

# Refresh current resources after deployment, including newly created workspaces
# omitted by task 101's predeployment amlExists-based RBAC inputs.
$projectRg = [string]$contract.projectResourceGroup
$workspaceType = 'Microsoft.MachineLearningServices/workspaces'
$workspaces = @(Invoke-AzJson @('resource', 'list', '--subscription', $subscription, '--resource-group', $projectRg, '--resource-type', $workspaceType))
$amlWorkspaces = @($workspaces | Where-Object { (Get-IdentityProperty $_ @('kind')) -notin @('Hub', 'Project') })
if ($amlRequired -and $amlWorkspaces.Count -eq 0) {
    throw "Azure Machine Learning is enabled but no current AML workspace was found in project resource group '$projectRg'."
}
$writers = @($contract.managedIdentityObjectIds)
$readers = @($contract.readOnlyObjectIds)
foreach ($workspace in $amlWorkspaces) {
    $workspaceName = [string](Get-IdentityProperty $workspace @('name'))
    if ([string]::IsNullOrWhiteSpace($workspaceName) -or $workspaceName.Contains('/')) {
        throw "Invalid workspace name returned for project resource group '$projectRg'."
    }
    $current = Invoke-AzJson @('resource', 'show', '--subscription', $subscription, '--resource-group', $projectRg, '--resource-type', $workspaceType, '--name', $workspaceName)
    $readers += @(Resolve-ResourceIdentity (Get-IdentityProperty $current @('identity')) $workspaceName $true)
    $computes = @(Invoke-AzJson @('ml', 'compute', 'list', '--subscription', $subscription, '--resource-group', $projectRg, '--workspace-name', $workspaceName))
    foreach ($compute in $computes) {
        $computeName = [string](Get-IdentityProperty $compute @('name'))
        $writers += @(Resolve-ResourceIdentity (Get-IdentityProperty $compute @('identity')) "$workspaceName/$computeName" $false)
    }
}
$writers = @($writers | Sort-Object -Unique)
# A shared project/compute UAMI retains its explicitly required write access.
$readers = @($readers | Where-Object { $_ -notin $writers } | Sort-Object -Unique)

$aclParameters = @{
    tenantID = [string]$contract.tenantId
    subscriptionID = $subscription
    storageAccount = $account
    storageResourceGroup = $storageRg
    adlsgen2filesystem = [string]$contract.fileSystem
    projectXXX = [string]$contract.project
    environment = [string]$contract.environment
    userObjectIds = @($contract.userObjectIds)
    managedIdentityObjectIds = $writers
    readOnlyObjectIds = $readers
    Execute = $Execute
    LegacyLayout = $legacyFlag
}
# The public ACL utility accepts one project team group per invocation. All IDs
# are validated before the first write; repeat merge-only provisioning for each group.
$groups = @($contract.groupObjectIds)
if ($groups.Count -eq 0) { $groups = @('') }
$aclScript = Join-Path $PSScriptRoot '..\esml-util\25-add-users-to-datalake-acl-rbac.ps1'
foreach ($group in $groups) {
    $aclParameters.projectADGroupObjectId = [string]$group
    try {
        & $aclScript @aclParameters
    }
    catch {
        throw "Project lake ACL provisioning failed for '$account/$($contract.fileSystem)'. The existing deployment identity requires Storage Blob Data Owner on this container, role-assignment permission for container Reader, and private DFS/blob connectivity. No automatic privilege elevation or public-network fallback is performed. $($_.Exception.Message)"
    }
}

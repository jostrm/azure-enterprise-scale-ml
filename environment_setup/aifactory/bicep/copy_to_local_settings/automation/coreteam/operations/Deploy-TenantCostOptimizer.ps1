#Requires -Version 7.6
param(
    [Parameter(Mandatory)][string]$ConfigurationPath,
    [Parameter(Mandatory)][string]$ApprovedPlanHash,
    [switch]$EnableSchedules
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
. "$root\Azure-Control.ps1"
. "$root\Tenant-Cost-Optimizer.ps1"
$configuration = Get-Content -LiteralPath $ConfigurationPath -Raw | ConvertFrom-Json -AsHashtable -DateKind String
Assert-OptimizerConfiguration -Configuration $configuration
if ($ApprovedPlanHash -cne $configuration.planHash) {
    throw 'Approval must match the exact reviewed plan hash. No deployment operations were performed.'
}
$subscriptionScope = "/subscriptions/$($configuration.subscriptionId)"
$groupScope = "$subscriptionScope/resourceGroups/$($configuration.resourceGroup)"
$automationPath = Get-AutomationPath -Configuration $configuration
$tags = @{
    'managed-by' = 'aifactory-cost-optimizer'
    'factory-key' = $configuration.scope.factoryKey
    'environment' = $configuration.scope.environment
    'plan-hash' = $configuration.planHash
}

function Set-OwnedResource {
    param([string]$Path, [string]$ApiVersion, [hashtable]$Body)
    $existing = Invoke-ControlArm -Configuration $configuration -Path $Path -ApiVersion $ApiVersion -ExpectedStatuses @(404)
    if ($existing.status -ne 404 -and
        (-not $existing.json.ContainsKey('tags') -or $existing.json.tags['managed-by'] -ne $tags['managed-by'] -or
        $existing.json.tags['factory-key'] -ne $tags['factory-key'] -or $existing.json.tags['plan-hash'] -ne $tags['plan-hash'])) {
        throw "Resource already exists without this optimizer's ownership tag: $Path"
    }
    $response = Invoke-ControlArm -Configuration $configuration -Path $Path -ApiVersion $ApiVersion -Method Put -Body $Body
    Wait-ControlOperation -Configuration $configuration -Response $response
    return (Invoke-ControlArm -Configuration $configuration -Path $Path -ApiVersion $ApiVersion).json
}

function Set-PowerRole {
    param([string]$Component, [string[]]$Actions)
    $id = Get-DeterministicGuid "$($configuration.subscriptionId)|tenant-cost-optimizer|$Component-role"
    $path = "$subscriptionScope/providers/Microsoft.Authorization/roleDefinitions/$id"
    $null = Invoke-ControlArm -Configuration $configuration -Path $path -ApiVersion '2022-04-01' -Method Put -Body @{
        properties = @{
            roleName = "Tenant Cost Optimizer - $Component ($($configuration.subscriptionId.Substring(0,8)))"
            description = 'Minimum operations at explicitly assigned optimizer resource scopes. No secrets, keys or deletion.'
            type = 'CustomRole'
            assignableScopes = @($subscriptionScope)
            permissions = @(@{ actions = $Actions; notActions = @(); dataActions = @(); notDataActions = @() })
        }
    }
    return $path
}

function Set-ScopedAssignment {
    param([string]$Scope, [string]$Principal, [string]$Role)
    $id = Get-DeterministicGuid "$Scope|$Principal|$Role"
    $null = Invoke-ControlArm -Configuration $configuration `
        -Path "$Scope/providers/Microsoft.Authorization/roleAssignments/$id" -ApiVersion '2022-04-01' -Method Put -Body @{
            properties = @{ principalId = $Principal; principalType = 'ServicePrincipal'; roleDefinitionId = $Role }
        }
}

# The plan and its state are immutable across code-only redeployments.
# Deployment must never strand an outstanding restore by rewriting its assets.
$registration = (Invoke-ControlArm -Configuration $configuration -Path "$subscriptionScope/providers/Microsoft.Automation" -ApiVersion '2021-04-01').json
$existingAccount = if ($registration.registrationState -eq 'Registered') {
    Invoke-ControlArm -Configuration $configuration -Path $automationPath -ExpectedStatuses @(404)
} else {
    @{ status = 404; json = $null }
}
if ($existingAccount.status -ne 404) {
    if ($existingAccount.json.tags['managed-by'] -ne $tags['managed-by'] -or
        $existingAccount.json.tags['plan-hash'] -ne $configuration.planHash) {
        throw 'Automation account belongs to a different owner or reviewed plan. Use an isolated deployment.'
    }
    $existingStatePath = "$groupScope/providers/Microsoft.Storage/storageAccounts/$($configuration.stateStorageAccount)/blobServices/default/containers/$($configuration.stateContainer)"
    $stored = Invoke-ControlArm -Configuration $configuration -Path $existingStatePath -ApiVersion '2023-05-01' -ExpectedStatuses @(404)
    if ($stored.status -ne 404) {
        if ($stored.json.properties.leaseState -ne 'Available') {
            throw 'Optimizer mutex is held. Finish or recover the existing job before redeploying.'
        }
        if ($stored.json.properties.ContainsKey('metadata') -and $stored.json.properties.metadata.ContainsKey('optimizer_checkpoint')) {
            $checkpoint = ConvertFrom-CheckpointMetadata $stored.json.properties.metadata.optimizer_checkpoint
            if (@('Idle', 'Started') -notcontains $checkpoint.phase -or
                $checkpoint.fingerprint -ne (Get-ConfigurationFingerprint $configuration)) {
                throw 'An outstanding or incompatible restore checkpoint exists. Run START/recovery before redeployment.'
            }
        }
    }
    $jobs = (Invoke-ControlArm -Configuration $configuration -Path "$automationPath/jobs").json
    if ($jobs.ContainsKey('nextLink') -and -not [string]::IsNullOrWhiteSpace($jobs.nextLink)) {
        throw 'Job history is paginated. Inspect active jobs before a code update rather than assuming no active job exists.'
    }
    foreach ($job in $jobs.value) {
        if ($job.properties.runbook.name -eq $configuration.runbookName -and
            @('Completed', 'Failed', 'Stopped') -notcontains $job.properties.status) {
            throw 'An optimizer job is still active or suspended. Finish it before redeploying.'
        }
    }
}
foreach ($target in $configuration.targets) {
    $api = if ($target.kind -eq 'ContainerApp') { '2026-07-01' } else { '2024-11-01' }
    $liveTarget = (Invoke-ControlArm -Configuration $configuration -Path $target.id -ApiVersion $api).json
    if ($liveTarget.id -ne $target.id) { throw "The live resource does not match the reviewed target: $($target.id)" }
}

$null = Set-OwnedResource -Path $groupScope -ApiVersion '2024-03-01' -Body @{
    location = $configuration.location
    tags = $tags
}
if ($registration.registrationState -ne 'Registered') {
    $null = Invoke-ControlArm -Configuration $configuration -Path "$subscriptionScope/providers/Microsoft.Automation/register" `
        -ApiVersion '2021-04-01' -Method Post
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(15)
    do {
        Start-Sleep -Seconds 10
        $registration = (Invoke-ControlArm -Configuration $configuration -Path "$subscriptionScope/providers/Microsoft.Automation" -ApiVersion '2021-04-01').json
        if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'Microsoft.Automation provider registration timed out.' }
    } while ($registration.registrationState -ne 'Registered')
}

$previouslyEnabled = @{}
foreach ($name in @($configuration.stopSchedule, $configuration.startSchedule)) {
    $existing = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/schedules/$name" -ExpectedStatuses @(404)
    $previouslyEnabled[$name] = $existing.status -ne 404 -and $existing.json.properties.isEnabled
    if ($previouslyEnabled[$name]) {
        Write-Warning "Pausing $name during deployment; it will be restored only after successful hosted validation."
        $null = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/schedules/$name" -Method Patch -Body @{
            properties = @{ isEnabled = $false }
        }
    }
}

$account = Set-OwnedResource -Path $automationPath -ApiVersion '2024-10-23' -Body @{
    location = $configuration.location
    tags = $tags
    identity = @{ type = 'SystemAssigned' }
    properties = @{ sku = @{ name = 'Basic' }; publicNetworkAccess = $true; disableLocalAuth = $true }
}
$principal = $account.identity.principalId
if ([string]::IsNullOrWhiteSpace($principal)) { throw 'Automation account has no managed identity principal.' }
Write-Host "Automation account: $($configuration.automationAccount); managed identity: $principal"

$storagePath = "$groupScope/providers/Microsoft.Storage/storageAccounts/$($configuration.stateStorageAccount)"
$storage = Set-OwnedResource -Path $storagePath -ApiVersion '2023-05-01' -Body @{
    location = $configuration.location
    tags = $tags
    kind = 'StorageV2'
    sku = @{ name = 'Standard_LRS' }
    properties = @{
        supportsHttpsTrafficOnly = $true
        minimumTlsVersion = 'TLS1_2'
        allowBlobPublicAccess = $false
        allowSharedKeyAccess = $false
        defaultToOAuthAuthentication = $true
        publicNetworkAccess = 'Disabled'
        networkAcls = @{ bypass = 'None'; defaultAction = 'Deny' }
    }
}
$null = Invoke-ControlArm -Configuration $configuration -Path "$storagePath/blobServices/default" -ApiVersion '2023-05-01' -Method Put -Body @{
    properties = @{
        isVersioningEnabled = $true
        deleteRetentionPolicy = @{ enabled = $true; days = 7 }
        containerDeleteRetentionPolicy = @{ enabled = $true; days = 7 }
    }
}
$containerPath = "$storagePath/blobServices/default/containers/$($configuration.stateContainer)"
$container = Invoke-ControlArm -Configuration $configuration -Path $containerPath -ApiVersion '2023-05-01' -ExpectedStatuses @(404)
if ($container.status -eq 404) {
    $null = Invoke-ControlArm -Configuration $configuration -Path $containerPath -ApiVersion '2023-05-01' -Method Put -Body @{
        properties = @{ publicAccess = 'None' }
    }
}
$vmRole = Set-PowerRole -Component 'VM power' -Actions @(
    'Microsoft.Compute/virtualMachines/read',
    'Microsoft.Compute/virtualMachines/instanceView/read',
    'Microsoft.Compute/virtualMachines/deallocate/action',
    'Microsoft.Compute/virtualMachines/start/action'
)
$appRole = Set-PowerRole -Component 'Container App power' -Actions @(
    'Microsoft.App/containerapps/read',
    'Microsoft.App/containerapps/revisions/read',
    'Microsoft.App/containerapps/stop/action',
    'Microsoft.App/containerapps/start/action'
)
foreach ($target in $configuration.targets) {
    $role = if ($target.kind -eq 'VirtualMachine') { $vmRole } else { $appRole }
    Set-ScopedAssignment -Scope $target.id -Principal $principal -Role $role
}
$stateRole = Set-PowerRole -Component 'State container' -Actions @(
    'Microsoft.Storage/storageAccounts/blobServices/containers/read',
    'Microsoft.Storage/storageAccounts/blobServices/containers/write',
    'Microsoft.Storage/storageAccounts/blobServices/containers/lease/action'
)
Set-ScopedAssignment -Scope $containerPath -Principal $principal -Role $stateRole
$jobRole = Set-PowerRole -Component 'Own job history' -Actions @(
    'Microsoft.Automation/automationAccounts/jobs/read'
)
Set-ScopedAssignment -Scope $automationPath -Principal $principal -Role $jobRole
$null = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/runtimeEnvironments/$($configuration.runtimeName)" -Method Put -Body @{
    location = $configuration.location
    properties = @{ runtime = @{ language = 'PowerShell'; version = '7.6' } }
}
$configurationText = $configuration | ConvertTo-Json -Depth 15 -Compress
$null = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/variables/$($configuration.configurationVariable)" -Method Put -Body @{
    name = $configuration.configurationVariable
    properties = @{
        description = 'Approved allowlist, DST-aware schedule and state storage. No credentials.'
        isEncrypted = $false
        value = (ConvertTo-Json -InputObject $configurationText -Compress)
    }
}
$runbookPath = "$automationPath/runbooks/$($configuration.runbookName)"
$null = Invoke-ControlArm -Configuration $configuration -Path $runbookPath -Method Put -Body @{
    location = $configuration.location
    tags = $tags
    properties = @{
        runbookType = 'PowerShell'
        runtimeEnvironment = $configuration.runtimeName
        description = "Stateful STOP/START of $($configuration.targets.Count) reviewed development resources. AKS excluded. Default Preview."
        logVerbose = $false
        logProgress = $false
        draft = @{}
    }
}
$response = Invoke-ControlArm -Configuration $configuration -Path "$runbookPath/draft/content" -Method Put `
    -Body (Get-Content -LiteralPath "$root\Tenant-Cost-Optimizer.ps1" -Raw) -ContentType 'text/plain; charset=utf-8'
Wait-ControlOperation -Configuration $configuration -Response $response
$response = Invoke-ControlArm -Configuration $configuration -Path "$runbookPath/publish" -Method Post
Wait-ControlOperation -Configuration $configuration -Response $response
$deadline = [DateTimeOffset]::UtcNow.AddMinutes(10)
do {
    $runbook = (Invoke-ControlArm -Configuration $configuration -Path $runbookPath).json
    if ($runbook.properties.state -eq 'Published') { break }
    if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'Runbook did not reach Published state.' }
    Start-Sleep -Seconds 5
} while ($true)

foreach ($action in @('STOP', 'START')) {
    $name = if ($action -eq 'STOP') { $configuration.stopSchedule } else { $configuration.startSchedule }
    $firstTime = if ($action -eq 'STOP') { $configuration.firstStop } else { $configuration.firstStart }
    $schedulePath = "$automationPath/schedules/$name"
    $existing = Invoke-ControlArm -Configuration $configuration -Path $schedulePath -ExpectedStatuses @(404)
    if ($existing.status -eq 404) {
        if ([DateTimeOffset]::Parse($firstTime) -le [DateTimeOffset]::UtcNow.AddMinutes(5)) {
            throw "Initial $action schedule time must be in the future: $firstTime"
        }
        $null = Invoke-ControlArm -Configuration $configuration -Path $schedulePath -Method Put -Body @{
            name = $name
            properties = @{
                description = "$action approved targets in $($configuration.timeZone), following daylight saving where applicable."
                startTime = $firstTime
                frequency = 'Day'
                interval = 1
                timeZone = $configuration.timeZone
                isEnabled = $false
            }
        }
    } else {
        $zone = [TimeZoneInfo]::FindSystemTimeZoneById($configuration.timeZone)
        $existingTime = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Parse($existing.json.properties.startTime), $zone).ToString('HH:mm')
        $desiredTime = [DateTimeOffset]::Parse($firstTime).ToString('HH:mm')
        if ($existing.json.properties.timeZone -ne $configuration.timeZone -or $existingTime -ne $desiredTime -or
            $existing.json.properties.frequency -ne 'Day' -or $existing.json.properties.interval -ne 1) {
            throw "Existing $name has different timing. Recreate it deliberately rather than silently ignoring configuration changes."
        }
    }
    $null = Invoke-ControlArm -Configuration $configuration -Path $schedulePath -Method Patch -Body @{
        properties = @{ isEnabled = $false }
    }
    $gated = (Invoke-ControlArm -Configuration $configuration -Path $schedulePath).json
    if ($gated.properties.isEnabled) { throw "Schedule $name did not become disabled; refusing to link or validate live execution." }
    $links = (Invoke-ControlArm -Configuration $configuration -Path "$automationPath/jobSchedules").json.value
    $matching = @($links | Where-Object {
        $_.properties.schedule.name -eq $name -and $_.properties.runbook.name -eq $configuration.runbookName
    })
    if ($matching.Count -gt 1) { throw "Duplicate optimizer bindings exist for $name; refusing to enable them." }
    if ($matching.Count -eq 1) {
        $detail = (Invoke-ControlArm -Configuration $configuration -Path $matching[0].id).json
        if ($detail.properties.parameters.Action -ne $action -or $detail.properties.parameters.Mode -ne 'Live') {
            $null = Invoke-ControlArm -Configuration $configuration -Path $matching[0].id -Method Delete
            $matching = @()
        }
    }
    if ($matching.Count -eq 0) {
        $linkId = Get-DeterministicGuid "$automationPath|$name|$($configuration.runbookName)"
        $created = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/jobSchedules/$linkId" -Method Put -Body @{
            properties = @{
                runbook = @{ name = $configuration.runbookName }
                schedule = @{ name = $name }
                parameters = @{ Action = $action; Mode = 'Live' }
            }
        }
        $detail = (Invoke-ControlArm -Configuration $configuration -Path $created.json.id).json
    }
    if ($detail.properties.parameters.Action -ne $action -or $detail.properties.parameters.Mode -ne 'Live') {
        throw "Schedule $name did not persist its explicit $action / Live parameters."
    }
}

Write-Host 'Published. Both schedules are disabled until hosted previews succeed.'
foreach ($action in @('STOP', 'START', 'VERIFY')) {
    $mode = if ($action -eq 'VERIFY') { 'Live' } else { 'Preview' }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        try {
            $null = Invoke-HostedOptimizerJob -Configuration $configuration -Action $action -Mode $mode
            break
        } catch {
            if ($_.Exception.Message -notmatch 'HTTP 403' -or $attempt -eq 4) { throw }
            Write-Warning 'Waiting for the new managed identity permissions to propagate; no target actions were performed.'
            Start-Sleep -Seconds 30
        }
    }
}
foreach ($name in @($configuration.stopSchedule, $configuration.startSchedule)) {
    if ($EnableSchedules -or $previouslyEnabled[$name]) {
        $null = Invoke-ControlArm -Configuration $configuration -Path "$automationPath/schedules/$name" -Method Patch -Body @{
            properties = @{ isEnabled = $true }
        }
    }
}
if ($EnableSchedules -or @($previouslyEnabled.Values | Where-Object { $_ }).Count -gt 0) {
    Write-Host "Enabled STOP $($configuration.stopTime) / START $($configuration.startTime) in $($configuration.timeZone). No live target STOP/START was executed during deployment."
} else {
    Write-Host 'Both schedules remain disabled. Redeploy with -EnableSchedules to enable the approved daily schedule.'
}

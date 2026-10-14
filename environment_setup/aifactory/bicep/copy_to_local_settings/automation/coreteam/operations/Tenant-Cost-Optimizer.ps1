#Requires -Version 7.6
param(
    [ValidateSet('STOP', 'START', 'STATUS', 'VERIFY')]
    [string]$Action = 'STATUS',
    [ValidateSet('Preview', 'Live')]
    [string]$Mode = 'Preview'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-OptimizerConfiguration {
    param([hashtable]$Configuration)
    $fields = @(
        'schemaVersion', 'tenantId', 'subscriptionId', 'location', 'resourceGroup',
        'automationAccount', 'runbookName', 'runtimeName', 'configurationVariable',
        'stateStorageAccount', 'stateContainer', 'stateTransport', 'timeZone',
        'firstStop', 'firstStart', 'stopTime', 'startTime', 'stopSchedule',
        'startSchedule', 'operationTimeoutSeconds', 'scope', 'targets', 'planHash'
    )
    Assert-OptimizerObjectFields -Value $Configuration -Fields $fields -Label 'configuration'
    if (-not (Test-OptimizerInteger $Configuration.schemaVersion) -or $Configuration.schemaVersion -ne 2) {
        throw [InvalidOperationException]::new('Expected optimizer configuration schema 2.')
    }
    foreach ($field in @('tenantId', 'subscriptionId')) {
        Assert-OptimizerString -Value $Configuration[$field] -Pattern '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' -Label $field
        if ([Guid]$Configuration[$field] -eq [Guid]::Empty) {
            throw [InvalidOperationException]::new("$field must not be the empty GUID.")
        }
    }
    Assert-OptimizerString $Configuration.location '^[a-z][a-z0-9]{1,63}$' 'location'
    Assert-OptimizerString $Configuration.resourceGroup '^[A-Za-z0-9_.()-]{1,90}(?<!\.)$' 'resourceGroup'
    Assert-OptimizerString $Configuration.automationAccount '^[A-Za-z][A-Za-z0-9-]{4,48}[A-Za-z0-9]$' 'automationAccount'
    Assert-OptimizerString $Configuration.stateStorageAccount '^[a-z0-9]{3,24}$' 'stateStorageAccount'
    if ($Configuration.resourceGroup -cnotmatch '^aif-cost-opt-([0-9a-f]{12})-rg$') {
        throw [InvalidOperationException]::new('Optimizer hosting requires a dedicated aif-cost-opt-<12hex>-rg resource group.')
    }
    $hostingKey = $Matches[1]
    if ($Configuration.automationAccount -cne "aa-aif-cost-opt-$hostingKey" -or
        $Configuration.stateStorageAccount -cne "staifcost$hostingKey") {
        throw [InvalidOperationException]::new('Optimizer account and state storage must use the dedicated hosting key.')
    }
    $constants = @{
        runbookName = 'Tenant-Cost-Optimizer'
        runtimeName = 'CostOptimizer-PowerShell76'
        configurationVariable = 'CostOptimizerConfiguration'
        stateContainer = 'cost-optimizer-state'
        stateTransport = 'ArmContainerMetadata'
    }
    foreach ($field in $constants.Keys) {
        if ($Configuration[$field] -isnot [string] -or $Configuration[$field] -cne $constants[$field]) {
            throw [InvalidOperationException]::new("Unsupported optimizer $field.")
        }
    }
    foreach ($field in @('stopSchedule', 'startSchedule')) {
        Assert-OptimizerString $Configuration[$field] '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' $field
    }
    if ($Configuration.stopSchedule -eq $Configuration.startSchedule) {
        throw [InvalidOperationException]::new('STOP and START schedules must have different names.')
    }
    foreach ($field in @('stopTime', 'startTime')) {
        Assert-OptimizerString $Configuration[$field] '^([01][0-9]|2[0-3]):[0-5][0-9]$' $field
    }
    if ($Configuration.stopTime -eq $Configuration.startTime) {
        throw [InvalidOperationException]::new('STOP and START must have different local times.')
    }
    foreach ($field in @('firstStop', 'firstStart')) {
        Assert-OptimizerString $Configuration[$field] '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,7})?(Z|[+-][0-9]{2}:[0-9]{2})$' $field
        $parsed = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse($Configuration[$field], [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
            throw [InvalidOperationException]::new("Invalid offset-qualified date: $field.")
        }
    }
    Assert-OptimizerString $Configuration.timeZone '^[A-Za-z0-9_+./ ()-]{1,128}$' 'timeZone'
    try { $null = [TimeZoneInfo]::FindSystemTimeZoneById($Configuration.timeZone) } catch {
        throw [InvalidOperationException]::new('timeZone must be a valid IANA or Windows time zone.')
    }
    if (-not (Test-OptimizerInteger $Configuration.operationTimeoutSeconds) -or
        $Configuration.operationTimeoutSeconds -lt 60 -or $Configuration.operationTimeoutSeconds -gt 3600) {
        throw [InvalidOperationException]::new('Operation timeout must be an integer between 60 and 3600 seconds.')
    }
    Assert-OptimizerObjectFields $Configuration.scope @('factoryKey', 'environment', 'resourceGroups', 'variablesSha256') 'scope'
    Assert-OptimizerString $Configuration.scope.factoryKey '^[0-9a-f]{12}$' 'scope.factoryKey'
    Assert-OptimizerString $Configuration.scope.variablesSha256 '^[0-9a-f]{64}$' 'scope.variablesSha256'
    if ($Configuration.scope.environment -isnot [string] -or @('dev', 'test') -cnotcontains $Configuration.scope.environment) {
        throw [InvalidOperationException]::new('Only explicit dev or test environment scopes are supported; prod is not supported.')
    }
    if ($Configuration.scope.resourceGroups -isnot [Collections.IList] -or $Configuration.scope.resourceGroups.Count -lt 1) {
        throw [InvalidOperationException]::new('Scope must contain an exact resource-group allowlist.')
    }
    $groups = @{}
    foreach ($group in $Configuration.scope.resourceGroups) {
        Assert-OptimizerString $group '^[A-Za-z0-9_.()-]{1,90}(?<!\.)$' 'scope.resourceGroups entry'
        if ($groups.ContainsKey($group) -or $group -eq $Configuration.resourceGroup) {
            throw [InvalidOperationException]::new('Duplicate scope group or optimizer hosting group in target scope.')
        }
        $groups[$group] = $true
    }
    if ($Configuration.targets -isnot [Collections.IList] -or
        $Configuration.targets.Count -lt 1 -or $Configuration.targets.Count -gt 16) {
        throw [InvalidOperationException]::new('A reviewed plan must contain between 1 and 16 exact targets.')
    }
    $seen = @{}
    foreach ($target in $Configuration.targets) {
        Assert-OptimizerObjectFields $target @('kind', 'id') 'target'
        $pattern = '^/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([^/]+)/providers/(Microsoft\.App/containerApps|Microsoft\.Compute/virtualMachines)/([^/]+)$'
        if ($target.id -isnot [string] -or $target.id -notmatch $pattern -or
            $Matches[1] -ne $Configuration.subscriptionId) {
            throw [InvalidOperationException]::new("Unapproved resource ID: $($target.id)")
        }
        $provider = $Matches[3]
        $group = $Matches[2]
        $name = $Matches[4]
        $kind = if ($provider -eq 'Microsoft.App/containerApps') { 'ContainerApp' } else { 'VirtualMachine' }
        $namePattern = if ($kind -eq 'ContainerApp') { '^[a-z][a-z0-9-]{0,30}[a-z0-9]$' } else { '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}(?<!\.)$' }
        Assert-OptimizerString $name $namePattern 'target resource name'
        if (($kind -eq 'ContainerApp' -and $name.Contains('--')) -or
            $target.kind -isnot [string] -or $target.kind -cne $kind -or
            -not $groups.ContainsKey($group) -or $seen.ContainsKey($target.id)) {
            throw [InvalidOperationException]::new("Unapproved or duplicate target: $($target.id)")
        }
        $seen[$target.id] = $true
    }
    Assert-OptimizerString $Configuration.planHash '^[0-9a-f]{64}$' 'planHash'
    if ($Configuration.planHash -cne (Get-CostOptimizerPlanHash $Configuration)) {
        throw [InvalidOperationException]::new('Reviewed plan hash does not match the configuration.')
    }
}

function Assert-OptimizerObjectFields {
    param($Value, [string[]]$Fields, [string]$Label)
    if ($Value -isnot [Collections.IDictionary] -or $Value.Count -ne $Fields.Count) {
        throw [InvalidOperationException]::new("Invalid $Label fields.")
    }
    foreach ($field in $Fields) {
        if (-not $Value.Contains($field)) { throw [InvalidOperationException]::new("Missing $Label field: $field.") }
    }
    foreach ($key in $Value.Keys) {
        if ($key -isnot [string] -or $Fields -cnotcontains $key) {
            throw [InvalidOperationException]::new("Unexpected $Label field.")
        }
    }
}

function Assert-OptimizerString {
    param($Value, [string]$Pattern, [string]$Label)
    if ($Value -isnot [string] -or $Value -cnotmatch $Pattern -or
        $Value -match '(?i)(placeholder|changeme|replace[-_]?me|your[-_](tenant|subscription|resource|factory|storage|account))') {
        throw [InvalidOperationException]::new("Invalid literal $Label.")
    }
}

function Test-OptimizerInteger {
    param($Value)
    return $Value -is [byte] -or $Value -is [sbyte] -or $Value -is [int16] -or
        $Value -is [uint16] -or $Value -is [int32] -or $Value -is [uint32] -or
        $Value -is [int64] -or $Value -is [uint64]
}

function ConvertTo-OptimizerCanonicalJson {
    param([AllowNull()]$Value, [int]$Depth = 0)
    if ($Depth -gt 64) { throw [InvalidOperationException]::new('Configuration nesting limit exceeded.') }
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [Collections.IDictionary]) {
        [string[]]$keys = @($Value.Keys)
        foreach ($key in $Value.Keys) {
            if ($key -isnot [string]) { throw [InvalidOperationException]::new('JSON object keys must be strings.') }
        }
        [Array]::Sort($keys, [StringComparer]::Ordinal)
        $parts = foreach ($key in $keys) {
            ($key | ConvertTo-Json -Compress) + ':' + (ConvertTo-OptimizerCanonicalJson -Value $Value[$key] -Depth ($Depth + 1))
        }
        return '{' + ($parts -join ',') + '}'
    }
    if ($Value -is [Collections.IList]) {
        $parts = foreach ($item in $Value) { ConvertTo-OptimizerCanonicalJson -Value $item -Depth ($Depth + 1) }
        return '[' + ($parts -join ',') + ']'
    }
    if ($Value -is [string] -or $Value -is [bool] -or (Test-OptimizerInteger $Value) -or
        $Value -is [decimal] -or $Value -is [double] -or $Value -is [single]) {
        if (($Value -is [double] -or $Value -is [single]) -and
            ([double]::IsNaN($Value) -or [double]::IsInfinity($Value))) {
            throw [InvalidOperationException]::new('Non-finite numbers are not JSON configuration values.')
        }
        return ConvertTo-Json -InputObject $Value -Compress
    }
    throw [InvalidOperationException]::new('Configuration contains a non-JSON value.')
}

function Get-CostOptimizerPlanHash {
    param([hashtable]$Configuration)
    $plan = [Collections.Specialized.OrderedDictionary]::new([StringComparer]::Ordinal)
    foreach ($key in $Configuration.Keys) {
        if ($key -cne 'planHash') { $plan[$key] = $Configuration[$key] }
    }
    $text = ConvertTo-OptimizerCanonicalJson $plan
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($text))).ToLowerInvariant()
}

function Get-ConfigurationFingerprint {
    param([hashtable]$Configuration)
    [string[]]$groups = @($Configuration.scope.resourceGroups | ForEach-Object { $_.ToLowerInvariant() })
    [string[]]$targets = @($Configuration.targets | ForEach-Object { "$($_.kind)|$($_.id.ToLowerInvariant())" })
    [Array]::Sort($groups, [StringComparer]::Ordinal)
    [Array]::Sort($targets, [StringComparer]::Ordinal)
    $binding = @{
        tenantId = $Configuration.tenantId.ToLowerInvariant()
        subscriptionId = $Configuration.subscriptionId.ToLowerInvariant()
        factoryKey = $Configuration.scope.factoryKey
        environment = $Configuration.scope.environment
        resourceGroups = $groups
        targets = $targets
        resourceGroup = $Configuration.resourceGroup.ToLowerInvariant()
        automationAccount = $Configuration.automationAccount.ToLowerInvariant()
        runbookName = $Configuration.runbookName
        configurationVariable = $Configuration.configurationVariable
        stateStorageAccount = $Configuration.stateStorageAccount
        stateContainer = $Configuration.stateContainer
        stateTransport = $Configuration.stateTransport
    }
    $text = ConvertTo-OptimizerCanonicalJson $binding
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

function Get-AppRoutingFingerprint {
    param([hashtable]$App)
    $routes = @($App.properties.configuration.ingress.traffic | ForEach-Object {
        [ordered]@{
            revisionName = $_['revisionName']
            latestRevision = $_['latestRevision']
            label = $_['label']
            weight = $_['weight']
        }
    } | Sort-Object { "$($_.label)|$($_.revisionName)|$($_.latestRevision)" })
    $text = ConvertTo-Json -InputObject $routes -Depth 5 -Compress
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($text)))
}

function Get-ManagedIdentityToken {
    param([string]$Audience)
    if ($script:Tokens.ContainsKey($Audience) -and
        $script:Tokens[$Audience].expires -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
        return $script:Tokens[$Audience].token
    }
    if ([string]::IsNullOrWhiteSpace($env:IDENTITY_ENDPOINT) -or
        [string]::IsNullOrWhiteSpace($env:IDENTITY_HEADER)) {
        throw [InvalidOperationException]::new('Azure Automation managed identity is unavailable.')
    }
    $separator = if ($env:IDENTITY_ENDPOINT.Contains('?')) { '&' } else { '?' }
    $uri = "$($env:IDENTITY_ENDPOINT)${separator}resource=$([Uri]::EscapeDataString($Audience))"
    $response = Invoke-WebRequest -Uri $uri -Method Get -TimeoutSec 15 -SkipHttpErrorCheck -Headers @{
        'X-IDENTITY-HEADER' = $env:IDENTITY_HEADER
        Metadata = 'True'
    }
    if ($response.StatusCode -ne 200) {
        throw [InvalidOperationException]::new("Managed identity token request failed: HTTP $($response.StatusCode).")
    }
    $data = $response.Content | ConvertFrom-Json -AsHashtable
    $expires = [DateTimeOffset]::FromUnixTimeSeconds([long]$data.expires_on)
    $script:Tokens[$Audience] = @{ token = $data.access_token; expires = $expires }
    return $data.access_token
}

function Invoke-StateLeaseAction {
    param([hashtable]$Body, [int[]]$ExpectedStatuses = @())
    return Invoke-OptimizerRequest -Uri "$($script:StateContainerUri)/lease?api-version=2023-05-01" `
        -Method Post -Body ($Body | ConvertTo-Json -Compress) -NoLeaseRenewal -ExpectedStatuses $ExpectedStatuses
}

function Update-StateLease {
    param([switch]$Force)
    if ($null -ne $script:Lease -and
        ($Force -or $script:Lease.lastVerified -lt [DateTimeOffset]::UtcNow.AddSeconds(-30))) {
        $null = Invoke-StateLeaseAction -Body @{ action = 'Renew'; leaseId = $script:Lease.id }
        $script:Lease.lastVerified = [DateTimeOffset]::UtcNow
    }
}

function Invoke-OptimizerRequest {
    param(
        [string]$Uri,
        [ValidateSet('Get', 'Post', 'Put', 'Patch')][string]$Method = 'Get',
        [string]$Audience = 'https://management.azure.com/',
        [hashtable]$Headers = @{},
        [AllowNull()][string]$Body = $null,
        [int[]]$ExpectedStatuses = @(),
        [switch]$NoLeaseRenewal,
        [switch]$NoRetry
    )
    if ($Method -ne 'Get' -and $script:Mode -ne 'Live') {
        throw [InvalidOperationException]::new('Preview cannot perform HTTP mutations.')
    }
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        if (-not $NoLeaseRenewal) { Update-StateLease -Force:($Method -ne 'Get') }
        $requestHeaders = @{
            Authorization = "Bearer $(Get-ManagedIdentityToken -Audience $Audience)"
        }
        if ($Audience -eq 'https://storage.azure.com/') {
            $requestHeaders['x-ms-version'] = '2023-11-03'
            $requestHeaders['x-ms-date'] = [DateTime]::UtcNow.ToString('R')
        }
        foreach ($key in $Headers.Keys) { $requestHeaders[$key] = $Headers[$key] }
        $parameters = @{
            Uri = $Uri
            Method = $Method
            Headers = $requestHeaders
            TimeoutSec = 15
            SkipHttpErrorCheck = $true
            MaximumRedirection = 0
        }
        if ($null -ne $Body) {
            $parameters.Body = [Text.Encoding]::UTF8.GetBytes($Body)
            $parameters.ContentType = 'application/json; charset=utf-8'
        }
        $response = Invoke-WebRequest @parameters
        $status = [int]$response.StatusCode
        $content = if ($response.Content -is [byte[]]) {
            [Text.Encoding]::UTF8.GetString($response.Content)
        } else { [string]$response.Content }
        if (($status -ge 200 -and $status -lt 300) -or $ExpectedStatuses -contains $status) {
            $json = if ($status -lt 200 -or $status -ge 300 -or [string]::IsNullOrWhiteSpace($content)) {
                $null
            } else {
                $content | ConvertFrom-Json -AsHashtable -DateKind String
            }
            return @{ status = $status; headers = $response.Headers; json = $json }
        }
        if ($status -eq 401 -and $attempt -lt 3 -and -not $NoRetry) {
            $script:Tokens.Remove($Audience)
            continue
        }
        if (@(408, 429, 500, 502, 503, 504) -contains $status -and $attempt -lt 3 -and -not $NoRetry) {
            Update-StateLease
            Start-Sleep -Seconds ([Math]::Min(5, [Math]::Pow(2, $attempt)))
            continue
        }
        throw [InvalidOperationException]::new("$Method $Uri failed: HTTP $status. No credentials or response body were logged.")
    }
    throw [InvalidOperationException]::new("Request retry limit exceeded: $Method $Uri")
}

function Invoke-ArmRequest {
    param([string]$Path, [string]$Method = 'Get', [string]$ApiVersion = '2026-07-01')
    return Invoke-OptimizerRequest -Uri "https://management.azure.com${Path}?api-version=$ApiVersion" -Method $Method
}

function Get-AppRevisions {
    param([string]$Id)
    $uri = "https://management.azure.com${Id}/revisions?api-version=2026-07-01"
    $results = [Collections.Generic.List[object]]::new()
    for ($page = 0; $page -lt 100; $page++) {
        $data = (Invoke-OptimizerRequest -Uri $uri).json
        foreach ($revision in $data.value) { $results.Add($revision) }
        if (-not $data.ContainsKey('nextLink') -or [string]::IsNullOrWhiteSpace($data.nextLink)) {
            return ,$results.ToArray()
        }
        if ($data.nextLink -notlike "https://management.azure.com${Id}/revisions?*") {
            throw [InvalidOperationException]::new('Unexpected Container Apps pagination URL.')
        }
        $uri = $data.nextLink
    }
    throw [InvalidOperationException]::new('Container Apps revision pagination limit exceeded.')
}

function Get-VmPowerState {
    param([string]$Id)
    $vm = (Invoke-ArmRequest -Path "$Id/instanceView" -ApiVersion '2024-11-01').json
    $codes = @($vm.statuses | ForEach-Object { $_.code } | Where-Object { $_ -like 'PowerState/*' })
    if ($codes.Count -ne 1) {
        throw [InvalidOperationException]::new("Cannot determine VM power state: $Id")
    }
    return $codes[0]
}

function New-IdleState {
    param([string]$Fingerprint)
    return @{
        schemaVersion = 1
        fingerprint = $Fingerprint
        cycleId = $null
        phase = 'Idle'
        updatedUtc = [DateTimeOffset]::UtcNow.ToString('o')
        targets = @()
    }
}

function ConvertTo-CheckpointMetadata {
    param([hashtable]$State)
    $json = $State | ConvertTo-Json -Depth 25 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    if ($bytes.Length -gt 262144) {
        throw [InvalidOperationException]::new('Uncompressed checkpoint exceeds the checkpoint decompression limit.')
    }
    $stream = [IO.MemoryStream]::new()
    $gzip = [IO.Compression.GZipStream]::new($stream, [IO.Compression.CompressionLevel]::Optimal, $true)
    try { $gzip.Write($bytes, 0, $bytes.Length) } finally { $gzip.Dispose() }
    try { $encoded = [Convert]::ToBase64String($stream.ToArray()) } finally { $stream.Dispose() }
    if ($encoded.Length -gt 7000) {
        throw [InvalidOperationException]::new('Compressed checkpoint exceeds the safe container metadata limit.')
    }
    return $encoded
}

function ConvertFrom-CheckpointMetadata {
    param([string]$Encoded)
    $inputStream = [IO.MemoryStream]::new([Convert]::FromBase64String($Encoded))
    $gzip = [IO.Compression.GZipStream]::new($inputStream, [IO.Compression.CompressionMode]::Decompress)
    $output = [IO.MemoryStream]::new()
    try {
        $buffer = [byte[]]::new(4096)
        while (($count = $gzip.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $output.Write($buffer, 0, $count)
            if ($output.Length -gt 262144) { throw [InvalidOperationException]::new('Checkpoint decompression limit exceeded.') }
        }
        return [Text.Encoding]::UTF8.GetString($output.ToArray()) | ConvertFrom-Json -AsHashtable -DateKind String
    } finally {
        $gzip.Dispose()
        $inputStream.Dispose()
        $output.Dispose()
    }
}

function Get-StateContainer {
    return (Invoke-OptimizerRequest -Uri "$($script:StateContainerUri)?api-version=2023-05-01").json
}

function Read-OptimizerState {
    $container = Get-StateContainer
    $metadata = if ($container.properties.ContainsKey('metadata')) { $container.properties.metadata } else { @{} }
    if (-not $metadata.ContainsKey('optimizer_checkpoint')) {
        return @{ exists = $false; data = (New-IdleState -Fingerprint $script:Fingerprint) }
    }
    $state = ConvertFrom-CheckpointMetadata -Encoded $metadata.optimizer_checkpoint
    if (-not (Test-OptimizerInteger $state.schemaVersion) -or $state.schemaVersion -ne 1 -or
        $state.fingerprint -isnot [string] -or $state.phase -isnot [string] -or
        $state.fingerprint -cnotmatch '^[0-9a-f]{64}$' -or $state.targets -isnot [Collections.IList] -or
        $state.targets.Count -gt 16 -or
        @('Idle', 'Stopping', 'Stopped', 'StopFailed', 'Starting', 'Started', 'StartFailed') -cnotcontains $state.phase) {
        throw [InvalidOperationException]::new('Checkpoint is incompatible. Do not overwrite an outstanding STOP snapshot.')
    }
    foreach ($target in $state.targets) {
        if ($target -isnot [Collections.IDictionary] -or $target.id -isnot [string] -or
            @('ContainerApp', 'VirtualMachine') -cnotcontains $target.kind -or
            @('Skipped', 'PendingStop', 'StopRequested', 'Stopped', 'StopFailed', 'StartRequested', 'Started', 'StartFailed') -cnotcontains $target.status) {
            throw [InvalidOperationException]::new('Checkpoint contains an invalid target or action status.')
        }
        if ($target.shouldRestore -isnot [bool] -or $target.stopAttempted -isnot [bool] -or
            $target.stopAccepted -isnot [bool]) {
            throw [InvalidOperationException]::new('Checkpoint ownership flags must be booleans.')
        }
        if (($target.stopAccepted -and -not $target.stopAttempted) -or
            (-not $target.shouldRestore -and ($target.stopAttempted -or $target.stopAccepted))) {
            throw [InvalidOperationException]::new('Checkpoint claims STOP ownership without a recorded attempt.')
        }
        if ($target.shouldRestore) {
            $originallyRunning = if ($target.kind -eq 'VirtualMachine') {
                $target.originalPowerState -eq 'PowerState/running'
            } else {
                $target.originalRunningStatus -eq 'Running' -and $target.revisions.Count -gt 0
            }
            if (-not $originallyRunning) {
                throw [InvalidOperationException]::new('Checkpoint attempts to restore a resource that was already off.')
            }
        }
    }
    $outstanding = @($state.targets | Where-Object {
        $_.shouldRestore -and $_.status -ne 'Started' -and
            ($_.stopAttempted -or $_.status -ne 'Skipped')
    }).Count -gt 0
    if (($state.phase -eq 'Idle' -and $state.targets.Count -gt 0) -or
        ($state.phase -eq 'Started' -and $outstanding)) {
        throw [InvalidOperationException]::new('Terminal checkpoint has outstanding resource restoration; refusing to reset it.')
    }
    if ($state.fingerprint -cne $script:Fingerprint) {
        if (@('Idle', 'Started') -notcontains $state.phase -or $outstanding) {
            throw [InvalidOperationException]::new('Checkpoint scope changed with an outstanding STOP snapshot; restore the previous scope before replacing it.')
        }
        return @{ exists = $true; data = (New-IdleState $script:Fingerprint) }
    }
    $approvedIds = @($script:Configuration.targets | ForEach-Object { $_.id })
    $seen = @{}
    foreach ($target in $state.targets) {
        if ($approvedIds -notcontains $target.id -or $seen.ContainsKey($target.id)) {
            throw [InvalidOperationException]::new('Checkpoint contains an unapproved or duplicate target.')
        }
        $expectedKind = @($script:Configuration.targets | Where-Object id -eq $target.id)[0].kind
        if ($target.kind -cne $expectedKind) {
            throw [InvalidOperationException]::new('Checkpoint target type does not match the allowlist.')
        }
        $seen[$target.id] = $true
    }
    if (@('Idle', 'Started') -notcontains $state.phase -and $state.targets.Count -ne $approvedIds.Count) {
        throw [InvalidOperationException]::new('Outstanding checkpoint is incomplete; refusing mutations.')
    }
    return @{ exists = $true; data = $state }
}

function Get-OptimizerJobHistory {
    $configuration = $script:Configuration
    $base = "/subscriptions/$($configuration.subscriptionId)/resourceGroups/$($configuration.resourceGroup)/providers/Microsoft.Automation/automationAccounts/$($configuration.automationAccount)"
    $uri = "https://management.azure.com$base/jobs?api-version=2024-10-23"
    $jobs = [Collections.Generic.List[object]]::new()
    for ($page = 0; $page -lt 100; $page++) {
        $result = (Invoke-OptimizerRequest -Uri $uri -NoLeaseRenewal).json
        foreach ($job in $result.value) {
            if ($job.properties.runbook.name -eq $configuration.runbookName) { $jobs.Add($job) }
        }
        if (-not $result.ContainsKey('nextLink') -or [string]::IsNullOrWhiteSpace($result.nextLink)) {
            return ,$jobs.ToArray()
        }
        if ($result.nextLink -notlike "https://management.azure.com$base/jobs?*") {
            throw [InvalidOperationException]::new('Unexpected job-history pagination URL.')
        }
        $uri = $result.nextLink
    }
    throw [InvalidOperationException]::new('Job-history pagination limit exceeded.')
}

function Enter-StateLease {
    if ($script:Mode -ne 'Live') {
        throw [InvalidOperationException]::new('Preview cannot acquire or change a checkpoint lease.')
    }
    # ARM ignores container If-Match: this is a cooperative-writer mutex, not CAS
    # or protection against administrators. Only settled terminal jobs are reclaimed.
    $request = @{ action = 'Acquire'; leaseDuration = -1; proposedLeaseId = $script:CurrentJobId }
    $response = Invoke-StateLeaseAction -Body $request -ExpectedStatuses @(409)
    if ($response.status -eq 409) {
        $reclaimed = $false
        foreach ($job in (Get-OptimizerJobHistory | Sort-Object { $_.properties.lastModifiedTime } -Descending)) {
            if (@('Completed', 'Failed', 'Stopped') -notcontains $job.properties.status) { continue }
            $settled = [DateTimeOffset]::Parse($job.properties.lastModifiedTime)
            if ($settled -gt [DateTimeOffset]::UtcNow.AddMinutes(-10)) { continue }
            $candidateId = [string]$job.properties.jobId
            if ([string]::IsNullOrWhiteSpace($candidateId)) { continue }
            $candidate = Invoke-StateLeaseAction -Body @{ action = 'Renew'; leaseId = $candidateId } -ExpectedStatuses @(409)
            if ($candidate.status -eq 200) {
                $null = Invoke-StateLeaseAction -Body @{ action = 'Release'; leaseId = $candidateId }
                Write-Warning "Reclaimed the mutex of terminal job $candidateId after its ten-minute settling period."
                $response = Invoke-StateLeaseAction -Body $request -ExpectedStatuses @(409)
                $reclaimed = $true
                break
            }
        }
        if (-not $reclaimed -or $response.status -eq 409) {
            throw [InvalidOperationException]::new('Another optimizer job owns the mutex, or its owner is not safely recoverable. No resources were changed.')
        }
    }
    if ($response.json.leaseId -ne $script:CurrentJobId) {
        throw [InvalidOperationException]::new('Storage did not return the proposed job-bound lease ID.')
    }
    $script:Lease = @{
        id = $response.json.leaseId
        lastVerified = [DateTimeOffset]::UtcNow
    }
    $current = Read-OptimizerState
    $script:State = $current.data
}

function Save-OptimizerState {
    if ($script:Mode -ne 'Live' -or $null -eq $script:Lease) {
        throw [InvalidOperationException]::new('Checkpoint writes require Live mode and an owned lease.')
    }
    if ($script:StateWriteUncertain) {
        throw [InvalidOperationException]::new('A checkpoint write has an unknown outcome; the mutex is retained and no further changes are allowed.')
    }
    $script:State.updatedUtc = [DateTimeOffset]::UtcNow.ToString('o')
    $encoded = ConvertTo-CheckpointMetadata -State $script:State
    $container = Get-StateContainer
    $metadata = if ($container.properties.ContainsKey('metadata')) { $container.properties.metadata } else { @{} }
    $metadata.Remove('optimizer_probe')
    $metadata.optimizer_checkpoint = $encoded
    $metadata.optimizer_owner_job = $script:CurrentJobId
    $metadataBytes = 0
    foreach ($key in $metadata.Keys) {
        $metadataBytes += [Text.Encoding]::UTF8.GetByteCount([string]$key)
        $metadataBytes += [Text.Encoding]::UTF8.GetByteCount([string]$metadata[$key])
    }
    if ($metadataBytes -gt 7800) { throw [InvalidOperationException]::new('Total state-container metadata exceeds its safety limit.') }
    $script:StateWriteUncertain = $true
    $body = @{ properties = @{ metadata = $metadata } } | ConvertTo-Json -Depth 5 -Compress
    $null = Invoke-OptimizerRequest -Uri "$($script:StateContainerUri)?api-version=2023-05-01" `
        -Method Patch -Body $body -NoRetry
    $saved = Get-StateContainer
    if ($saved.properties.metadata.optimizer_checkpoint -ne $encoded) {
        throw [InvalidOperationException]::new('Checkpoint verification failed; the mutex is retained.')
    }
    $script:StateWriteUncertain = $false
}

function Exit-StateLease {
    if ($null -ne $script:Lease) {
        $null = Invoke-StateLeaseAction -Body @{ action = 'Release'; leaseId = $script:Lease.id }
        $script:Lease = $null
    }
}

function New-StopSnapshot {
    $targets = [Collections.Generic.List[object]]::new()
    foreach ($target in $script:Configuration.targets) {
        $entry = @{
            kind = $target.kind
            id = $target.id
            shouldRestore = $false
            stopAttempted = $false
            stopAccepted = $false
            status = 'Skipped'
            error = $null
        }
        if ($target.kind -eq 'VirtualMachine') {
            $power = Get-VmPowerState -Id $target.id
            if (@('PowerState/running', 'PowerState/deallocated', 'PowerState/stopped') -notcontains $power) {
                throw [InvalidOperationException]::new("VM is transitioning; retry after it settles: $($target.id) ($power)")
            }
            $entry.originalPowerState = $power
            $entry.shouldRestore = $power -eq 'PowerState/running'
            if ($power -eq 'PowerState/stopped') {
                Write-Warning "Already stopped but allocated; preserving the user's state, not powering it on later: $($target.id)"
            }
        } else {
            $app = (Invoke-ArmRequest -Path $target.id).json
            $revisions = Get-AppRevisions -Id $target.id
            if (@('Running', 'Stopped') -notcontains $app.properties.runningStatus) {
                throw [InvalidOperationException]::new("Container App is transitioning: $($target.id)")
            }
            $entry.originalRunningStatus = $app.properties.runningStatus
            $entry.latestRevisionName = $app.properties.latestRevisionName
            $entry.revisionMode = $app.properties.configuration.activeRevisionsMode
            $entry.routingFingerprint = Get-AppRoutingFingerprint -App $app
            $entry.revisions = @($revisions | Where-Object { $_.properties.active } | ForEach-Object {
                @{
                    name = $_.name
                    health = $_.properties.healthState
                    trafficWeight = $_.properties.trafficWeight
                    replicas = $_.properties.replicas
                }
            })
            $entry.shouldRestore = $app.properties.runningStatus -eq 'Running' -and $entry.revisions.Count -gt 0
        }
        if ($entry.shouldRestore) { $entry.status = 'PendingStop' }
        $targets.Add($entry)
    }
    return @{
        schemaVersion = 1
        fingerprint = $script:Fingerprint
        cycleId = [Guid]::NewGuid().ToString()
        phase = 'Stopping'
        createdUtc = [DateTimeOffset]::UtcNow.ToString('o')
        updatedUtc = [DateTimeOffset]::UtcNow.ToString('o')
        targets = $targets.ToArray()
    }
}

function Assert-AppUnchanged {
    param([hashtable]$Entry)
    $app = (Invoke-ArmRequest -Path $Entry.id).json
    if ($app.properties.latestRevisionName -ne $Entry.latestRevisionName -or
        $app.properties.configuration.activeRevisionsMode -ne $Entry.revisionMode -or
        (Get-AppRoutingFingerprint -App $app) -ne $Entry.routingFingerprint) {
        throw [InvalidOperationException]::new("App deployment changed during the pause; refusing to restore old revisions: $($Entry.id)")
    }
    $revisions = Get-AppRevisions -Id $Entry.id
    $expectedNames = @($Entry.revisions | ForEach-Object { $_.name })
    foreach ($revision in $revisions) {
        if ($revision.properties.active -and $expectedNames -notcontains $revision.name) {
            throw [InvalidOperationException]::new("Unexpected active revision; leaving the new deployment untouched: $($revision.name)")
        }
    }
    foreach ($name in $expectedNames) {
        if (@($revisions | Where-Object name -eq $name).Count -ne 1) {
            throw [InvalidOperationException]::new("Saved revision no longer exists: $name")
        }
    }
    return @{ app = $app; revisions = $revisions }
}

function Request-TargetAction {
    param([hashtable]$Entry, [ValidateSet('STOP', 'START')][string]$RequestedAction)
    if (-not $Entry.shouldRestore) { return }
    if ($script:Mode -ne 'Live') { throw [InvalidOperationException]::new('Preview cannot change resources.') }
    if ($script:StateWriteUncertain) {
        throw [InvalidOperationException]::new('Checkpoint write outcome is unknown; no further target changes are allowed.')
    }
    if ($RequestedAction -eq 'START' -and -not $Entry.stopAccepted) {
        throw [InvalidOperationException]::new('START requires an accepted STOP operation owned by this automation.')
    }
    if ($Entry.kind -eq 'VirtualMachine') {
        $power = Get-VmPowerState -Id $Entry.id
        if ($RequestedAction -eq 'STOP') {
            if ($power -eq 'PowerState/running' -or $power -eq 'PowerState/stopped') {
                $Entry.stopAttempted = $true
                Save-OptimizerState
                $null = Invoke-ArmRequest -Path "$($Entry.id)/deallocate" -Method Post -ApiVersion '2024-11-01'
                $Entry.stopAccepted = $true
                Save-OptimizerState
            } elseif ($power -eq 'PowerState/deallocated' -and -not $Entry.stopAccepted) {
                if ($Entry.stopAttempted) {
                    throw [InvalidOperationException]::new('VM is deallocated, but STOP acceptance was not confirmed. Inspect or restore it manually; it will not be silently skipped.')
                }
                $Entry.status = 'Skipped'
                Save-OptimizerState
            } elseif ($power -eq 'PowerState/deallocating' -and -not $Entry.stopAccepted) {
                throw [InvalidOperationException]::new('VM is being deallocated by an unconfirmed operation; refusing to claim it.')
            } elseif (@('PowerState/deallocated', 'PowerState/deallocating') -notcontains $power) {
                throw [InvalidOperationException]::new("Unexpected VM state for STOP: $power ($($Entry.id))")
            }
        } else {
            if ($power -eq 'PowerState/deallocated' -or $power -eq 'PowerState/stopped') {
                $null = Invoke-ArmRequest -Path "$($Entry.id)/start" -Method Post -ApiVersion '2024-11-01'
            } elseif (@('PowerState/running', 'PowerState/starting') -notcontains $power) {
                throw [InvalidOperationException]::new("Unexpected VM state for START: $power ($($Entry.id))")
            }
        }
    } else {
        $current = Assert-AppUnchanged -Entry $Entry
        $desired = if ($RequestedAction -eq 'START') { 'Running' } else { 'Stopped' }
        if ($current.app.properties.runningStatus -ne $desired) {
            $verb = $RequestedAction.ToLowerInvariant()
            if ($RequestedAction -eq 'STOP') {
                $Entry.stopAttempted = $true
                Save-OptimizerState
            }
            $null = Invoke-ArmRequest -Path "$($Entry.id)/$verb" -Method Post
            if ($RequestedAction -eq 'STOP') {
                $Entry.stopAccepted = $true
                Save-OptimizerState
            }
        } elseif ($RequestedAction -eq 'STOP' -and -not $Entry.stopAccepted) {
            if ($Entry.stopAttempted) {
                throw [InvalidOperationException]::new('App is stopped, but STOP acceptance was not confirmed. Inspect or restore it manually; it will not be silently skipped.')
            }
            $Entry.status = 'Skipped'
            Save-OptimizerState
        }
    }
}

function Test-TargetActionComplete {
    param([hashtable]$Entry, [ValidateSet('STOP', 'START')][string]$RequestedAction)
    if ($Entry.kind -eq 'VirtualMachine') {
        $desired = if ($RequestedAction -eq 'STOP') { 'PowerState/deallocated' } else { 'PowerState/running' }
        return (Get-VmPowerState -Id $Entry.id) -eq $desired
    }
    $state = Assert-AppUnchanged -Entry $Entry
    $desired = if ($RequestedAction -eq 'START') { 'Running' } else { 'Stopped' }
    if ($state.app.properties.runningStatus -ne $desired) { return $false }
    foreach ($saved in $Entry.revisions) {
        $current = @($state.revisions | Where-Object name -eq $saved.name)[0].properties
        if ($RequestedAction -eq 'STOP') {
            if ($current.replicas -gt 0) { return $false }
        } else {
            if (-not $current.active) { return $false }
            if ($saved.health -eq 'Healthy' -and $saved.trafficWeight -gt 0 -and $saved.replicas -gt 0) {
                if ($current.healthState -ne 'Healthy' -or $current.replicas -lt 1) { return $false }
            }
        }
    }
    return $true
}

function Invoke-StatefulAction {
    param([ValidateSet('STOP', 'START')][string]$RequestedAction)
    if ($RequestedAction -eq 'STOP') {
        if (@('Starting', 'StartFailed') -contains $script:State.phase) {
            throw [InvalidOperationException]::new('Finish the outstanding START before beginning another STOP cycle.')
        }
        if (@('Idle', 'Started') -contains $script:State.phase) {
            $script:State = New-StopSnapshot
            Save-OptimizerState
        }
        $script:State.phase = 'Stopping'
        $complete = 'Stopped'
        $failed = 'StopFailed'
        $requested = 'StopRequested'
    } else {
        if (@('Idle', 'Started') -contains $script:State.phase) {
            return @{ action = 'START'; phase = $script:State.phase; message = 'No outstanding STOP snapshot. No resources were started.' }
        }
        $script:State.phase = 'Starting'
        $complete = 'Started'
        $failed = 'StartFailed'
        $requested = 'StartRequested'
    }
    Save-OptimizerState
    foreach ($entry in $script:State.targets) {
        if (-not $entry.shouldRestore -or ($RequestedAction -eq 'START' -and $entry.status -eq 'Started')) { continue }
        try {
            if ($RequestedAction -eq 'START' -and -not $entry.stopAccepted) {
                if ($entry.stopAttempted) {
                    $running = if ($entry.kind -eq 'VirtualMachine') {
                        (Get-VmPowerState -Id $entry.id) -eq 'PowerState/running'
                    } else {
                        (Invoke-ArmRequest -Path $entry.id).json.properties.runningStatus -eq 'Running'
                    }
                    if (-not $running) {
                        throw [InvalidOperationException]::new("STOP acceptance was not confirmed for $($entry.id). Inspect or restore it manually, then retry START. It will not be powered on automatically.")
                    }
                    $entry.status = 'Started'
                } else {
                    $entry.status = 'Skipped'
                }
                Save-OptimizerState
                continue
            }
            $entry.status = $requested
            $entry.error = $null
            Save-OptimizerState
            Request-TargetAction -Entry $entry -RequestedAction $RequestedAction
        } catch {
            $entry.status = $failed
            $entry.error = $_.Exception.Message
            Write-Warning $entry.error
            Save-OptimizerState
        }
    }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($script:Configuration.operationTimeoutSeconds)
    while (@($script:State.targets | Where-Object status -eq $requested).Count -gt 0) {
        foreach ($entry in @($script:State.targets | Where-Object status -eq $requested)) {
            try {
                if (Test-TargetActionComplete -Entry $entry -RequestedAction $RequestedAction) {
                    $entry.status = $complete
                    Save-OptimizerState
                } elseif ([DateTimeOffset]::UtcNow -ge $deadline) {
                    throw [TimeoutException]::new("$RequestedAction timed out for $($entry.id). The checkpoint is retained for recovery.")
                }
            } catch {
                $entry.status = $failed
                $entry.error = $_.Exception.Message
                Write-Warning $entry.error
                Save-OptimizerState
            }
        }
        if (@($script:State.targets | Where-Object status -eq $requested).Count -gt 0) {
            Update-StateLease
            Start-Sleep -Seconds 10
        }
    }
    $failures = @($script:State.targets | Where-Object status -eq $failed)
    $script:State.phase = if ($failures.Count -gt 0) { $failed } else { $complete }
    Save-OptimizerState
    $summary = @{
        action = $RequestedAction
        phase = $script:State.phase
        cycleId = $script:State.cycleId
        targets = @($script:State.targets | ForEach-Object {
            @{ id = $_.id; kind = $_.kind; status = $_.status; shouldRestore = $_.shouldRestore; error = $_.error }
        })
    }
    if ($failures.Count -gt 0) {
        Write-Output ($summary | ConvertTo-Json -Depth 10)
        throw [InvalidOperationException]::new("$RequestedAction failed for $($failures.Count) target(s). Retry the same action; the original snapshot was preserved.")
    }
    return $summary
}

function Get-OptimizerPreview {
    param([string]$RequestedAction)
    $checkpoint = Read-OptimizerState
    $plan = New-StopSnapshot
    $summary = @{
        mode = 'Preview'
        action = $RequestedAction
        checkpointPhase = $checkpoint.data.phase
        message = 'Read-only. No power, revision, or checkpoint changes.'
        targets = @()
    }
    foreach ($entry in $plan.targets) {
        $saved = @($checkpoint.data.targets | Where-Object id -eq $entry.id)
        $willRestore = $saved.Count -eq 1 -and $saved[0].shouldRestore -and $saved[0].stopAccepted -and
            @('Idle', 'Started') -notcontains $checkpoint.data.phase -and $saved[0].status -ne 'Started'
        $current = if ($entry.kind -eq 'VirtualMachine') {
            $entry.originalPowerState
        } else {
            "$($entry.originalRunningStatus); $($entry.revisions.Count) active revisions"
        }
        $summary.targets += @{
            id = $entry.id
            kind = $entry.kind
            currentState = $current
            wouldStop = $RequestedAction -eq 'STOP' -and $entry.shouldRestore
            wouldStart = $RequestedAction -eq 'START' -and $willRestore
        }
    }
    return $summary
}

function Invoke-OptimizerMain {
    param([string]$RequestedAction, [string]$RequestedMode)
    $script:Mode = $RequestedMode
    $script:Tokens = @{}
    $script:Lease = $null
    $script:StateWriteUncertain = $false
    $script:Configuration = Get-AutomationVariable -Name 'CostOptimizerConfiguration' | ConvertFrom-Json -AsHashtable -DateKind String
    Assert-OptimizerConfiguration -Configuration $script:Configuration
    $script:Fingerprint = Get-ConfigurationFingerprint -Configuration $script:Configuration
    $configuration = $script:Configuration
    $script:StateContainerUri = "https://management.azure.com/subscriptions/$($configuration.subscriptionId)/resourceGroups/$($configuration.resourceGroup)/providers/Microsoft.Storage/storageAccounts/$($configuration.stateStorageAccount)/blobServices/default/containers/$($configuration.stateContainer)"
    if ($RequestedMode -eq 'Preview' -or $RequestedAction -eq 'STATUS') {
        return Get-OptimizerPreview -RequestedAction $RequestedAction
    }
    if ($RequestedAction -eq 'START' -and -not (Read-OptimizerState).exists) {
        return @{ action = 'START'; phase = 'Idle'; message = 'No prior STOP snapshot exists. No resources were started.' }
    }
    $jobIdentity = Get-Variable -Name AutomationPSPrivateMetadataJobId -ValueOnly -ErrorAction SilentlyContinue
    if ($null -eq $jobIdentity) {
        $privateMetadata = Get-Variable -Name PSPrivateMetadata -ValueOnly -ErrorAction Stop
        $jobIdentity = $privateMetadata.JobId.Guid
    }
    $script:CurrentJobId = ([Guid]$jobIdentity).ToString()
    if ($script:CurrentJobId -eq [Guid]::Empty.ToString()) {
        throw [InvalidOperationException]::new('Automation job identity is unavailable.')
    }
    try {
        Enter-StateLease
        if ($RequestedAction -eq 'VERIFY') {
            Save-OptimizerState
            $history = Get-OptimizerJobHistory
            return @{ action = 'VERIFY'; phase = $script:State.phase; jobHistoryReadable = $true; knownJobs = $history.Count; message = 'Private management-plane checkpoint, codec and server mutex verified. No target power or revision changes.' }
        }
        return Invoke-StatefulAction -RequestedAction $RequestedAction
    } finally {
        if ($null -ne $script:Lease) {
            if ($script:StateWriteUncertain) {
                Write-Warning 'Checkpoint write outcome is uncertain. The non-expiring mutex is retained; a terminal job can be recovered after ten minutes.'
            } else {
                try {
                    Exit-StateLease
                } catch {
                    Write-Warning "Mutex release failed. A later job can recover this terminal job after ten minutes. $($_.Exception.Message)"
                }
            }
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-OptimizerMain -RequestedAction $Action -RequestedMode $Mode | ConvertTo-Json -Depth 15
}

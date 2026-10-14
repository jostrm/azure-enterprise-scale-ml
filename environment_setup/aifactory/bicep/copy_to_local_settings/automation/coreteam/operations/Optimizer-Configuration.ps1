#Requires -Version 7.6
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RequiredOptimizerText {
    param([hashtable]$Values, [string]$Key, [switch]$AllowEmpty)
    if (-not $Values.ContainsKey($Key) -or $Values[$Key] -isnot [string]) {
        throw "variables.json must contain a string value for $Key."
    }
    $value = $Values[$Key].Trim()
    if ((-not $AllowEmpty -and [string]::IsNullOrWhiteSpace($value)) -or
        $value -match '[<>$*?{}]' -or $value -match '\$\(') {
        throw "variables.json contains an empty or unresolved value for $Key."
    }
    return $value
}

function Assert-OptimizerGuid {
    param([string]$Value, [string]$Key)
    if ($Value -notmatch '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' -or
        [Guid]$Value -eq [Guid]::Empty) {
        throw "$Key must be a nonempty Azure GUID, not a placeholder."
    }
}

function Assert-OptimizerResourceGroupName {
    param([string]$Name)
    if ($Name.Length -lt 1 -or $Name.Length -gt 90 -or
        $Name -notmatch '^[a-zA-Z0-9_.()-]+$' -or $Name.EndsWith('.')) {
        throw "Invalid resolved resource group name: $Name"
    }
}

function Resolve-CostOptimizerScope {
    param(
        [hashtable]$Variables,
        [ValidateSet('dev', 'stage', 'test', 'prod')][string]$Environment = 'dev',
        [string[]]$ProjectNumbers = @(),
        [switch]$IncludeCommonVms
    )
    $physicalEnvironment = if ($Environment -eq 'stage') { 'test' } else { $Environment }
    if ($physicalEnvironment -eq 'prod') {
        throw 'Production shutdown is not supported by this development cost optimizer.'
    }
    if (-not $Variables.ContainsKey('dev') -or $Variables.dev -isnot [hashtable]) {
        throw 'variables.json must contain the canonical dev object.'
    }
    $selected = $Variables.dev
    $values = @{} + $Variables.dev
    if ($physicalEnvironment -ne 'dev') {
        if (-not $Variables.ContainsKey('stage_prod') -or $Variables.stage_prod -isnot [hashtable]) {
            throw 'Stage/test selection requires an explicit stage_prod object.'
        }
        $selected = $Variables.stage_prod
        foreach ($key in $selected.Keys) { $values[$key] = $selected[$key] }
    }
    # Identity must come from the exact selected section, never the dev fallback.
    $tenant = Get-RequiredOptimizerText $selected 'tenantId'
    $subscription = Get-RequiredOptimizerText $selected "${physicalEnvironment}_sub_id"
    Assert-OptimizerGuid $tenant 'tenantId'
    Assert-OptimizerGuid $subscription "${physicalEnvironment}_sub_id"
    $location = Get-RequiredOptimizerText $values 'admin_location'
    $locationShort = Get-RequiredOptimizerText $values 'admin_locationSuffix'
    if ($location -notmatch '^[a-z0-9]+$' -or $locationShort -notmatch '^[a-z0-9]+$') {
        throw 'Azure location and location suffix must be lowercase alphanumeric.'
    }
    $prefix = Get-RequiredOptimizerText $values 'admin_aifactoryPrefixRG' -AllowEmpty
    $suffix = Get-RequiredOptimizerText $values 'admin_aifactorySuffixRG' -AllowEmpty
    $projectPrefix = Get-RequiredOptimizerText $values 'projectPrefix' -AllowEmpty
    $projectSuffix = Get-RequiredOptimizerText $values 'projectSuffix' -AllowEmpty
    $commonBase = Get-RequiredOptimizerText $values 'vnetResourceGroupBase'
    if ($ProjectNumbers.Count -eq 0) {
        $ProjectNumbers = @(Get-RequiredOptimizerText $values 'project_number_000')
    }
    $seenProjects = @{}
    foreach ($project in $ProjectNumbers) {
        if ($project -notmatch '^\d{3}$' -or $project -eq '000' -or $seenProjects.ContainsKey($project)) {
            throw 'Choose distinct three-digit project numbers, excluding 000. All and wildcards are not allowed.'
        }
        $seenProjects[$project] = $true
    }
    # Same formulas as CmnAIfactoryNaming/deploy-dashboards-only and FinOps.
    $commonGroup = "${prefix}${commonBase}-${locationShort}-${physicalEnvironment}${suffix}"
    if ($values.ContainsKey('commonResourceGroup_param')) {
        $override = Get-RequiredOptimizerText $values 'commonResourceGroup_param' -AllowEmpty
        if (-not [string]::IsNullOrWhiteSpace($override)) { $commonGroup = $override }
    }
    Assert-OptimizerResourceGroupName $commonGroup
    $projectGroups = @($ProjectNumbers | Sort-Object | ForEach-Object {
        $name = "${prefix}${projectPrefix}project${_}-${locationShort}-${physicalEnvironment}${suffix}${projectSuffix}"
        Assert-OptimizerResourceGroupName $name
        $name
    })
    $resourceGroups = @($projectGroups)
    if ($IncludeCommonVms) { $resourceGroups += $commonGroup }
    if (@($resourceGroups | Sort-Object -Unique).Count -ne $resourceGroups.Count) {
        throw 'The selected naming resolves overlapping common and project groups.'
    }
    $identityText = "$tenant|$subscription|$prefix|$suffix|$locationShort|$physicalEnvironment|$commonGroup".ToLowerInvariant()
    $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($identityText))).ToLowerInvariant()
    return @{
        tenantId = $tenant.ToLowerInvariant()
        subscriptionId = $subscription.ToLowerInvariant()
        location = $location
        environment = $physicalEnvironment
        factoryKey = $digest.Substring(0, 12)
        commonResourceGroup = $commonGroup
        projectResourceGroups = $projectGroups
        resourceGroups = $resourceGroups
        includeCommonVms = [bool]$IncludeCommonVms
    }
}

function Get-CostOptimizerScheduleTimes {
    param(
        [string]$TimeZone = 'Europe/Berlin',
        [string]$StopTime = '03:00',
        [string]$StartTime = '08:00',
        [string]$FirstStopDate = '',
        [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow
    )
    foreach ($time in @($StopTime, $StartTime)) {
        if ($time -notmatch '^([01]\d|2[0-3]):[0-5]\d$') { throw "Invalid local time: $time. Use HH:mm." }
    }
    if ($StopTime -eq $StartTime) { throw 'STOP and START cannot have the same local time.' }
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById($TimeZone)
    $localNow = [TimeZoneInfo]::ConvertTime($Now, $zone)
    $date = if ([string]::IsNullOrWhiteSpace($FirstStopDate)) {
        $localNow.Date.AddDays(1)
    } else {
        [DateTime]::ParseExact($FirstStopDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    }
    $stop = [DateTime]::SpecifyKind($date.Add([TimeSpan]::Parse($StopTime)), [DateTimeKind]::Unspecified)
    $start = [DateTime]::SpecifyKind($date.Add([TimeSpan]::Parse($StartTime)), [DateTimeKind]::Unspecified)
    if ($start -lt $stop) { $start = $start.AddDays(1) }
    foreach ($instant in @($stop, $start)) {
        if ($zone.IsInvalidTime($instant) -or $zone.IsAmbiguousTime($instant)) {
            throw 'Initial schedule falls in a daylight-saving gap or overlap. Choose another first date or time.'
        }
    }
    $firstStop = [DateTimeOffset]::new($stop, $zone.GetUtcOffset($stop))
    $firstStart = [DateTimeOffset]::new($start, $zone.GetUtcOffset($start))
    if ($firstStop -le $Now.AddMinutes(5)) { throw 'First STOP must be at least five minutes in the future.' }
    return @{ firstStop = $firstStop.ToString('o'); firstStart = $firstStart.ToString('o') }
}

function Select-CostOptimizerTargets {
    param(
        [hashtable]$Scope,
        [object[]]$Inventory,
        [ValidateSet('ContainerApp', 'VirtualMachine')][string[]]$Kinds,
        [string[]]$TargetResourceIds = @()
    )
    if ($Kinds.Count -eq 0) { throw 'Select at least one supported resource kind.' }
    $targets = [Collections.Generic.List[object]]::new()
    $seen = @{}
    foreach ($resource in $Inventory) {
        if (@('Microsoft.App/containerApps', 'Microsoft.Compute/virtualMachines') -notcontains $resource.type) { continue }
        $kind = if ($resource.type -eq 'Microsoft.App/containerApps') { 'ContainerApp' } else { 'VirtualMachine' }
        if ($Kinds -notcontains $kind) { continue }
        $pattern = '^/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/([^/]+/[^/]+)/([^/]+)$'
        if ($resource.id -notmatch $pattern -or $Matches[1] -ne $Scope.subscriptionId -or
            $Scope.resourceGroups -notcontains $Matches[2] -or $Matches[3] -ne $resource.type) {
            throw "Inventory contains a resource outside the resolved scope: $($resource.id)"
        }
        $group = $Matches[2]
        if ($group -eq $Scope.commonResourceGroup -and
            (-not $Scope.includeCommonVms -or $kind -ne 'VirtualMachine')) { continue }
        if ($TargetResourceIds.Count -gt 0 -and $TargetResourceIds -notcontains $resource.id) { continue }
        if ($seen.ContainsKey($resource.id)) { throw "Duplicate inventory entry: $($resource.id)" }
        $seen[$resource.id] = $true
        $targets.Add(@{ kind = $kind; id = $resource.id })
    }
    foreach ($id in $TargetResourceIds) {
        if (-not $seen.ContainsKey($id)) { throw "Requested target was not discovered in the selected scope/kinds: $id" }
    }
    if ($targets.Count -eq 0 -or $targets.Count -gt 16) {
        throw 'Choose 1 to 16 supported resources per automation deployment; split larger scopes into separate plans.'
    }
    return ,@($targets.ToArray() | Sort-Object { $_.id.ToLowerInvariant() })
}

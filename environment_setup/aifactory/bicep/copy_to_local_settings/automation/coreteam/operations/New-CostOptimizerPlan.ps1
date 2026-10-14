#Requires -Version 7.6
param(
    [Parameter(Mandatory)][string]$VariablesPath,
    [ValidateSet('dev', 'stage', 'test', 'prod')][string]$Environment = 'dev',
    [string[]]$ProjectNumbers = @(),
    [Parameter(Mandatory)][ValidateSet('ContainerApp', 'VirtualMachine')][string[]]$Kinds,
    [switch]$IncludeCommonVms,
    [string[]]$TargetResourceIds = @(),
    [string]$TimeZone = 'Europe/Berlin',
    [string]$StopTime = '03:00',
    [string]$StartTime = '08:00',
    [string]$FirstStopDate = '',
    [Parameter(Mandatory)][string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Optimizer-Configuration.ps1"
. "$PSScriptRoot\Tenant-Cost-Optimizer.ps1"
. "$PSScriptRoot\Azure-Control.ps1"
if ([IO.Path]::GetFileName($VariablesPath) -ne 'variables.json') {
    throw 'Use the customer Factory variables.json as the identity and naming source.'
}
$variablesHash = (Get-FileHash -LiteralPath $VariablesPath -Algorithm SHA256).Hash.ToLowerInvariant()
$variablesText = Get-Content -LiteralPath $VariablesPath -Raw
$variables = $variablesText | ConvertFrom-Json -AsHashtable -DateKind String
$scope = Resolve-CostOptimizerScope -Variables $variables -Environment $Environment `
    -ProjectNumbers $ProjectNumbers -IncludeCommonVms:$IncludeCommonVms
$schedule = Get-CostOptimizerScheduleTimes -TimeZone $TimeZone -StopTime $StopTime `
    -StartTime $StartTime -FirstStopDate $FirstStopDate
$inventory = [Collections.Generic.List[object]]::new()
foreach ($group in $scope.resourceGroups) {
    $path = "/subscriptions/$($scope.subscriptionId)/resourceGroups/$group/resources"
    $response = Invoke-ControlArm -Configuration $scope -Path $path -ApiVersion '2021-04-01'
    for ($page = 0; $page -lt 100; $page++) {
        foreach ($resource in $response.json.value) { $inventory.Add($resource) }
        if (-not $response.json.ContainsKey('nextLink') -or [string]::IsNullOrWhiteSpace($response.json.nextLink)) { break }
        if ($page -eq 99) { throw 'Resource inventory pagination limit exceeded.' }
        if ($response.json.nextLink -notlike "https://management.azure.com${path}?*") {
            throw 'Unexpected resource inventory pagination URL.'
        }
        $response = Invoke-ControlArm -Configuration $scope -Path $response.json.nextLink
    }
}
$targets = Select-CostOptimizerTargets -Scope $scope -Inventory $inventory.ToArray() `
    -Kinds $Kinds -TargetResourceIds $TargetResourceIds
$key = $scope.factoryKey
$projectKey = ($scope.projectResourceGroups -join '|').ToLowerInvariant()
$deploymentKey = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes("$key|$projectKey"))).ToLowerInvariant().Substring(0, 12)
$configuration = @{
    schemaVersion = 2
    tenantId = $scope.tenantId
    subscriptionId = $scope.subscriptionId
    location = $scope.location
    resourceGroup = "aif-cost-opt-$deploymentKey-rg"
    automationAccount = "aa-aif-cost-opt-$deploymentKey"
    runbookName = 'Tenant-Cost-Optimizer'
    runtimeName = 'CostOptimizer-PowerShell76'
    configurationVariable = 'CostOptimizerConfiguration'
    stateStorageAccount = "staifcost$deploymentKey"
    stateContainer = 'cost-optimizer-state'
    stateTransport = 'ArmContainerMetadata'
    timeZone = $TimeZone
    stopTime = $StopTime
    startTime = $StartTime
    firstStop = $schedule.firstStop
    firstStart = $schedule.firstStart
    stopSchedule = "STOP-COST-OPTIMIZE-$($StopTime.Replace(':',''))"
    startSchedule = "START-COST-OPTIMIZE-$($StartTime.Replace(':',''))"
    operationTimeoutSeconds = 1200
    scope = @{
        factoryKey = $key
        environment = $scope.environment
        resourceGroups = @($scope.resourceGroups | Sort-Object)
        variablesSha256 = $variablesHash
    }
    targets = $targets
}
$configuration.planHash = Get-CostOptimizerPlanHash -Configuration $configuration
Assert-OptimizerConfiguration $configuration
if ((Get-FileHash -LiteralPath $VariablesPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $variablesHash) {
    throw 'variables.json changed during discovery. Generate a new plan from the current file.'
}
$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite an existing plan: $output. Use a new output filename." }
if ([IO.Path]::GetExtension($output) -ne '.json') { throw 'OutputPath must be a JSON file.' }
$parent = [IO.Path]::GetDirectoryName($output)
if (-not (Test-Path -LiteralPath $parent)) { $null = New-Item -ItemType Directory -Path $parent }
$bytes = [Text.Encoding]::UTF8.GetBytes(($configuration | ConvertTo-Json -Depth 20))
$stream = [IO.File]::Open($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Write-Host "Read-only plan saved: $output"
Write-Host "Tenant: $($scope.tenantId); subscription: $($scope.subscriptionId); environment: $($scope.environment)"
$targets | ForEach-Object { [pscustomobject]@{kind=$_.kind;id=$_.id} } | Format-Table -AutoSize | Out-Host
Write-Host "STOP $StopTime / START $StartTime ($TimeZone). Plan hash: $($configuration.planHash)"
Write-Host 'No Azure resources were changed. Review every target before passing this hash to deployment.'
$configuration

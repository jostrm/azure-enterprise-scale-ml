<#
.SYNOPSIS
    Azure Automation Runbook: replicates the "Reports: Foundry models and token" report
    (see ignore.md / readme.md) from Log Analytics + (optional) Application Insights, and
    appends a "Recommendations" section (PAYGO vs PTU).

.DESCRIPTION
    1. Resolves Azure resource NAMES by CONCAT rules (no hardcoded names):
         - Subscription / RGs are built the same way infra-project.yml + CmnAIfactoryNaming.bicep do.
         - Foundry (CognitiveServices) account, Log Analytics workspace and App Insights are
           DISCOVERED by type inside those RGs, because the live name carries an unpredictable salt.
    2. Queries Log Analytics for INPUT/OUTPUT/cached tokens + requests per minute.
    3. Derives workload telemetry, blended cost, monthly cost (PAYGO).
    4. Computes a PTU recommendation per model (Model info + Discount config).
    5. Writes the report as Markdown (output stream + optional blob).

    Auth: Automation Account System-Assigned Managed Identity (Connect-AzAccount -Identity).
    Modules required: Az.Accounts, Az.OperationalInsights, Az.Resources, Az.Storage (blob only).

.NOTES
    Config: report-config.json (Model info + Discount). Override per-run via parameters.
#>

param(
    # aifactory.aggregate-report.v1: isolated local reporting, never the legacy Az login/output path.
    [string]$MonitoringRequest,
    [string]$MonitoringPython,
    # --- Identity / scope ---
    [string]$SubscriptionId,
    [string]$TenantId,
    # User-Assigned MI client id (the project 'mi-prj*' UAMI). If empty, discovered in project RG; else System MI.
    [string]$UamiClientId,
    [string]$ProjectNumber,
    [string]$Env,
    [string]$LocationShort,
    [string]$AifactoryPrefix,
    [string]$AifactorySuffix,
    [string]$ProjectPrefix,
    [string]$ProjectSuffix,
    [string]$VnetResourceGroupBase,

    # --- Discovery overrides (skip naming-concat discovery) ---
    [string]$ProjectResourceGroup,
    [string]$CommonResourceGroup,
    [string]$LogAnalyticsWorkspaceName,
    [string]$FoundryAccountName,

    # --- Reporting window ---
    [ValidateRange(1,90)] [int]$LookbackDays = 30,

    # --- Config + output ---
    [string]$ConfigPath = "$PSScriptRoot/report-config.json",
    [string]$ConfigJson,
    [ValidateSet('Markdown','Json')] [string]$ReportFormat = 'Markdown',
    [switch]$NoUpload,
    # Where naming variables come from: 'github' (.env) or 'ado' (variables.yaml). Default 'config' uses report-config.json.
    [ValidateSet('github','ado','config')] [string]$Source = 'config',
    # Path to the .env (github) or variables.yaml (ado). Defaults to repo root .env / variables.yaml.
    [string]$SettingsPath,
    [string]$OutputBlobStorageAccount,
    [string]$OutputBlobContainer = 'reports',
    [string]$OutputBlobName = 'foundry-token-report.md',

    # --- Local preview: skip Azure login + live queries, use sample telemetry from config ---
    [switch]$DryRun,

    # --- Use the already-signed-in Az PowerShell context instead of managed identity ---
    [switch]$UseCurrentLogin
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($MonitoringRequest) {
    if (-not $MonitoringPython) { throw 'The reviewed Monitoring Python runtime is required.' }
    & $MonitoringPython -I -B "$PSScriptRoot/common/monitoring_report.py" --request $MonitoringRequest
    exit $LASTEXITCODE
}
if ($ReportFormat -eq 'Json') {
    $WarningPreference = 'SilentlyContinue'
    $ProgressPreference = 'SilentlyContinue'
    $InformationPreference = 'SilentlyContinue'
}
$reportWarnings = [System.Collections.Generic.List[string]]::new()
$reportFailure = 'Report configuration or target is invalid.'
trap {
    if ($MonitoringRequest) { throw }
    if ($ReportFormat -eq 'Json') {
        [ordered]@{
            schema_version=1; report_type='foundry-tokens'; source=$(if ($DryRun) {'sample'} else {'live'})
            generated_at=[datetime]::UtcNow.ToString('o'); period=@{days=$LookbackDays}
            target=@{subscription_id=$SubscriptionId; project_resource_group=$ProjectResourceGroup; common_resource_group=$CommonResourceGroup; environment=$Env}
            status='failed'; warnings=@($reportFailure); tables=@(); charts=@(); output="# Foundry token report`n`n$reportFailure"
        } | ConvertTo-Json -Depth 12 -Compress | Write-Output
        exit 1
    }
    Write-Error $reportFailure
    exit 1
}
function Write-ReportInfo([string]$Message) {
    if ($ReportFormat -eq 'Json') { Write-Verbose $Message } else { Write-Output $Message }
}

function Get-Config {
    param([string]$Path)
    if (-not (Test-Path $Path)) { throw "Config file not found: $Path" }
    return Get-Content -Raw -Path $Path | ConvertFrom-Json
}

# Parse a KEY="value" .env file into a hashtable (GitHub Actions source).
function Get-EnvSettings {
    param([string]$Path)
    $h = @{}
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k,$v = $line -split '=',2
        $h[$k.Trim()] = ($v -replace '\s+#.*$','').Trim().Trim('"').Trim("'")
    }
    return $h
}

# Parse 'key: value' under variables: of variables.yaml into a hashtable (Azure DevOps source).
function Get-AdoSettings {
    param([string]$Path)
    $h = @{}
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match '^\s*#' -or $line -match '^\s*variables\s*:') { continue }
        if ($line -match '^\s{2,}([A-Za-z0-9_]+)\s*:\s*(.+)$') {
            $h[$matches[1].Trim()] = ($matches[2] -replace '\s+#.*$','').Trim().Trim('"').Trim("'")
        }
    }
    return $h
}

# Map github (.env) / ado (variables.yaml) settings to the common naming hashtable.
function Resolve-Naming {
    param([string]$Source,[hashtable]$s)
    if ($Source -eq 'github') {
        return @{ aifactoryPrefix=$s.AIFACTORY_PREFIX; aifactorySuffix=$s.AIFACTORY_SUFFIX; projectPrefix=$s.PROJECT_PREFIX;
                  projectSuffix=$s.PROJECT_SUFFIX; projectNumber=$s.PROJECT_NUMBER; locationShort=$s.AIFACTORY_LOCATION_SHORT;
                  env='dev'; vnetResourceGroupBase=$s.VNET_RESOURCE_GROUP_BASE }
    }
    return @{ aifactoryPrefix=$s.admin_aifactoryPrefixRG; aifactorySuffix=$s.admin_aifactorySuffixRG; projectPrefix=$s.projectPrefix;
              projectSuffix=$s.projectSuffix; projectNumber=$s.project_number_000; locationShort=$s.admin_locationSuffix;
              env=($s.ContainsKey('dev_test_prod') -and $s.dev_test_prod ? $s.dev_test_prod : 'dev'); vnetResourceGroupBase=$s.vnetResourceGroupBase }
}

# ---- Load config and resolve effective settings (param > github/ado source > config.naming) ----
$cfg = if ($ConfigJson) { $ConfigJson | ConvertFrom-Json } else { Get-Config -Path $ConfigPath }
$n = $cfg.naming
if ($Source -ne 'config') {
    $path = if ($SettingsPath) { $SettingsPath } elseif ($Source -eq 'github') { "$PSScriptRoot/../../../.env" } else { "$PSScriptRoot/../../esml-infra/azure-devops/bicep/yaml/variables/variables.yaml" }
    if (-not (Test-Path $path)) { throw "Settings file for source '$Source' not found: $path" }
    Write-ReportInfo "Reading naming from '$Source': $path"
    $settings = if ($Source -eq 'github') { Get-EnvSettings $path } else { Get-AdoSettings $path }
    $n = Resolve-Naming -Source $Source -s $settings
}
$aifactoryPrefix = if ($AifactoryPrefix) { $AifactoryPrefix } else { $n.aifactoryPrefix }
$aifactorySuffix = if ($AifactorySuffix) { $AifactorySuffix } else { $n.aifactorySuffix }
$projectPrefix   = if ($ProjectPrefix)   { $ProjectPrefix }   else { $n.projectPrefix }
$projectSuffix   = if ($ProjectSuffix)   { $ProjectSuffix }   else { $n.projectSuffix }
$projectNumber   = if ($ProjectNumber)   { $ProjectNumber }   else { $n.projectNumber }
if ($projectNumber -eq 'All') {
    $reportFailure = 'This collector requires one concrete project. All applies only to previously collected authorized rows; no resource named All is queried.'
    throw $reportFailure
}
$locShort        = if ($LocationShort)   { $LocationShort }   else { $n.locationShort }
$env             = if ($Env)             { $Env }             else { $n.env }
$vnetRgBase      = if ($VnetResourceGroupBase) { $VnetResourceGroupBase } else { $n.vnetResourceGroupBase }

# Project RG: {prefix}{projectPrefix}project{NNN}-{loc}-{env}{aifSuffix}{prjSuffix}
$projectRg = if ($ProjectResourceGroup) { $ProjectResourceGroup } else {
    "${aifactoryPrefix}${projectPrefix}project${projectNumber}-${locShort}-${env}${aifactorySuffix}${projectSuffix}"
}
# Common RG: {prefix}{vnetResourceGroupBase}-{loc}-{env}{aifSuffix}
$commonRg = if ($CommonResourceGroup) { $CommonResourceGroup } else {
    "${aifactoryPrefix}${vnetRgBase}-${locShort}-${env}${aifactorySuffix}"
}

$inputTokens=0.0; $outputTokens=0.0; $requests=0.0
$activeWindowMinutes = $LookbackDays * 24 * 60

if ($DryRun) {
    Write-ReportInfo "DRY-RUN: skipping Azure login + live queries; using sample telemetry from config."
    $reportWarnings.Add('Sample telemetry only; no Azure authentication or queries were performed.')
    if (-not $FoundryAccountName) { $FoundryAccountName = 'aif2<discovered>004dev' }
    Write-ReportInfo "Project RG   : $projectRg"
    Write-ReportInfo "Common RG    : $commonRg"
    $inputTokens  = ($cfg.totalUsersWithAccess * 1.3) * $activeWindowMinutes
    $outputTokens = $inputTokens * 0.011
    $requests     = 84 * $activeWindowMinutes
} else {

$reportFailure = 'Azure authentication or selected subscription/tenant validation failed.'
Disable-AzContextAutosave -Scope Process | Out-Null
Write-ReportInfo "Connecting with Managed Identity..."
if ($UseCurrentLogin) {
    Write-ReportInfo "Using existing Az PowerShell login."
} elseif ($UamiClientId) {
    Connect-AzAccount -Identity -AccountId $UamiClientId | Out-Null   # project UAMI (mi-prj*)
} else {
    Connect-AzAccount -Identity | Out-Null                            # fallback: Automation Account System MI
}
if ($SubscriptionId) { Select-AzSubscription -SubscriptionId $SubscriptionId | Out-Null }
$ctx = Get-AzContext
if (-not $ctx -or ($TenantId -and $ctx.Tenant.Id -ne $TenantId) -or ($SubscriptionId -and $ctx.Subscription.Id -ne $SubscriptionId)) { throw $reportFailure }
$SubscriptionId = $ctx.Subscription.Id
Write-ReportInfo "Subscription : $SubscriptionId"
Write-ReportInfo "Project RG   : $projectRg"
Write-ReportInfo "Common RG    : $commonRg"
$reportFailure = 'Foundry account or Log Analytics workspace discovery failed for the selected resource groups.'

# Discover the project UAMI (mi-prj*) for reference/logging if not explicitly passed
if (-not $UamiClientId) {
    $uami = Get-AzResource -ResourceGroupName $projectRg -ResourceType 'Microsoft.ManagedIdentity/userAssignedIdentities' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'mi-prj*' } | Select-Object -First 1
    if ($uami) { Write-ReportInfo "Project UAMI : $($uami.Name)" }
}

# ---- Discover Foundry (CognitiveServices) + Log Analytics by type ----
if (-not $FoundryAccountName) {
    $foundry = Get-AzResource -ResourceGroupName $projectRg -ResourceType 'Microsoft.CognitiveServices/accounts' -ErrorAction SilentlyContinue |
        Sort-Object Name | Select-Object -First 1
    if (-not $foundry) { throw "No Microsoft.CognitiveServices/accounts found in $projectRg" }
    $FoundryAccountName = $foundry.Name
    $foundryResourceId = $foundry.ResourceId
} else {
    $foundryResourceId = (Get-AzResource -ResourceGroupName $projectRg -Name $FoundryAccountName -ResourceType 'Microsoft.CognitiveServices/accounts').ResourceId
}
Write-ReportInfo "Foundry acct : $FoundryAccountName"

if (-not $LogAnalyticsWorkspaceName) {
    $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'la-cmn-*' } | Select-Object -First 1
    if (-not $law) { $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $law) { throw "No Log Analytics workspace found in $commonRg" }
} else {
    $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -Name $LogAnalyticsWorkspaceName
}
$workspaceId = $law.CustomerId
Write-ReportInfo "Log Analytics: $($law.Name) ($workspaceId)"

# ---- KQL: token + request rates from CognitiveServices metrics piped to Log Analytics ----
$kql = @"
AzureMetrics
| where TimeGenerated > ago(${LookbackDays}d)
| where Resource =~ '$FoundryAccountName'
| where MetricName in ('ProcessedPromptTokens','GeneratedTokens','ProcessedInferenceTokens','TotalCalls')
| summarize total=sum(Total) by MetricName
"@

try {
    $reportFailure = 'Log Analytics token query failed or returned incomplete telemetry; zero usage cannot be inferred.'
    $r = Invoke-AzOperationalInsightsQuery -WorkspaceId $workspaceId -Query $kql
    if (($r.PSObject.Properties['Error'] -and $r.Error) -or -not @($r.Results).Count) { throw $reportFailure }
    $metricNames = @($r.Results | ForEach-Object { $_.MetricName })
    foreach ($required in @('ProcessedPromptTokens','GeneratedTokens','TotalCalls')) {
        if ($required -notin $metricNames) { throw $reportFailure }
    }
    foreach ($row in $r.Results) {
        switch ($row.MetricName) {
            'ProcessedPromptTokens' { $inputTokens  = [double]$row.total }
            'GeneratedTokens'       { $outputTokens = [double]$row.total }
            'TotalCalls'            { $requests     = [double]$row.total }
        }
    }
} catch { throw $reportFailure }

}

$inputTpm  = if ($activeWindowMinutes) { [math]::Round($inputTokens/$activeWindowMinutes,0) } else { 0 }
$outputTpm = if ($activeWindowMinutes) { [math]::Round($outputTokens/$activeWindowMinutes,0) } else { 0 }
$rpm       = if ($activeWindowMinutes) { [math]::Round($requests/$activeWindowMinutes,0) } else { 0 }
$totalTokens = $inputTokens + $outputTokens

# ---- Discount + cost derivation ----
$reportFailure = 'Pricing configuration could not be used to calculate the estimate.'
$reportWarnings.Add('PAYGO/PTU estimates use configured model rates, discount, cache rate and capacity assumptions; they are not verified actual billing or per-model measured utilization.')
$d = $cfg.discountAndAdjustments
$model = $cfg.models[0]
$inputRate  = $model.inputCostPerMTokens  * (1 - $d.eaDiscount)
$cachedRate = $model.cachedCostPerMTokens * (1 - $d.eaDiscount)
$outputRate = $model.outputCostPerMTokens * (1 - $d.eaDiscount)
$avgTpm     = $inputTpm + $outputTpm
$reqPerDay  = $rpm * 60 * 24
$monthlyTok = $totalTokens / [math]::Max($LookbackDays,1) * 30
$blendedInputTok = $inputTokens * (1 - $d.cacheRate)
$blendedCacheTok = $inputTokens * $d.cacheRate
$monthCost = ($blendedInputTok*$inputRate + $blendedCacheTok*$cachedRate + $outputTokens*$outputRate)/1e6 / [math]::Max($LookbackDays,1)*30
$ptu = if ($model.inputTpmPerPtu) { [math]::Ceiling(($inputTpm*(1-$d.cacheRate))/$model.inputTpmPerPtu) } else { 0 }
$ptuTpm = $ptu * $model.inputTpmPerPtu

# ---- Build Markdown report ----
$telemetrySource = if ($DryRun) { 'Sample fixture (not live)' } else { 'Log Analytics workspace' }
$md = @"
# Automation for the AI Factory

## Reports: Foundry models and token
Model: $($model.name) — RG ``$projectRg`` — window ${LookbackDays}d — generated $(Get-Date -Format 'yyyy-MM-dd HH:mm')

> $(if ($DryRun) {'SAMPLE DATA — not live usage.'} else {'Live account-level aggregate telemetry; not per-model measured usage.'})
> Pricing, cache rate, users with access and PTU sizing use configuration assumptions, not verified actual billing.
> Data source: $telemetrySource (account token observations); Calculated (configured pricing/PTU estimates).
> Calculation: TPM = observed tokens / window minutes; monthly estimate = ((input*(1-cacheRate)*inputRate + input*cacheRate*cachedRate + output*outputRate)/1e6) * 30/windowDays. Rates include configured EA discount. Token volume is not business value.

### 2) Current workload telemetry (from logs)

| Workload - telemetry | Value | Unit |
|---|---|---|
| Total users with access | $($cfg.totalUsersWithAccess) | users |
| INPUT tokens per minute | $inputTpm | TPM |
| OUTPUT tokens per minute | $outputTpm | TPM |
| REQUESTS per minute | $rpm | RPM |
| Total tokens (window) | $([math]::Round($totalTokens,0)) | tokens |
| EA Discount | $($d.eaDiscount*100)% | |
| Cache rate | $($d.cacheRate*100)% | |
| Input rate (\$/1M) | $([math]::Round($inputRate,3)) | |
| Cached rate (\$/1M) | $([math]::Round($cachedRate,3)) | |
| Output rate (\$/1M) | $([math]::Round($outputRate,3)) | |

### 3) Derived workload information

| Derived | Value | Unit |
|---|---|---|
| Average TPM | $avgTpm | TPM |
| Requests per day | $([math]::Round($reqPerDay,0)) | req/day |
| Monthly tokens (30d) | $([math]::Round($monthlyTok,0)) | tokens |
| Est. monthly PAYGO cost | $([math]::Round($monthCost,0)) | USD |

# Recommendations

## Based on PAYGO usage, is PTU an option

| $($model.name) PTU Recommendation | Value | Note |
|---|---|---|
| PTUs (avg, ~$([int]($d.cacheRate*100))% cache) | $ptu | $($model.inputTpmPerPtu) input TPM/PTU |
| -> resulting TPM | $ptuTpm | normalized |
| PTU to handle spikes | $($d.ptuHandleSpikes) | else spillover PAYGO |
| AI Gateway loadbalancer | $($d.aiGatewayLoadBalancerExists) | |
"@

if (-not $NoUpload -and -not $DryRun -and $OutputBlobStorageAccount) {
    $reportFailure = 'Report generated, but the requested blob upload failed.'
    $tmp = Join-Path $PWD ("aif-report-" + [guid]::NewGuid() + ".txt")
    try {
        $md | Out-File -FilePath $tmp -Encoding utf8
        $sctx = (Get-AzStorageAccount -ResourceGroupName $projectRg -Name $OutputBlobStorageAccount).Context
        Set-AzStorageBlobContent -File $tmp -Container $OutputBlobContainer -Blob $OutputBlobName -Context $sctx -Force | Out-Null
        Write-ReportInfo "Report written: $OutputBlobContainer/$OutputBlobName"
    } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
}
if ($ReportFormat -eq 'Json') {
    [ordered]@{
        schema_version=1; report_type='foundry-tokens'; source=$(if ($DryRun) {'sample'} else {'live'})
        generated_at=[datetime]::UtcNow.ToString('o')
        period=@{days=$LookbackDays; start=[datetime]::UtcNow.AddDays(-$LookbackDays).ToString('o'); end=[datetime]::UtcNow.ToString('o')}
        target=@{subscription_id=$SubscriptionId; project_resource_group=$projectRg; common_resource_group=$commonRg; environment=$env}
        status='warning'; warnings=@($reportWarnings)
        dataSource="$telemetrySource; Calculated"
        lineage=@{inputs=@{inputTokens=$inputTokens; outputTokens=$outputTokens; requests=$requests; windowMinutes=$activeWindowMinutes; windowDays=$LookbackDays; inputRate=$inputRate; cachedRate=$cachedRate; outputRate=$outputRate; cacheRate=$d.cacheRate; eaDiscount=$d.eaDiscount; inputTpmPerPtu=$model.inputTpmPerPtu}; formula='TPM=tokens/windowMinutes; monthlyEstimate=((input*(1-cacheRate)*inputRate+input*cacheRate*cachedRate+output*outputRate)/1e6)*30/windowDays; PTU=ceil(inputTPM*(1-cacheRate)/inputTpmPerPtu)'; costBasis='estimate-not-billed'}
        tables=@(
            @{title='Account telemetry'; dataSource=$telemetrySource; formula='Token/request sums; per-minute rates divide sums by window minutes'; columns=@('Metric','Value','Unit'); rows=@(
                @('Input tokens',$inputTokens,'tokens'), @('Output tokens',$outputTokens,'tokens'), @('Requests',$requests,'requests'),
                @('Input TPM',$inputTpm,'TPM'), @('Output TPM',$outputTpm,'TPM'), @('Requests per minute',$rpm,'RPM')
            )},
            @{title='Configured pricing estimates (not actual billing)'; dataSource='Calculated'; formula='Configured rates, discount, cache ratio and capacity; see report lineage inputs'; columns=@('Estimate','Value','Unit'); rows=@(
                @('Monthly PAYGO',[math]::Round($monthCost,2),'USD'), @('Average PTUs',$ptu,'PTUs')
            )}
        )
        charts=@(@{title='Account token totals'; dataSource=$telemetrySource; formula='Sum observed input/output tokens in selected account and window'; labels=@('Input','Output'); series=@(@{name='Tokens'; values=@($inputTokens,$outputTokens)})})
        output=$md
    } | ConvertTo-Json -Depth 12 -Compress | Write-Output
} else {
    Write-Output $md
}

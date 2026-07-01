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
    # --- Identity / scope ---
    [string]$SubscriptionId,
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
    [int]$LookbackDays = 30,

    # --- Config + output ---
    [string]$ConfigPath = "$PSScriptRoot/report-config.json",
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
$cfg = Get-Config -Path $ConfigPath
$n = $cfg.naming
if ($Source -ne 'config') {
    $path = if ($SettingsPath) { $SettingsPath } elseif ($Source -eq 'github') { "$PSScriptRoot/../../../.env" } else { "$PSScriptRoot/../../esml-infra/azure-devops/bicep/yaml/variables/variables.yaml" }
    if (-not (Test-Path $path)) { throw "Settings file for source '$Source' not found: $path" }
    Write-Output "Reading naming from '$Source': $path"
    $settings = if ($Source -eq 'github') { Get-EnvSettings $path } else { Get-AdoSettings $path }
    $n = Resolve-Naming -Source $Source -s $settings
}
$aifactoryPrefix = if ($AifactoryPrefix) { $AifactoryPrefix } else { $n.aifactoryPrefix }
$aifactorySuffix = if ($AifactorySuffix) { $AifactorySuffix } else { $n.aifactorySuffix }
$projectPrefix   = if ($ProjectPrefix)   { $ProjectPrefix }   else { $n.projectPrefix }
$projectSuffix   = if ($ProjectSuffix)   { $ProjectSuffix }   else { $n.projectSuffix }
$projectNumber   = if ($ProjectNumber)   { $ProjectNumber }   else { $n.projectNumber }
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
    Write-Output "DRY-RUN: skipping Azure login + live queries; using sample telemetry from config."
    if (-not $FoundryAccountName) { $FoundryAccountName = 'aif2<discovered>004dev' }
    Write-Output "Project RG   : $projectRg"
    Write-Output "Common RG    : $commonRg"
    $inputTokens  = ($cfg.totalUsersWithAccess * 1.3) * $activeWindowMinutes
    $outputTokens = $inputTokens * 0.011
    $requests     = 84 * $activeWindowMinutes
} else {

Write-Output "Connecting with Managed Identity..."
if ($UseCurrentLogin) {
    Write-Output "Using existing Az PowerShell login."
} elseif ($UamiClientId) {
    Connect-AzAccount -Identity -AccountId $UamiClientId | Out-Null   # project UAMI (mi-prj*)
} else {
    Connect-AzAccount -Identity | Out-Null                            # fallback: Automation Account System MI
}
if ($SubscriptionId) { Select-AzSubscription -SubscriptionId $SubscriptionId | Out-Null }
$ctx = Get-AzContext
$SubscriptionId = $ctx.Subscription.Id
Write-Output "Subscription : $SubscriptionId"
Write-Output "Project RG   : $projectRg"
Write-Output "Common RG    : $commonRg"

# Discover the project UAMI (mi-prj*) for reference/logging if not explicitly passed
if (-not $UamiClientId) {
    $uami = Get-AzResource -ResourceGroupName $projectRg -ResourceType 'Microsoft.ManagedIdentity/userAssignedIdentities' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'mi-prj*' } | Select-Object -First 1
    if ($uami) { Write-Output "Project UAMI : $($uami.Name)" }
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
Write-Output "Foundry acct : $FoundryAccountName"

if (-not $LogAnalyticsWorkspaceName) {
    $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'la-cmn-*' } | Select-Object -First 1
    if (-not $law) { $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $law) { throw "No Log Analytics workspace found in $commonRg" }
} else {
    $law = Get-AzOperationalInsightsWorkspace -ResourceGroupName $commonRg -Name $LogAnalyticsWorkspaceName
}
$workspaceId = $law.CustomerId
Write-Output "Log Analytics: $($law.Name) ($workspaceId)"

# ---- KQL: token + request rates from CognitiveServices metrics piped to Log Analytics ----
$kql = @"
AzureMetrics
| where TimeGenerated > ago(${LookbackDays}d)
| where Resource =~ '$FoundryAccountName'
| where MetricName in ('ProcessedPromptTokens','GeneratedTokens','ProcessedInferenceTokens','TotalCalls')
| summarize total=sum(Total) by MetricName
"@

try {
    $r = Invoke-AzOperationalInsightsQuery -WorkspaceId $workspaceId -Query $kql
    foreach ($row in $r.Results) {
        switch ($row.MetricName) {
            'ProcessedPromptTokens' { $inputTokens  = [double]$row.total }
            'GeneratedTokens'       { $outputTokens = [double]$row.total }
            'TotalCalls'            { $requests     = [double]$row.total }
        }
    }
} catch { Write-Warning "Log Analytics query failed: $_" }

}

$inputTpm  = if ($activeWindowMinutes) { [math]::Round($inputTokens/$activeWindowMinutes,0) } else { 0 }
$outputTpm = if ($activeWindowMinutes) { [math]::Round($outputTokens/$activeWindowMinutes,0) } else { 0 }
$rpm       = if ($activeWindowMinutes) { [math]::Round($requests/$activeWindowMinutes,0) } else { 0 }
$totalTokens = $inputTokens + $outputTokens

# ---- Discount + cost derivation ----
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
$md = @"
# Automation for the AI Factory

## Reports: Foundry models and token
Model: $($model.name) — RG ``$projectRg`` — window ${LookbackDays}d — generated $(Get-Date -Format 'yyyy-MM-dd HH:mm')

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

Write-Output $md

if ($OutputBlobStorageAccount) {
    $tmp = New-TemporaryFile; $md | Out-File -FilePath $tmp -Encoding utf8
    $sctx = (Get-AzStorageAccount -ResourceGroupName $projectRg -Name $OutputBlobStorageAccount).Context
    Set-AzStorageBlobContent -File $tmp -Container $OutputBlobContainer -Blob $OutputBlobName -Context $sctx -Force | Out-Null
    Write-Output "Report written: $OutputBlobContainer/$OutputBlobName"
}

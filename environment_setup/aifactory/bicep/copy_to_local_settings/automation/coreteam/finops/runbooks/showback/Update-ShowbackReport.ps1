<#
.SYNOPSIS
    Azure Automation Runbook: AI Factory FinOps SHOWBACK report (cross-charging, showback flavour).
    Replaces the legacy Azure DevOps pipeline `aifactory-governance/gov-cross-charging.yaml`
    (+ bicep/scripts/ado/120-124_*.sh) with a single scheduled PowerShell 7.2 runbook.

.DESCRIPTION
    SHOWBACK (not chargeback): report cost per AI Factory *project* / *environment* / *cost center*
    to give teams visibility and accountability — no billing transfer is enforced.

    Steps (mirrors the old 121->124 bash chain, but in one runbook):
      1. Resolve naming (GitHub .env / ADO variables.yaml / config) and discover ALL AI Factory
         project resource groups in the subscription by naming pattern (across all project numbers),
         same convention as CmnAIfactoryNaming.bicep / infra-project.yml. No hardcoded names.
      2. Query Azure Cost Management (ActualCost month-to-date + forecast) grouped by
         ResourceGroupName in ONE subscription-scope call (efficient vs old per-RG loop).
      3. Join each RG's `CostCenter` and `AIF-Project Owners` tags.
      4. Build a Markdown showback report grouped by project / cost center / environment with totals.
      5. Export Markdown / HTML / PDF (Export-ReportFiles) and optionally upload to the common
         data lake (Write-ReportFilesToBlob), replacing the old 123_upload_to_datalake.sh.

    Auth: Automation Account Managed Identity (System-Assigned or project UAMI mi-prj*).
    RBAC needed: 'Cost Management Reader' + 'Reader' at SUBSCRIPTION scope (see deploy-automation.bicep).
    Modules required: Az.Accounts, Az.Resources, Az.Storage (blob upload only).

.NOTES
    Config: report-config.json (naming seed + showback options). Override per-run via parameters.
    Email delivery is intentionally OUT OF SCOPE for showback (visibility, not enforcement).
    If email is later required, add Azure Communication Services / Graph in a separate step.
#>

param(
    # aifactory.aggregate-report.v1: selected-project actual cost only, no upload or global Az context.
    [string]$MonitoringRequest,
    [string]$MonitoringPython,
    # --- Identity / scope ---
    [string]$SubscriptionId,
    [string]$TenantId,
    [string]$ProjectNumber,
    [string]$ProjectResourceGroup,
    [string]$CommonResourceGroup,
    # Project UAMI client id (mi-prj*). If empty -> Automation Account System MI.
    [string]$UamiClientId,
    [string]$Env,
    [string]$LocationShort,
    [string]$AifactoryPrefix,
    [string]$AifactorySuffix,
    [string]$ProjectPrefix,
    [string]$ProjectSuffix,
    [string]$VnetResourceGroupBase,

    # --- Config + source ---
    [string]$ConfigPath = "$PSScriptRoot/report-config.json",
    [string]$ConfigJson,
    [ValidateSet('Markdown','Json')] [string]$ReportFormat = 'Markdown',
    [switch]$NoUpload,
    [ValidateSet('github','ado','config')] [string]$Source = 'config',
    [string]$SettingsPath,

    # --- Reporting window / behaviour ---
    # Currency shown in the report (cost figures use the account's billing currency).
    [string]$Currency,
    # Include a next-period forecast column (Cost Management forecast API).
    [switch]$NoForecast,
    [ValidateRange(0,90)] [int]$LookbackDays = 0,

    # --- Output: common data lake (optional; replaces old 123_upload_to_datalake.sh) ---
    [string]$OutputBlobStorageAccount,   # if empty -> discovered in common RG (dls*/*esml* datalake)
    [string]$OutputBlobContainer,        # if empty -> uses config.showback.lakeContainerName
    # Local folder for MD/HTML/PDF (used by run-and-export.ps1). Blob upload uses the common lake.
    [string]$OutDir,

    # --- Local preview: skip Azure login + live queries, use sample data from config ---
    [switch]$DryRun,
    # Use the already-signed-in Az PowerShell context instead of managed identity.
    [switch]$UseCurrentLogin
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($MonitoringRequest) {
    if (-not $MonitoringPython) { throw 'The reviewed Monitoring Python runtime is required.' }
    & $MonitoringPython -I -B "$PSScriptRoot/../common/monitoring_report.py" --request $MonitoringRequest
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
            schema_version=1; report_type='showback'; source=$(if ($DryRun) {'sample'} else {'live'})
            generated_at=[datetime]::UtcNow.ToString('o'); period=@{days=$LookbackDays}
            target=@{subscription_id=$SubscriptionId; project_resource_group=$ProjectResourceGroup; common_resource_group=$CommonResourceGroup; environment=$Env}
            status='failed'; warnings=@($reportFailure); tables=@(); charts=@(); output="# Showback report`n`n$reportFailure"
        } | ConvertTo-Json -Depth 12 -Compress | Write-Output
        exit 1
    }
    Write-Error $reportFailure
    exit 1
}
function Write-ReportInfo([string]$Message) {
    if ($ReportFormat -eq 'Json') { Write-Verbose $Message } else { Write-Output $Message }
}
function Format-Cost($Value) {
    if ($null -eq $Value) { return 'N/A' }
    return [math]::Round($Value,2)
}

$sharedModule = "$PSScriptRoot/../common/AifFactory.psm1"
if (Test-Path $sharedModule) {
    Import-Module $sharedModule -Force -WarningAction SilentlyContinue
} elseif (Get-Module -ListAvailable AifFactory) {
    Import-Module AifFactory -Force -WarningAction SilentlyContinue
} else {
    $reportFailure = 'The shared AifFactory module is unavailable. Import the existing common/AifFactory.psm1 into the Automation runtime.'
    throw $reportFailure
}

# ---------------------------------------------------------------------------
# 1) Resolve naming (param > github/ado source > config.naming)
# ---------------------------------------------------------------------------
if ($ConfigJson) { $cfg = $ConfigJson | ConvertFrom-Json }
else {
    if (-not (Test-Path $ConfigPath)) { throw "Config file not found: $ConfigPath" }
    $cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
}
$sb  = $cfg.showback
if ($sb.PSObject.Properties['includeForecast'] -and -not $sb.includeForecast) { $NoForecast = $true }
$forecastAvailable = -not $NoForecast

if ($Source -ne 'config') {
    $path = if ($SettingsPath) { $SettingsPath }
            elseif ($Source -eq 'github') { "$PSScriptRoot/../../../../.env" }
            else { "$PSScriptRoot/../../../esml-infra/azure-devops/bicep/yaml/variables/variables.yaml" }
    $n = Resolve-ProjectNaming -Source $Source -SettingsPath $path -ConfigPath $ConfigPath
} else {
    $n = $cfg.naming
}

# Effective naming (explicit params win over the resolved source)
$naming = @{
    aifactoryPrefix       = if ($AifactoryPrefix)       { $AifactoryPrefix }       else { $n.aifactoryPrefix }
    aifactorySuffix       = if ($AifactorySuffix)       { $AifactorySuffix }       else { $n.aifactorySuffix }
    projectPrefix         = if ($ProjectPrefix)         { $ProjectPrefix }         else { $n.projectPrefix }
    projectSuffix         = if ($ProjectSuffix)         { $ProjectSuffix }         else { $n.projectSuffix }
    locationShort         = if ($LocationShort)         { $LocationShort }         else { $n.locationShort }
    env                   = if ($Env)                   { $Env }                   else { $n.env }
    vnetResourceGroupBase = if ($VnetResourceGroupBase) { $VnetResourceGroupBase } else { $n.vnetResourceGroupBase }
    projectNumber         = '000' # placeholder; showback discovers ALL project numbers
}

# Common RG follows the same rule as the token report runbook.
$commonRg = "$($naming.aifactoryPrefix)$($naming.vnetResourceGroupBase)-$($naming.locationShort)-$($naming.env)$($naming.aifactorySuffix)"
if ($CommonResourceGroup) { $commonRg = $CommonResourceGroup }

# Project RG regex: {prefix}{projectPrefix}project<NNN>-{loc}-{env}{aifSuffix}{prjSuffix}
# (same pattern the legacy 121_discover_resource_groups.sh matched, but built from naming rules).
$rgRegex = '^' + [regex]::Escape("$($naming.aifactoryPrefix)$($naming.projectPrefix)project") +
           '(?<num>\d+)' + [regex]::Escape("-$($naming.locationShort)-$($naming.env)$($naming.aifactorySuffix)$($naming.projectSuffix)") + '$'

$currency = if ($Currency) { $Currency } elseif ($sb -and $sb.currency) { $sb.currency } else { 'USD' }
$reportDate = Get-Date -Format 'yyyy-MM-dd'
$periodEnd = [datetime]::UtcNow
$periodStart = if ($LookbackDays) { $periodEnd.AddDays(-$LookbackDays) } else { [datetime]::new($periodEnd.Year,$periodEnd.Month,1,0,0,0,[DateTimeKind]::Utc) }
$periodLabel = if ($LookbackDays) { "selected $LookbackDays-day window" } else { 'current billing month to date' }

Write-ReportInfo "=== AI Factory FinOps Showback Report ==="
Write-ReportInfo "Environment : $($naming.env)"
Write-ReportInfo "Common RG   : $commonRg"
Write-ReportInfo "RG pattern  : $rgRegex"

# ---------------------------------------------------------------------------
# 2) Connect + discover project resource groups
# ---------------------------------------------------------------------------
$projects = New-Object System.Collections.Generic.List[object]

if ($DryRun) {
    Write-ReportInfo "DRY-RUN: using sample data from config.showback.sampleProjects (no Azure calls)."
    $reportWarnings.Add('Sample costs only; no Azure authentication or queries were performed.')
    foreach ($p in $sb.sampleProjects) {
        if ($ProjectNumber -and $p.projectNumber -ne $ProjectNumber) { continue }
        $projects.Add([pscustomobject]@{
            ResourceGroup = $(if ($ProjectResourceGroup) {$ProjectResourceGroup} else {$p.resourceGroup}); ProjectNumber = $p.projectNumber
            CostCenter = $p.costCenter; Owner = $p.owner
            CurrentCost = [double]$p.currentCost; ForecastCost = [double]$p.forecastCost
        })
    }
} else {
    $reportFailure = 'Azure authentication or selected subscription/tenant validation failed.'
    $SubscriptionId = Connect-Aif -SubscriptionId $SubscriptionId -TenantId $TenantId -UamiClientId $UamiClientId -UseCurrentLogin:$UseCurrentLogin
    Write-ReportInfo "Subscription: $SubscriptionId"

    # Discover matching project RGs + their tags
    $reportFailure = 'Project resource-group discovery failed for the selected target.'
    $allRgs = if ($ProjectResourceGroup) { Get-AzResourceGroup -Name $ProjectResourceGroup } else { Get-AzResourceGroup }
    $matched = @{}
    foreach ($rg in $allRgs) {
        $m = [regex]::Match($rg.ResourceGroupName, $rgRegex)
        if (-not $m.Success -and -not $ProjectResourceGroup) { continue }
        if ($ProjectNumber -and -not $ProjectResourceGroup -and $m.Groups['num'].Value -ne $ProjectNumber) { continue }
        $tags = $rg.Tags
        $matched[$rg.ResourceGroupName] = [pscustomobject]@{
            ResourceGroup = $rg.ResourceGroupName
            ProjectNumber = $(if ($ProjectNumber) {$ProjectNumber} else {$m.Groups['num'].Value})
            CostCenter    = if ($tags -and $tags['CostCenter']) { $tags['CostCenter'] } else { 'Unknown' }
            Owner         = if ($tags -and $tags['AIF-Project Owners']) { $tags['AIF-Project Owners'] } else { 'Unknown' }
            CurrentCost   = $null
            ForecastCost  = $null
        }
    }
    Write-ReportInfo "Matched project resource groups: $($matched.Count)"
    if ($matched.Count -eq 0) {
        $reportFailure = 'No AI Factory project resource groups matched the selected target.'
        throw $reportFailure
    }

    # ---- 3) Cost Management: ActualCost month-to-date, grouped by ResourceGroupName ----
    $costUri = "/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    $costSpec = @{
        type      = 'ActualCost'
        timeframe = 'MonthToDate'
        dataset   = @{
            granularity = 'None'
            aggregation = @{ totalCost = @{ name = 'Cost'; function = 'Sum' } }
            grouping    = @( @{ type = 'Dimension'; name = 'ResourceGroupName' } )
        }
    }
    if ($LookbackDays) {
        $costSpec.timeframe = 'Custom'
        $costSpec.timePeriod = @{from=$periodStart.ToString('o'); to=$periodEnd.ToString('o')}
    }
    $costBody = $costSpec | ConvertTo-Json -Depth 10

    try {
        $reportFailure = 'Actual cost query failed or returned incomplete data; zero cost cannot be inferred.'
        do {
        $resp = Invoke-AzRestMethod -Method POST -Path $costUri -Payload $costBody
        if ($resp.StatusCode -ge 400) { throw "Cost query HTTP $($resp.StatusCode): $($resp.Content)" }
        $data = $resp.Content | ConvertFrom-Json
        $cols = @($data.properties.columns.name)
        $iCost = [array]::IndexOf($cols, 'Cost')
        $iRg   = [array]::IndexOf($cols, 'ResourceGroupName')
        $iCurrency = [array]::IndexOf($cols, 'Currency')
        if ($iCost -lt 0 -or $iRg -lt 0) { throw $reportFailure }
        if (-not @($data.properties.rows).Count) { $reportWarnings.Add('Cost Management returned no rows for this period; costs may not yet be available.') }
        foreach ($row in $data.properties.rows) {
            $rgName = "$($row[$iRg])"
            if ($matched.ContainsKey($rgName)) {
                $matched[$rgName].CurrentCost += [double]$row[$iCost]
                if ($iCurrency -ge 0 -and $row[$iCurrency] -ne $currency) { throw 'Billing currency does not match report configuration.' }
            }
        }
        $costUri = if ($data.properties.PSObject.Properties['nextLink']) { $data.properties.nextLink } else { $null }
        if ($costUri) {
            $nextUri = [uri]$costUri
            if ($nextUri.Scheme -ne 'https' -or $nextUri.Host -ne 'management.azure.com' -or $nextUri.AbsolutePath -ne "/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/query") { throw $reportFailure }
            $costUri = $nextUri.PathAndQuery
        }
        } while ($costUri)
    } catch { throw $reportFailure }

    # ---- Cost Management: forecast for the remainder of the current + next period ----
    if (-not $NoForecast) {
        $from = (Get-Date).ToString('yyyy-MM-01')
        $to   = (Get-Date (Get-Date).AddMonths(1).ToString('yyyy-MM-01')).AddDays(-1).ToString('yyyy-MM-dd')
        $fcUri  = "/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/forecast?api-version=2023-11-01"
        $fcBody = @{
            type       = 'ActualCost'
            timeframe  = 'Custom'
            timePeriod = @{ from = $from; to = $to }
            includeActualCost      = $true
            includeFreshPartialCost = $false
            dataset    = @{
                granularity = 'None'
                aggregation = @{ totalCost = @{ name = 'Cost'; function = 'Sum' } }
                grouping    = @( @{ type = 'Dimension'; name = 'ResourceGroupName' } )
            }
        } | ConvertTo-Json -Depth 10
        try {
            do {
            $fresp = Invoke-AzRestMethod -Method POST -Path $fcUri -Payload $fcBody
            if ($fresp.StatusCode -lt 400) {
                $fdata = $fresp.Content | ConvertFrom-Json
                $fcols = @($fdata.properties.columns.name)
                $fiCost = [array]::IndexOf($fcols, 'Cost')
                $fiRg   = [array]::IndexOf($fcols, 'ResourceGroupName')
                if ($fiCost -lt 0 -or $fiRg -lt 0 -or -not @($fdata.properties.rows).Count) { throw 'Forecast data is unavailable.' }
                foreach ($row in $fdata.properties.rows) {
                    $rgName = "$($row[$fiRg])"
                    if ($matched.ContainsKey($rgName)) { $matched[$rgName].ForecastCost += [double]$row[$fiCost] }
                }
                $fcUri = if ($fdata.properties.PSObject.Properties['nextLink']) { $fdata.properties.nextLink } else { $null }
                if ($fcUri) {
                    $nextUri = [uri]$fcUri
                    if ($nextUri.Scheme -ne 'https' -or $nextUri.Host -ne 'management.azure.com' -or $nextUri.AbsolutePath -ne "/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/forecast") { throw 'Invalid forecast continuation.' }
                    $fcUri = $nextUri.PathAndQuery
                }
            } else { throw 'Forecast query failed.' }
            } while ($fcUri)
        } catch {
            $forecastAvailable = $false
            $reportWarnings.Add('Forecast query failed or returned incomplete data. Forecast values are unavailable, not zero.')
        }
    }

    $projects.AddRange([object[]]($matched.Values))
    if (@($projects | Where-Object {$null -eq $_.CurrentCost}).Count) {
        $reportWarnings.Add('Some selected projects have no actual-cost rows. Missing costs and incomplete totals are unavailable, not zero.')
    }
    if ($forecastAvailable -and @($projects | Where-Object {$null -eq $_.ForecastCost}).Count) {
        $reportWarnings.Add('Some selected projects have no forecast rows. Missing forecasts and incomplete totals are unavailable, not zero.')
    }
}
if (-not $projects.Count) { $reportWarnings.Add('No projects were present in the selected sample or result.') }
if (-not $forecastAvailable) { foreach ($p in $projects) { $p.ForecastCost = $null } }

# ---------------------------------------------------------------------------
# 4) Build Markdown showback report
# ---------------------------------------------------------------------------
$ordered = @($projects | Sort-Object ProjectNumber)
$totalCurrent  = if ($ordered.Count) { ($ordered | Measure-Object -Property CurrentCost -Sum).Sum } else { $null }
$totalForecast = if ($ordered.Count) { ($ordered | Measure-Object -Property ForecastCost -Sum).Sum } else { $null }
if (-not $totalCurrent)  { $totalCurrent  = 0 }
if (@($ordered | Where-Object {$null -eq $_.CurrentCost}).Count) { $totalCurrent = $null }
if (-not $forecastAvailable -or @($ordered | Where-Object {$null -eq $_.ForecastCost}).Count) { $totalForecast = $null }
elseif (-not $totalForecast) { $totalForecast = 0 }

$rows = @(foreach ($p in $ordered) {
    "| project$($p.ProjectNumber) | ``$($p.ResourceGroup)`` | $($p.CostCenter) | $($p.Owner) | $(Format-Cost $p.CurrentCost) | $(Format-Cost $p.ForecastCost) |"
})

# Cost-center rollup
$byCc = @($ordered | Group-Object CostCenter | ForEach-Object {
    $ccCurrent = if (@($_.Group | Where-Object {$null -eq $_.CurrentCost}).Count) {$null} else {($_.Group | Measure-Object CurrentCost -Sum).Sum}
    $ccForecast = if (-not $forecastAvailable -or @($_.Group | Where-Object {$null -eq $_.ForecastCost}).Count) {$null} else {($_.Group | Measure-Object ForecastCost -Sum).Sum}
    "| $($_.Name) | $($_.Count) | $(Format-Cost $ccCurrent) | $(Format-Cost $ccForecast) |"
})

$md = @"
# AI Factory — FinOps Showback Report

**Type:** Showback (visibility & accountability — no billing transfer) ·
**Environment:** $($naming.env) · **Currency:** $currency · **Generated:** $reportDate

> Cost per AI Factory project / cost center for the **$periodLabel**, with an
> optional forecast for the full month. Costs come from Azure Cost Management; project ownership and
> cost center come from the ``CostCenter`` and ``AIF-Project Owners`` resource-group tags.

## Per-project showback

| Project | Resource Group | Cost Center | Owner | Current ($currency) | Forecast ($currency) |
|---|---|---|---|---:|---:|
$([string]::Join("`n", $rows))
| **TOTAL** | | | | **$(Format-Cost $totalCurrent)** | **$(Format-Cost $totalForecast)** |

## Rollup by cost center

| Cost Center | Projects | Current ($currency) | Forecast ($currency) |
|---|---:|---:|---:|
$([string]::Join("`n", $byCc))

---

*Generated by the AI Factory FinOps Showback runbook (``Update-ShowbackReport``) — replaces the legacy ``aifactory-governance/gov-cross-charging.yaml`` Azure DevOps pipeline.*
"@

if ($reportWarnings.Count) { $md += "`n`n> " + ($reportWarnings -join "`n> ") }

# ---------------------------------------------------------------------------
# 5) Export files (+ optional upload to common data lake)
# ---------------------------------------------------------------------------
$baseName = "aifactory-showback-$($naming.env)-{0:yyyyMMdd}" -f (Get-Date)

if ($OutDir) {
    $files = Export-ReportFiles -Markdown $md -BaseName $baseName -OutDir $OutDir
    Write-ReportInfo "Report files: $($files.Md)"
    if ($files.Html) { Write-ReportInfo "              $($files.Html)" }
    if ($files.Pdf)  { Write-ReportInfo "              $($files.Pdf)" }
}

if (-not $NoUpload -and -not $DryRun -and ($OutputBlobStorageAccount -or ($sb -and $sb.uploadToLake))) {
    try {
        $sa = $OutputBlobStorageAccount
        if (-not $sa) {
            $sa = (Get-AzStorageAccount -ResourceGroupName $commonRg -ErrorAction SilentlyContinue |
                   Where-Object { $_.StorageAccountName -like '*esml*' } | Select-Object -First 1).StorageAccountName
        }
        $container = if ($OutputBlobContainer) { $OutputBlobContainer } elseif ($sb.lakeContainerName) { $sb.lakeContainerName } else { 'reports' }
        if ($sa) {
            if (-not $OutDir) { $files = Export-ReportFiles -Markdown $md -BaseName $baseName -OutDir (Join-Path $env:TEMP 'aif-showback') }
            $prefix = "aifactory-governance/showback/$($naming.env)/$(Get-Date -Format 'yyyy/MM/dd')/"
            Write-ReportFilesToBlob -Files $files -ProjectRg $commonRg -StorageAccount $sa -Container $container -Prefix $prefix
            Write-ReportInfo "Uploaded to lake: $sa/$container/$prefix"
        } else { $reportWarnings.Add('No common data lake storage account found; upload was skipped.') }
    } catch { $reportWarnings.Add('Data lake upload failed; report data is still available.') }
}
if ($ReportFormat -eq 'Json') {
    $tableRows = @($ordered | ForEach-Object { ,@($_.ProjectNumber,$_.ResourceGroup,$_.CostCenter,$_.Owner,$_.CurrentCost,$_.ForecastCost) })
    [ordered]@{
        schema_version=1; report_type='showback'; source=$(if ($DryRun) {'sample'} else {'live'})
        generated_at=[datetime]::UtcNow.ToString('o')
        period=@{days=$LookbackDays; start=$periodStart.ToString('o'); end=$periodEnd.ToString('o'); actual_cost_window=$periodLabel; forecast_window='current full billing month'}
        target=@{subscription_id=$SubscriptionId; project_resource_group=$ProjectResourceGroup; common_resource_group=$commonRg; environment=$naming.env}
        status=$(if ($reportWarnings.Count) {'warning'} else {'completed'}); warnings=@($reportWarnings)
        tables=@(@{title='Per-project showback'; columns=@('Project','Resource group','Cost center','Owner',"Current ($currency)","Forecast ($currency)"); rows=$tableRows})
        charts=@(@{title='Project costs'; labels=@($ordered | ForEach-Object {$_.ProjectNumber}); series=@(
            @{name="Current ($currency)"; values=@($ordered | ForEach-Object {$_.CurrentCost})},
            @{name="Forecast ($currency)"; values=@($ordered | ForEach-Object {$_.ForecastCost})}
        )}); output=$md
    } | ConvertTo-Json -Depth 12 -Compress | Write-Output
} else { Write-Output $md }

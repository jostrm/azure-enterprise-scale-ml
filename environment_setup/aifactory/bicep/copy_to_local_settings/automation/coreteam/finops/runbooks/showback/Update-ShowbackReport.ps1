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
    # --- Identity / scope ---
    [string]$SubscriptionId,
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
    [ValidateSet('github','ado','config')] [string]$Source = 'config',
    [string]$SettingsPath,

    # --- Reporting window / behaviour ---
    # Currency shown in the report (cost figures use the account's billing currency).
    [string]$Currency,
    # Include a next-period forecast column (Cost Management forecast API).
    [switch]$NoForecast,

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

Import-Module "$PSScriptRoot/../common/AifFactory.psm1" -Force

# ---------------------------------------------------------------------------
# 1) Resolve naming (param > github/ado source > config.naming)
# ---------------------------------------------------------------------------
if (-not (Test-Path $ConfigPath)) { throw "Config file not found: $ConfigPath" }
$cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$sb  = $cfg.showback

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

# Project RG regex: {prefix}{projectPrefix}project<NNN>-{loc}-{env}{aifSuffix}{prjSuffix}
# (same pattern the legacy 121_discover_resource_groups.sh matched, but built from naming rules).
$rgRegex = '^' + [regex]::Escape("$($naming.aifactoryPrefix)$($naming.projectPrefix)project") +
           '(?<num>\d+)' + [regex]::Escape("-$($naming.locationShort)-$($naming.env)$($naming.aifactorySuffix)$($naming.projectSuffix)") + '$'

$currency = if ($Currency) { $Currency } elseif ($sb -and $sb.currency) { $sb.currency } else { 'USD' }
$reportDate = Get-Date -Format 'yyyy-MM-dd'

Write-Output "=== AI Factory FinOps Showback Report ==="
Write-Output "Environment : $($naming.env)"
Write-Output "Common RG   : $commonRg"
Write-Output "RG pattern  : $rgRegex"

# ---------------------------------------------------------------------------
# 2) Connect + discover project resource groups
# ---------------------------------------------------------------------------
$projects = New-Object System.Collections.Generic.List[object]

if ($DryRun) {
    Write-Output "DRY-RUN: using sample data from config.showback.sampleProjects (no Azure calls)."
    foreach ($p in $sb.sampleProjects) {
        $projects.Add([pscustomobject]@{
            ResourceGroup = $p.resourceGroup; ProjectNumber = $p.projectNumber
            CostCenter = $p.costCenter; Owner = $p.owner
            CurrentCost = [double]$p.currentCost; ForecastCost = [double]$p.forecastCost
        })
    }
} else {
    $SubscriptionId = Connect-Aif -SubscriptionId $SubscriptionId -UamiClientId $UamiClientId -UseCurrentLogin:$UseCurrentLogin
    Write-Output "Subscription: $SubscriptionId"

    # Discover matching project RGs + their tags
    $allRgs = Get-AzResourceGroup
    $matched = @{}
    foreach ($rg in $allRgs) {
        $m = [regex]::Match($rg.ResourceGroupName, $rgRegex)
        if (-not $m.Success) { continue }
        $tags = $rg.Tags
        $matched[$rg.ResourceGroupName] = [pscustomobject]@{
            ResourceGroup = $rg.ResourceGroupName
            ProjectNumber = $m.Groups['num'].Value
            CostCenter    = if ($tags -and $tags['CostCenter']) { $tags['CostCenter'] } else { 'Unknown' }
            Owner         = if ($tags -and $tags['AIF-Project Owners']) { $tags['AIF-Project Owners'] } else { 'Unknown' }
            CurrentCost   = 0.0
            ForecastCost  = 0.0
        }
    }
    Write-Output "Matched project resource groups: $($matched.Count)"
    if ($matched.Count -eq 0) { Write-Warning "No AI Factory project resource groups matched the naming pattern." }

    # ---- 3) Cost Management: ActualCost month-to-date, grouped by ResourceGroupName ----
    $costUri = "/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    $costBody = @{
        type      = 'ActualCost'
        timeframe = 'MonthToDate'
        dataset   = @{
            granularity = 'None'
            aggregation = @{ totalCost = @{ name = 'Cost'; function = 'Sum' } }
            grouping    = @( @{ type = 'Dimension'; name = 'ResourceGroupName' } )
        }
    } | ConvertTo-Json -Depth 10

    try {
        $resp = Invoke-AzRestMethod -Method POST -Path $costUri -Payload $costBody
        if ($resp.StatusCode -ge 400) { throw "Cost query HTTP $($resp.StatusCode): $($resp.Content)" }
        $data = $resp.Content | ConvertFrom-Json
        $cols = @($data.properties.columns.name)
        $iCost = [array]::IndexOf($cols, 'Cost')
        $iRg   = [array]::IndexOf($cols, 'ResourceGroupName')
        foreach ($row in $data.properties.rows) {
            $rgName = "$($row[$iRg])"
            if ($matched.ContainsKey($rgName)) { $matched[$rgName].CurrentCost = [double]$row[$iCost] }
        }
    } catch { Write-Warning "Actual cost query failed: $_" }

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
            $fresp = Invoke-AzRestMethod -Method POST -Path $fcUri -Payload $fcBody
            if ($fresp.StatusCode -lt 400) {
                $fdata = $fresp.Content | ConvertFrom-Json
                $fcols = @($fdata.properties.columns.name)
                $fiCost = [array]::IndexOf($fcols, 'Cost')
                $fiRg   = [array]::IndexOf($fcols, 'ResourceGroupName')
                foreach ($row in $fdata.properties.rows) {
                    $rgName = "$($row[$fiRg])"
                    if ($matched.ContainsKey($rgName)) { $matched[$rgName].ForecastCost += [double]$row[$fiCost] }
                }
            } else { Write-Warning "Forecast query HTTP $($fresp.StatusCode): $($fresp.Content)" }
        } catch { Write-Warning "Forecast query failed (non-critical): $_" }
    }

    $projects.AddRange([object[]]($matched.Values))
}

# ---------------------------------------------------------------------------
# 4) Build Markdown showback report
# ---------------------------------------------------------------------------
$ordered = $projects | Sort-Object ProjectNumber
$totalCurrent  = ($ordered | Measure-Object -Property CurrentCost  -Sum).Sum
$totalForecast = ($ordered | Measure-Object -Property ForecastCost -Sum).Sum
if (-not $totalCurrent)  { $totalCurrent  = 0 }
if (-not $totalForecast) { $totalForecast = 0 }

$rows = foreach ($p in $ordered) {
    "| project$($p.ProjectNumber) | ``$($p.ResourceGroup)`` | $($p.CostCenter) | $($p.Owner) | $([math]::Round($p.CurrentCost,2)) | $([math]::Round($p.ForecastCost,2)) |"
}

# Cost-center rollup
$byCc = $ordered | Group-Object CostCenter | ForEach-Object {
    "| $($_.Name) | $($_.Count) | $([math]::Round((($_.Group | Measure-Object CurrentCost -Sum).Sum),2)) | $([math]::Round((($_.Group | Measure-Object ForecastCost -Sum).Sum),2)) |"
}

$md = @"
# AI Factory — FinOps Showback Report

**Type:** Showback (visibility & accountability — no billing transfer) ·
**Environment:** $($naming.env) · **Currency:** $currency · **Generated:** $reportDate

> Cost per AI Factory project / cost center for the **current billing month to date**, with an
> optional forecast for the full month. Costs come from Azure Cost Management; project ownership and
> cost center come from the ``CostCenter`` and ``AIF-Project Owners`` resource-group tags.

## Per-project showback

| Project | Resource Group | Cost Center | Owner | Current ($currency) | Forecast ($currency) |
|---|---|---|---|---:|---:|
$([string]::Join("`n", $rows))
| **TOTAL** | | | | **$([math]::Round($totalCurrent,2))** | **$([math]::Round($totalForecast,2))** |

## Rollup by cost center

| Cost Center | Projects | Current ($currency) | Forecast ($currency) |
|---|---:|---:|---:|
$([string]::Join("`n", $byCc))

---

*Generated by the AI Factory FinOps Showback runbook (``Update-ShowbackReport``) — replaces the legacy ``aifactory-governance/gov-cross-charging.yaml`` Azure DevOps pipeline.*
"@

Write-Output $md

# ---------------------------------------------------------------------------
# 5) Export files (+ optional upload to common data lake)
# ---------------------------------------------------------------------------
$baseName = "aifactory-showback-$($naming.env)-{0:yyyyMMdd}" -f (Get-Date)

if ($OutDir) {
    $files = Export-ReportFiles -Markdown $md -BaseName $baseName -OutDir $OutDir
    Write-Output "Report files: $($files.Md)"
    if ($files.Html) { Write-Output "              $($files.Html)" }
    if ($files.Pdf)  { Write-Output "              $($files.Pdf)" }
}

if (-not $DryRun -and ($OutputBlobStorageAccount -or ($sb -and $sb.uploadToLake))) {
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
            Write-Output "Uploaded to lake: $sa/$container/$prefix"
        } else { Write-Warning "No common data lake storage account found in $commonRg; skipping upload." }
    } catch { Write-Warning "Data lake upload failed (non-critical): $_" }
}

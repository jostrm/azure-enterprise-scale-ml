<#
.SYNOPSIS
    Throttle (cap) or un-throttle Azure AI Foundry / Cognitive Services (and optionally AI Search)
    at a Resource Group or Subscription scope by cutting network access.

.DESCRIPTION
    "Throttle" = block all data-plane requests to the AI model endpoints so callers stop consuming tokens.
    Because AI Factory projects can be reached two ways, this script handles BOTH and is fully revertible:

      1. Public access accounts  -> set publicNetworkAccess=Disabled and networkAcls.defaultAction=Deny
      2. Private endpoint accounts -> set every APPROVED private endpoint connection to 'Rejected'

    Before changing anything, the previous state of each account is saved into resource TAGS, so
    'Unthrottle' restores the exact original configuration (only re-approves the PE connections that
    this tool rejected - it never touches connections that were already rejected/disconnected).

    Requires: Azure CLI (az) logged in, with rights to modify Microsoft.CognitiveServices/accounts
    and their privateEndpointConnections in the target scope.

.PARAMETER Action
    Throttle   - cut network access (cap consumption).
    Unthrottle - restore the saved state (remove the cap).
    Status     - show current throttle state without changing anything.

.PARAMETER Scope
    Subscription     - act on every Cognitive Services account in the subscription.
    ResourceGroup    - act only on accounts in -ResourceGroup (a single AI Factory project RG).

.PARAMETER SubscriptionId
    Target subscription id. Defaults to the current 'az account' subscription.

.PARAMETER ResourceGroup
    Required when -Scope ResourceGroup. The AI Factory project resource group name.

.PARAMETER IncludeSearch
    Also throttle Azure AI Search services (Microsoft.Search/searchServices) in scope.

.PARAMETER EsmlAifactoryExists
    When set, resource names (project RG, vnet RG/name, private DNS RG) are DERIVED from the
    AI Factory naming convention using -VarsFile (+ -Env) or the individual naming parameters,
    so you do not have to pass them. When NOT set, pass the names explicitly
    (-ResourceGroup, -VnetName, -VnetResourceGroup, -PrivateDnsResourceGroup, -StorageAccountName).

.PARAMETER VarsFile
    Path to an AI Factory variables.yaml (used with -EsmlAifactoryExists to derive names).

.PARAMETER Env
    dev | test | prod. Used with -EsmlAifactoryExists to derive names. Default: dev.

.PARAMETER DryRun
    Print the actions that would be taken without making changes.

.PARAMETER SkipReport
    Do not generate or upload a run report. By default a .md/.html/.pdf report of the run is written
    and uploaded to the target RG's primary storage account under
    'aifactory/automation/finops/reports/<yyyyMMdd>/'.

.PARAMETER ReportStorageAccount
    Explicit storage account for the report. If omitted, the AI Factory project primary account
    (sa...1...) is auto-discovered in the target resource group.

.PARAMETER ReportResourceGroup
    Resource group holding the report storage account. Defaults to the throttled -ResourceGroup.

.PARAMETER ReportContainer
    Blob container for reports. Default: 'aifactory'.

.PARAMETER ReportLocalDir
    Local directory to write the report files before upload. Default: a temp directory.

.EXAMPLE
    # AI Factory exists: derive the project RG (and vnet/DNS) from variables.yaml
    ./throttle-genai.ps1 -Action Throttle -Scope ResourceGroup -EsmlAifactoryExists `
        -VarsFile ../../../../../aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml -Env dev

.EXAMPLE
    # No AI Factory: pass names explicitly
    ./throttle-genai.ps1 -Action Throttle -Scope ResourceGroup -ResourceGroup my-genai-rg

.EXAMPLE
    # Cap a single project resource group
    ./throttle-genai.ps1 -Action Throttle -Scope ResourceGroup -ResourceGroup acme-1-esml-project001-swc-dev-001-rg

.EXAMPLE
    # Remove the cap for the whole subscription
    ./throttle-genai.ps1 -Action Unthrottle -Scope Subscription -SubscriptionId 00000000-0000-0000-0000-000000000000

.EXAMPLE
    # See what is currently throttled
    ./throttle-genai.ps1 -Action Status -Scope ResourceGroup -ResourceGroup acme-1-esml-project001-swc-dev-001-rg
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Throttle', 'Unthrottle', 'Status')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Subscription', 'ResourceGroup')]
    [string]$Scope,

    [Parameter(Mandatory = $false)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $false)]
    [string]$ResourceGroup,

    [Parameter(Mandatory = $false)]
    [switch]$IncludeSearch,

    # --- AI Factory naming ---
    [Parameter(Mandatory = $false)]
    [switch]$EsmlAifactoryExists,

    [Parameter(Mandatory = $false)]
    [string]$VarsFile,

    [Parameter(Mandatory = $false)]
    [ValidateSet('dev', 'test', 'prod')]
    [string]$Env = 'dev',

    [Parameter(Mandatory = $false)]
    [string]$ProjectNumber,

    # --- Explicit names (used when -EsmlAifactoryExists is NOT set) ---
    [Parameter(Mandatory = $false)]
    [string]$VnetResourceGroup,

    [Parameter(Mandatory = $false)]
    [string]$VnetName,

    [Parameter(Mandatory = $false)]
    [string]$PrivateDnsResourceGroup,

    [Parameter(Mandatory = $false)]
    [string]$StorageAccountName,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun,

    # --- Report output (store a run report in the target RG primary storage account) ---
    [Parameter(Mandatory = $false)]
    [switch]$SkipReport,

    [Parameter(Mandatory = $false)]
    [string]$ReportStorageAccount,

    [Parameter(Mandatory = $false)]
    [string]$ReportResourceGroup,

    [Parameter(Mandatory = $false)]
    [string]$ReportContainer = 'aifactory',

    [Parameter(Mandatory = $false)]
    [string]$ReportLocalDir
)

$ErrorActionPreference = 'Stop'

# Collects one row per resource acted on, for the run report written to blob.
$script:ReportRows = New-Object System.Collections.Generic.List[object]
function Add-ReportRow {
    param($Type, $Name, $ResourceGroup, $Result, $Detail)
    $script:ReportRows.Add([pscustomobject]@{
        Type = $Type; Name = $Name; ResourceGroup = $ResourceGroup; Result = $Result; Detail = $Detail
    })
}

# Tag keys used to preserve prior state for a clean revert.
$TAG_STATE      = 'esmlThrottleState'          # throttled | normal
$TAG_PREV_PNA   = 'esmlThrottlePrevPublicNet'  # Enabled | Disabled
$TAG_PREV_ACL   = 'esmlThrottlePrevDefaultAcl' # Allow | Deny
$TAG_PREV_PECS  = 'esmlThrottledPeConns'       # semi-colon separated PE connection names we rejected
$TAG_TIMESTAMP  = 'esmlThrottleTimestampUtc'

function Write-Info    { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Ok      { param($m) Write-Host $m -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-ErrLine { param($m) Write-Host $m -ForegroundColor Red }

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

# Reads a top-level "key: value" from an AI Factory variables.yaml (trailing ':'
# anchor avoids prefix collisions; strips inline comments and quotes).
function Get-YamlValue {
    param([string]$File, [string]$Key)
    if (-not (Test-Path $File)) { return '' }
    $line = Select-String -Path $File -Pattern "^\s*$([regex]::Escape($Key)):" | Select-Object -First 1
    if (-not $line) { return '' }
    $v = $line.Line -replace "^\s*$([regex]::Escape($Key)):\s*", ''
    $v = $v -replace '\s*#.*$', ''          # strip inline comment
    $v = $v.Trim().Trim('"').Trim("'")      # strip quotes
    return $v
}

# --- Derive AI Factory resource names when -EsmlAifactoryExists ---
if ($EsmlAifactoryExists) {
    if ([string]::IsNullOrWhiteSpace($VarsFile)) {
        throw "-EsmlAifactoryExists requires -VarsFile <path-to-variables.yaml> so names can be derived."
    }
    if (-not (Test-Path $VarsFile)) { throw "-VarsFile '$VarsFile' not found." }
    Write-Info "Deriving AI Factory resource names from '$VarsFile' (env=$Env)..."

    $prefixRG     = Get-YamlValue $VarsFile 'admin_aifactoryPrefixRG'
    $projectPrefix = Get-YamlValue $VarsFile 'projectPrefix'
    $projectSuffix = Get-YamlValue $VarsFile 'projectSuffix'
    $projNum      = Get-YamlValue $VarsFile 'project_number_000'
    $locSuffix    = Get-YamlValue $VarsFile 'admin_locationSuffix'
    $suffixRG     = Get-YamlValue $VarsFile 'admin_aifactorySuffixRG'
    $commonSuffix = Get-YamlValue $VarsFile 'admin_commonResourceSuffix'
    $vnetNameBase = Get-YamlValue $VarsFile 'vnetNameBase'
    $vnetRgBase   = Get-YamlValue $VarsFile 'vnetResourceGroupBase'
    $vnetRgParam  = Get-YamlValue $VarsFile 'vnetResourceGroup_param'
    $vnetNameParam = Get-YamlValue $VarsFile 'vnetNameFull_param'

    switch ($Env) {
        'dev'  { $derivedSub = Get-YamlValue $VarsFile 'dev_sub_id' }
        'test' { $derivedSub = Get-YamlValue $VarsFile 'test_sub_id' }
        'prod' { $derivedSub = Get-YamlValue $VarsFile 'prod_sub_id' }
    }

    if ([string]::IsNullOrWhiteSpace($ProjectNumber)) { $ProjectNumber = $projNum }

    # Project resource group (== job-2 targetResourceGroup)
    $derivedProjectRG = "${prefixRG}${projectPrefix}project${ProjectNumber}-${locSuffix}-${Env}${suffixRG}${projectSuffix}"

    # VNet RG: honor BYO vnetResourceGroup_param, else common-RG fallback
    $derivedVnetRG = if (-not [string]::IsNullOrWhiteSpace($vnetRgParam)) { $vnetRgParam }
                     else { "${prefixRG}${vnetRgBase}-${locSuffix}-${Env}${suffixRG}" }

    # VNet name: honor BYO vnetNameFull_param, else common-vnet fallback
    $derivedVnetName = if (-not [string]::IsNullOrWhiteSpace($vnetNameParam)) { $vnetNameParam }
                       else { "${vnetNameBase}-${locSuffix}-${Env}${commonSuffix}" }

    # Fill ONLY the values the caller did not pass explicitly (CLI wins).
    if ([string]::IsNullOrWhiteSpace($SubscriptionId))          { $SubscriptionId = $derivedSub }
    if ([string]::IsNullOrWhiteSpace($ResourceGroup))           { $ResourceGroup = $derivedProjectRG }
    if ([string]::IsNullOrWhiteSpace($VnetResourceGroup))       { $VnetResourceGroup = $derivedVnetRG }
    if ([string]::IsNullOrWhiteSpace($VnetName))                { $VnetName = $derivedVnetName }
    # Private DNS zones for AI Factory live in the vnet/common RG by convention.
    if ([string]::IsNullOrWhiteSpace($PrivateDnsResourceGroup)) { $PrivateDnsResourceGroup = $derivedVnetRG }

    Write-Ok "  project RG        : $ResourceGroup"
    Write-Ok "  vnet RG           : $VnetResourceGroup"
    Write-Ok "  vnet name         : $VnetName"
    Write-Ok "  private DNS RG    : $PrivateDnsResourceGroup"
}

if ($Scope -eq 'ResourceGroup' -and [string]::IsNullOrWhiteSpace($ResourceGroup)) {
    throw "-ResourceGroup is required when -Scope is 'ResourceGroup' (or use -EsmlAifactoryExists -VarsFile ... to derive it)."
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI ('az') was not found on PATH. Install it and 'az login' first."
}

if ([string]::IsNullOrWhiteSpace($SubscriptionId)) {
    $SubscriptionId = (az account show --query id -o tsv)
    if ([string]::IsNullOrWhiteSpace($SubscriptionId)) { throw "Not logged in. Run 'az login'." }
}
Write-Info "Using subscription: $SubscriptionId"
az account set --subscription $SubscriptionId | Out-Null

# ---------------------------------------------------------------------------
# Discover Cognitive Services (AI Foundry / OpenAI / AI Services) accounts
# ---------------------------------------------------------------------------
function Get-CognitiveAccounts {
    if ($Scope -eq 'ResourceGroup') {
        $json = az resource list --resource-group $ResourceGroup --resource-type 'Microsoft.CognitiveServices/accounts' -o json
    }
    else {
        $json = az resource list --resource-type 'Microsoft.CognitiveServices/accounts' -o json
    }
    return ($json | ConvertFrom-Json)
}

function Get-SearchServices {
    if ($Scope -eq 'ResourceGroup') {
        $json = az resource list --resource-group $ResourceGroup --resource-type 'Microsoft.Search/searchServices' -o json
    }
    else {
        $json = az resource list --resource-type 'Microsoft.Search/searchServices' -o json
    }
    return ($json | ConvertFrom-Json)
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Get-AccountShow {
    param($rg, $name)
    return (az cognitiveservices account show -g $rg -n $name -o json | ConvertFrom-Json)
}

function Get-Tag {
    param($tags, $key)
    if ($null -eq $tags) { return $null }
    if ($tags.PSObject.Properties.Name -contains $key) { return $tags.$key }
    return $null
}

function Set-AccountTags {
    param($rg, $name, [hashtable]$tags)
    $pairs = @()
    foreach ($k in $tags.Keys) { $pairs += "$k=$($tags[$k])" }
    if ($DryRun) { Write-Warn "  [DryRun] would set tags: $($pairs -join ' ')"; return }
    az resource tag --ids (az cognitiveservices account show -g $rg -n $name --query id -o tsv) --tags @pairs --is-incremental | Out-Null
}

function Get-ApprovedPeConnections {
    param($accountId)
    $json = az network private-endpoint-connection list --id $accountId -o json 2>$null
    if ([string]::IsNullOrWhiteSpace($json)) { return @() }
    $all = $json | ConvertFrom-Json
    return @($all | Where-Object { $_.properties.privateLinkServiceConnectionState.status -eq 'Approved' })
}

# ---------------------------------------------------------------------------
# THROTTLE one cognitive account
# ---------------------------------------------------------------------------
function Invoke-ThrottleAccount {
    param($acct)
    $rg = $acct.resourceGroup
    $name = $acct.name
    Write-Info "-> Cognitive account: $name (rg: $rg)"

    $show = Get-AccountShow -rg $rg -name $name
    $current = Get-Tag $show.tags $TAG_STATE
    if ($current -eq 'throttled') {
        Write-Warn "   already throttled - skipping"
        Add-ReportRow -Type 'CognitiveServices' -Name $name -ResourceGroup $rg -Result 'Skipped' -Detail 'Already throttled'
        return
    }

    $prevPna = if ($show.properties.publicNetworkAccess) { $show.properties.publicNetworkAccess } else { 'Enabled' }
    $prevAcl = if ($show.properties.networkAcls.defaultAction) { $show.properties.networkAcls.defaultAction } else { 'Allow' }

    # 1) Reject approved private endpoint connections (private access path)
    $approved = Get-ApprovedPeConnections -accountId $show.id
    $rejectedNames = @()
    foreach ($pec in $approved) {
        Write-Info "   rejecting private endpoint connection: $($pec.name)"
        if (-not $DryRun) {
            az network private-endpoint-connection reject --id $pec.id `
                --description "Throttled by esml aimodel-throttling on $(Get-Date -AsUTC -Format o)" | Out-Null
        }
        $rejectedNames += $pec.name
    }

    # 2) Block public access path (generic resource patch is reliable across api-versions)
    Write-Info "   setting publicNetworkAccess=Disabled, networkAcls.defaultAction=Deny"
    if (-not $DryRun) {
        az resource update --ids $show.id `
            --set properties.publicNetworkAccess=Disabled properties.networkAcls.defaultAction=Deny | Out-Null
    }

    # 3) Persist previous state so we can revert exactly
    Set-AccountTags -rg $rg -name $name -tags @{
        $TAG_STATE     = 'throttled'
        $TAG_PREV_PNA  = $prevPna
        $TAG_PREV_ACL  = $prevAcl
        $TAG_PREV_PECS = ($rejectedNames -join ';')
        $TAG_TIMESTAMP = (Get-Date -AsUTC -Format o)
    }
    Write-Ok  "   throttled (prev publicNet=$prevPna, prev acl=$prevAcl, PEs rejected=$($rejectedNames.Count))"
    Add-ReportRow -Type 'CognitiveServices' -Name $name -ResourceGroup $rg `
        -Result $(if ($DryRun) { 'Throttled (DryRun)' } else { 'Throttled' }) `
        -Detail "prev publicNet=$prevPna; prev acl=$prevAcl; PEs rejected=$($rejectedNames.Count)"
}

# ---------------------------------------------------------------------------
# UNTHROTTLE one cognitive account
# ---------------------------------------------------------------------------
function Invoke-UnthrottleAccount {
    param($acct)
    $rg = $acct.resourceGroup
    $name = $acct.name
    Write-Info "-> Cognitive account: $name (rg: $rg)"

    $show = Get-AccountShow -rg $rg -name $name
    $state = Get-Tag $show.tags $TAG_STATE
    if ($state -ne 'throttled') {
        Write-Warn "   not throttled by this tool - skipping"
        Add-ReportRow -Type 'CognitiveServices' -Name $name -ResourceGroup $rg -Result 'Skipped' -Detail 'Not throttled by this tool'
        return
    }

    $prevPna = Get-Tag $show.tags $TAG_PREV_PNA; if (-not $prevPna) { $prevPna = 'Enabled' }
    $prevAcl = Get-Tag $show.tags $TAG_PREV_ACL; if (-not $prevAcl) { $prevAcl = 'Allow' }
    $pecs    = Get-Tag $show.tags $TAG_PREV_PECS

    # 1) Restore public access path
    Write-Info "   restoring publicNetworkAccess=$prevPna, networkAcls.defaultAction=$prevAcl"
    if (-not $DryRun) {
        az resource update --ids $show.id `
            --set properties.publicNetworkAccess=$prevPna properties.networkAcls.defaultAction=$prevAcl | Out-Null
    }

    # 2) Re-approve only the PE connections we rejected
    if (-not [string]::IsNullOrWhiteSpace($pecs)) {
        foreach ($pecName in ($pecs -split ';' | Where-Object { $_ })) {
            Write-Info "   approving private endpoint connection: $pecName"
            if (-not $DryRun) {
                az network private-endpoint-connection approve `
                    --resource-name $name -g $rg --name $pecName `
                    --type 'Microsoft.CognitiveServices/accounts' `
                    --description "Un-throttled by esml aimodel-throttling on $(Get-Date -AsUTC -Format o)" 2>$null | Out-Null
            }
        }
    }

    # 3) Clear the throttle tags
    if (-not $DryRun) {
        az resource tag --ids $show.id --tags "$TAG_STATE=normal" --is-incremental | Out-Null
    }
    Write-Ok "   un-throttled (restored)"
    Add-ReportRow -Type 'CognitiveServices' -Name $name -ResourceGroup $rg `
        -Result $(if ($DryRun) { 'Un-throttled (DryRun)' } else { 'Un-throttled' }) `
        -Detail "restored publicNet=$prevPna; acl=$prevAcl"
}

# ---------------------------------------------------------------------------
# STATUS one cognitive account
# ---------------------------------------------------------------------------
function Show-AccountStatus {
    param($acct)
    $show = Get-AccountShow -rg $acct.resourceGroup -name $acct.name
    $state = Get-Tag $show.tags $TAG_STATE
    if (-not $state) { $state = 'normal' }
    $pna = $show.properties.publicNetworkAccess
    $acl = $show.properties.networkAcls.defaultAction
    $color = if ($state -eq 'throttled') { 'Red' } else { 'Green' }
    Write-Host ("  {0,-45} state={1,-9} publicNet={2,-9} acl={3}" -f $acct.name, $state, $pna, $acl) -ForegroundColor $color
    Add-ReportRow -Type 'CognitiveServices' -Name $acct.name -ResourceGroup $acct.resourceGroup -Result "state=$state" -Detail "publicNet=$pna; acl=$acl"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
$accounts = Get-CognitiveAccounts
if (-not $accounts -or $accounts.Count -eq 0) {
    Write-Warn "No Microsoft.CognitiveServices/accounts found in scope."
}
else {
    Write-Info "Found $($accounts.Count) Cognitive Services account(s) in scope '$Scope'."
    foreach ($a in $accounts) {
        switch ($Action) {
            'Throttle'   { Invoke-ThrottleAccount   -acct $a }
            'Unthrottle' { Invoke-UnthrottleAccount -acct $a }
            'Status'     { Show-AccountStatus        -acct $a }
        }
    }
}

if ($IncludeSearch) {
    $searches = Get-SearchServices
    if ($searches -and $searches.Count -gt 0) {
        Write-Info "Found $($searches.Count) AI Search service(s) in scope."
        foreach ($s in $searches) {
            $rg = $s.resourceGroup; $name = $s.name
            switch ($Action) {
                'Throttle' {
                    Write-Info "-> AI Search: $name (rg: $rg) -> publicNetworkAccess=Disabled"
                    if (-not $DryRun) { az search service update -g $rg -n $name --public-access disabled | Out-Null }
                    Add-ReportRow -Type 'AISearch' -Name $name -ResourceGroup $rg -Result $(if ($DryRun) { 'Throttled (DryRun)' } else { 'Throttled' }) -Detail 'publicNetworkAccess=Disabled'
                }
                'Unthrottle' {
                    Write-Info "-> AI Search: $name (rg: $rg) -> publicNetworkAccess=Enabled"
                    if (-not $DryRun) { az search service update -g $rg -n $name --public-access enabled | Out-Null }
                    Add-ReportRow -Type 'AISearch' -Name $name -ResourceGroup $rg -Result $(if ($DryRun) { 'Un-throttled (DryRun)' } else { 'Un-throttled' }) -Detail 'publicNetworkAccess=Enabled'
                }
                'Status' {
                    $pna = az search service show -g $rg -n $name --query publicNetworkAccess -o tsv 2>$null
                    Write-Host ("  {0,-45} publicNet={1}" -f $name, $pna)
                    Add-ReportRow -Type 'AISearch' -Name $name -ResourceGroup $rg -Result "publicNet=$pna" -Detail ''
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Run report -> target RG primary storage account
#   Container : $ReportContainer (default 'aifactory')
#   Blob path : automation/finops/reports/<yyyyMMdd>/throttle-report-<action>-<utc>.{md,html,pdf}
# ---------------------------------------------------------------------------

# Best-effort discovery of the AI Factory project PRIMARY storage account (sa...1...) in a RG.
# The live name carries an unpredictable salt, so we discover by type and prefer the '1' (primary)
# over the '2' (secondary) account. Pass -ReportStorageAccount / -StorageAccountName to be explicit.
function Resolve-PrimaryStorageAccount {
    param([string]$Rg)
    $json = az storage account list --resource-group $Rg --query "[].name" -o json 2>$null
    if ([string]::IsNullOrWhiteSpace($json)) { return $null }
    $names = @($json | ConvertFrom-Json | Where-Object { $_ -like 'sa*' })
    if ($names.Count -eq 0) { $names = @($json | ConvertFrom-Json) }   # fall back to any account
    if ($names.Count -eq 0) { return $null }
    if ($names.Count -eq 1) { return $names[0] }
    # Prefer the primary '1' account when a matching '2' sibling exists (sa...1... vs sa...2...).
    foreach ($n in $names) {
        if ($n -match '1' -and ($names -contains ($n -replace '1', '2'))) { return $n }
    }
    return ($names | Sort-Object)[0]
}

# Markdown -> minimal styled HTML (reuses the finops runbook renderer when reachable).
function Convert-ThrottleReportToHtml {
    param([string]$Markdown, [string]$Title)
    $mod = Join-Path $PSScriptRoot '..\..\..\runbooks\common\AifFactory.psm1'
    if (Test-Path $mod) {
        try {
            Import-Module $mod -Force -ErrorAction Stop
            return (ConvertTo-ReportHtml -Markdown $Markdown -Title $Title)
        } catch { }
    }
    $body = ($Markdown -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;')
    @"
<!doctype html><html><head><meta charset='utf-8'><title>$Title</title>
<style>body{font-family:Segoe UI,Arial;margin:32px;color:#222}pre{white-space:pre-wrap;font-family:Consolas,monospace;font-size:13px}</style>
</head><body><pre>$body</pre></body></html>
"@
}

# Produces .md/.html and a best-effort .pdf (headless Edge/Chrome, else PSWritePDF, else html only).
function Export-ThrottleReportFiles {
    param([string]$Markdown, [string]$BaseName, [string]$OutDir)
    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
    $OutDir = (Resolve-Path $OutDir).Path
    $md = Join-Path $OutDir "$BaseName.md"; $html = Join-Path $OutDir "$BaseName.html"; $pdf = Join-Path $OutDir "$BaseName.pdf"
    $Markdown | Out-File $md -Encoding utf8
    (Convert-ThrottleReportToHtml -Markdown $Markdown -Title $BaseName) | Out-File $html -Encoding utf8
    $browser = @('msedge', 'chrome') | ForEach-Object { (Get-Command $_ -EA SilentlyContinue).Source } | Where-Object { $_ } | Select-Object -First 1
    if (-not $browser) { foreach ($p in 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', 'C:\Program Files\Microsoft\Edge\Application\msedge.exe', 'C:\Program Files\Google\Chrome\Application\chrome.exe') { if (Test-Path $p) { $browser = $p; break } } }
    if ($browser) {
        $uri = 'file:///' + ((Resolve-Path $html).Path -replace '\\', '/')
        $prof = Join-Path ([System.IO.Path]::GetTempPath()) ('aifpdf-' + (Get-Random))
        $eargs = @('--headless=new', '--disable-gpu', '--no-pdf-header-footer', "--user-data-dir=$prof", "--print-to-pdf=$pdf", $uri)
        $proc = Start-Process $browser -ArgumentList $eargs -PassThru -WindowStyle Hidden
        if (-not $proc.WaitForExit(20000)) { try { $proc.Kill() } catch { } }
        Remove-Item $prof -Recurse -Force -EA SilentlyContinue
    }
    if (-not (Test-Path $pdf) -and (Get-Module -ListAvailable PSWritePDF)) {
        Import-Module PSWritePDF; ConvertTo-PDF -InputFile $html -OutputFile $pdf -ErrorAction SilentlyContinue
    }
    [pscustomobject]@{ Md = $md; Html = $html; Pdf = ((Test-Path $pdf) ? $pdf : $null) }
}

if (-not $SkipReport) {
    $utc       = Get-Date -AsUTC
    $dateDir   = $utc.ToString('yyyyMMdd')
    $stamp     = $utc.ToString('yyyyMMddTHHmmssZ')
    $baseName  = "throttle-report-$($Action.ToLower())-$stamp"
    $blobPrefix = "automation/finops/reports/$dateDir/"

    # Build the Markdown report from the collected rows.
    $rowsMd = if ($script:ReportRows.Count -gt 0) {
        ($script:ReportRows | ForEach-Object { "| $($_.Type) | $($_.Name) | $($_.ResourceGroup) | $($_.Result) | $($_.Detail) |" }) -join "`n"
    } else { "| _(none)_ | | | | |" }

    $reportMd = @"
# GenAI throttle run report

| Field | Value |
|-------|-------|
| Action | $Action |
| Scope | $Scope |
| Subscription | $SubscriptionId |
| Resource group | $(if ($ResourceGroup) { $ResourceGroup } else { '(subscription-wide)' }) |
| Include AI Search | $([bool]$IncludeSearch) |
| Dry run | $([bool]$DryRun) |
| Run (UTC) | $($utc.ToString('o')) |
| Resources acted on | $($script:ReportRows.Count) |

## Results

| Type | Name | Resource group | Result | Detail |
|------|------|----------------|--------|--------|
$rowsMd
"@

    # Where to write locally, then upload.
    $outDir = if ($ReportLocalDir) { $ReportLocalDir } else { Join-Path ([System.IO.Path]::GetTempPath()) "genai-throttle-reports/$dateDir" }
    try {
        $files = Export-ThrottleReportFiles -Markdown $reportMd -BaseName $baseName -OutDir $outDir
        $pdfNote = if ($files.Pdf) { ", $($files.Pdf)" } else { '' }
        Write-Info "Report generated: $($files.Md)$pdfNote"
    } catch {
        Write-Warn "Report generation failed: $($_.Exception.Message)"
        $files = $null
    }

    # Resolve the target storage account (primary of the throttled RG).
    $reportRg = if ($ReportResourceGroup) { $ReportResourceGroup } elseif ($ResourceGroup) { $ResourceGroup } else { '' }
    $reportSa = if ($ReportStorageAccount) { $ReportStorageAccount } elseif ($StorageAccountName) { $StorageAccountName } elseif ($reportRg) { Resolve-PrimaryStorageAccount -Rg $reportRg } else { $null }

    if ($files -and $reportSa -and $reportRg) {
        Write-Info "Uploading report to storage account '$reportSa' (rg '$reportRg') -> $ReportContainer/$blobPrefix"
        if ($DryRun) {
            Write-Warn "  [DryRun] would upload: $ReportContainer/$blobPrefix$baseName.{md,html,pdf}"
        } else {
            # Ensure the container exists (idempotent), then upload each produced file.
            az storage container create --account-name $reportSa --name $ReportContainer --auth-mode login --only-show-errors | Out-Null
            foreach ($f in @($files.Md, $files.Html, $files.Pdf)) {
                if ($f -and (Test-Path $f)) {
                    $blob = "$blobPrefix$(Split-Path $f -Leaf)"
                    az storage blob upload --account-name $reportSa --container-name $ReportContainer `
                        --name $blob --file $f --auth-mode login --overwrite --only-show-errors | Out-Null
                    Write-Ok "  uploaded: $ReportContainer/$blob"
                }
            }
        }
    } elseif (-not $reportSa) {
        Write-Warn "No target storage account resolved (subscription scope or no 'sa*' account found). Report kept locally at: $outDir"
        Write-Warn "  Pass -ReportStorageAccount <name> (+ -ReportResourceGroup <rg>) to upload."
    }
}

Write-Ok "Done. Action='$Action' Scope='$Scope'$(if($DryRun){' (DryRun - no changes made)'})."

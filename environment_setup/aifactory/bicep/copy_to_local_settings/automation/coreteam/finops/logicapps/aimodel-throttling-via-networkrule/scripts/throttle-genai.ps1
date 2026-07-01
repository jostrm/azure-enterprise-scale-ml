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
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

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
    if ($current -eq 'throttled') { Write-Warn "   already throttled - skipping"; return }

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
    if ($state -ne 'throttled') { Write-Warn "   not throttled by this tool - skipping"; return }

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
                }
                'Unthrottle' {
                    Write-Info "-> AI Search: $name (rg: $rg) -> publicNetworkAccess=Enabled"
                    if (-not $DryRun) { az search service update -g $rg -n $name --public-access enabled | Out-Null }
                }
                'Status' {
                    $pna = az search service show -g $rg -n $name --query publicNetworkAccess -o tsv 2>$null
                    Write-Host ("  {0,-45} publicNet={1}" -f $name, $pna)
                }
            }
        }
    }
}

Write-Ok "Done. Action='$Action' Scope='$Scope'$(if($DryRun){' (DryRun - no changes made)'})."

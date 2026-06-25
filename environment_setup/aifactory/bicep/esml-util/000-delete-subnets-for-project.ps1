<#
.SYNOPSIS
    Deletes the project subnets (and their NSGs) for a RANGE of AI Factory projects from a given VNet.

.DESCRIPTION
    For every project number in the range [ProjectsFrom .. ProjectsTo] this script finds and
    deletes all subnets belonging to that project (matched by the project filter token
    'prj{number}-') inside the specified VNet / resource group, then deletes the matching NSGs.

    If ProjectsFrom and ProjectsTo are the same (or ProjectsTo is omitted) only that single
    project's subnets/NSGs are deleted.

    Logic is ported from the tested scripts/delete-services-if-disabled.sh (Step 7 + Step 8):
      - Project subnets follow the pattern  snt-prj{nnn}-{purpose}
        (e.g. snt-prj003-aks, snt-prj012-genai); NSGs follow nsg-snt-prj{nnn}-{purpose}.
      - Matching is CASE-INSENSITIVE because AI Foundry capability-host /
        network-injection auto-provisioning can rewrite a name in uppercase
        (e.g. SNT-PRJ012-GENAI). A case-sensitive match would silently miss those.
      - The filter token requires the trailing dash ('prj012-') so that
        prj012 cannot accidentally match prj0120-* in a shared multi-project VNet.
      - Project numbers are zero-padded to 3 digits (002, 009, 012, ...).

    Deletion order per project (same as delete-services-if-disabled.sh):
      Pass 1: Detach NSG / RouteTable / delegations / serviceEndpoints from each subnet.
      Pass 2: Delete each subnet (SEQUENTIALLY - Azure processes only one write op per VNet).
      Step 3: Delete each NSG (with self-heal re-detach + retry).

    NOTE: Subnets with surviving Service Association Links (SALs) from ACA /
    Foundry managed environments cannot be force-removed; those release only
    when the parent service is fully deleted. Such subnets are logged and skipped.

.PARAMETER ProjectsFrom
    First project number in the range, e.g. '002'. Used to build the filter token 'prj{number}-'.

.PARAMETER ProjectsTo
    Last project number in the range, e.g. '009'. Defaults to ProjectsFrom (single project).

.PARAMETER ResourceGroupName
    The resource group that contains the VNet (the common / VNet resource group).

.PARAMETER VNetName
    The name of the VNet that contains the project subnets.

.PARAMETER SubscriptionId
    Optional. The subscription to operate in. If omitted, the current az context is used.

.PARAMETER SkipNsgDeletion
    Optional. Detach + delete subnets only, leave the NSGs in place.

.PARAMETER WhatIf
    Optional. Lists the matched subnets/NSGs and the detach/delete actions without executing them.

.EXAMPLE
    # Delete subnets + NSGs for projects 002 through 009
    ./000-delete-subnets-for-project.ps1 -ProjectsFrom 002 -ProjectsTo 009 `
        -ResourceGroupName 'acme-aif-esml-common-weu-dev-001' `
        -VNetName 'vnt-esmlcmn-weu-dev-001'

.EXAMPLE
    # Single project (002 only)
    ./000-delete-subnets-for-project.ps1 -ProjectsFrom 002 -ProjectsTo 002 `
        -ResourceGroupName 'acme-aif-esml-common-weu-dev-001' `
        -VNetName 'vnt-esmlcmn-weu-dev-001' -WhatIf
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectsFrom,

    [Parameter(Mandatory = $false)]
    [string]$ProjectsTo,

    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$VNetName,

    [Parameter(Mandatory = $false)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $false)]
    [switch]$SkipNsgDeletion,

    [Parameter(Mandatory = $false)]
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

# If ProjectsTo is omitted, operate on the single ProjectsFrom project only.
if (-not $ProjectsTo) { $ProjectsTo = $ProjectsFrom }

# Parse the range as integers (input may be zero-padded like '002')
$fromInt = [int]$ProjectsFrom
$toInt   = [int]$ProjectsTo
if ($fromInt -gt $toInt) {
    throw "ProjectsFrom ($ProjectsFrom) must be less than or equal to ProjectsTo ($ProjectsTo)."
}

Write-Host "=== Delete Project Subnets + NSGs (range) ===" -ForegroundColor Cyan
Write-Host "Resource group : $ResourceGroupName"
Write-Host "VNet           : $VNetName"
if ($fromInt -eq $toInt) {
    Write-Host "Project        : $($fromInt.ToString('D3')) (single)"
} else {
    Write-Host "Project range  : $($fromInt.ToString('D3')) .. $($toInt.ToString('D3'))"
}
Write-Host "Delete NSGs    : $(-not $SkipNsgDeletion)"
if ($WhatIf) { Write-Host "Mode           : WhatIf (no changes will be made)" -ForegroundColor Yellow }
Write-Host ""

if ($SubscriptionId) {
    Write-Host "Setting subscription: $SubscriptionId"
    az account set --subscription $SubscriptionId | Out-Null
}

# -----------------------------------------------------------------------------
# Helper: wait until the VNet is back at provisioningState=Succeeded before the
# next PATCH/DELETE. Azure serializes write operations on a single VNet —
# concurrent calls return "Bad Request". Polls up to ~2 minutes.
# -----------------------------------------------------------------------------
function Wait-VNetIdle {
    param(
        [string]$Rg,
        [string]$Vnet,
        [string]$Label
    )
    $max = 24
    for ($i = 0; $i -lt $max; $i++) {
        $state = az network vnet show -g $Rg -n $Vnet --query "provisioningState" -o tsv 2>$null
        if ([string]::IsNullOrWhiteSpace($state) -or $state -eq 'Succeeded') { return }
        Start-Sleep -Seconds 5
    }
    Write-Host "    (waited $($max * 5)s for vnet idle after $Label; last state=$state - proceeding anyway)"
}

# Verify the VNet exists
$vnetExists = az network vnet show -g $ResourceGroupName -n $VNetName --query "name" -o tsv 2>$null
if ([string]::IsNullOrWhiteSpace($vnetExists)) {
    Write-Host "VNet '$VNetName' not found in resource group '$ResourceGroupName'. Nothing to do." -ForegroundColor Yellow
    return
}

# Running totals across the whole project range
$script:deletedSubnets = 0
$script:failedSubnets  = 0
$script:deletedNsgs    = 0
$script:failedNsgs     = 0

# -----------------------------------------------------------------------------
# Detach + delete all subnets, then delete the NSGs, for ONE project token.
# Reads $ResourceGroupName / $VNetName / $WhatIf / $SkipNsgDeletion from script scope.
# -----------------------------------------------------------------------------
function Remove-ProjectNetworking {
    param([string]$Token)

    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Project token : '$Token' (case-insensitive substring)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    # -------------------------------------------------------------------------
    # Find matching project subnets.
    # IMPORTANT: filter in PowerShell, NOT in JMESPath. `lower()` is NOT a
    # built-in JMESPath function in the jmespath library azure-cli uses, so
    # server-side lower-casing throws. List all names, match case-insensitively.
    # -------------------------------------------------------------------------
    $allSubnets = az network vnet subnet list `
        --resource-group $ResourceGroupName `
        --vnet-name $VNetName `
        --query "[].name" `
        -o tsv 2>$null

    $subnets = @()
    if ($allSubnets) {
        $subnets = $allSubnets -split "`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and ($_.ToLower().Contains($Token.ToLower())) }
    }

    if (-not $subnets -or $subnets.Count -eq 0) {
        Write-Host "  No project subnets matched token '$Token' in VNet '$VNetName'." -ForegroundColor Yellow
    }
    else {
        Write-Host "  Matched $($subnets.Count) project subnet(s) in VNet '$VNetName':"
        $subnets | ForEach-Object { Write-Host "    - $_" }
        Write-Host ""

        # ---------------------------------------------------------------------
        # PASS 1: Detach NSG / RouteTable / delegations / serviceEndpoints from
        # every matched subnet. This must happen before deletion, otherwise the
        # subnet delete (and any later NSG delete) fails with in-use errors.
        # ---------------------------------------------------------------------
        Write-Host "  --- Pass 1/2: Detaching NSG / RouteTable / delegations from subnets ---"
        Wait-VNetIdle -Rg $ResourceGroupName -Vnet $VNetName -Label "pre-detach"

        foreach ($subnetName in $subnets) {
            Write-Host "  Detaching from subnet: $VNetName/$subnetName"

            $curNsg = az network vnet subnet show -g $ResourceGroupName --vnet-name $VNetName -n $subnetName --query "networkSecurityGroup.id" -o tsv 2>$null
            $curRt  = az network vnet subnet show -g $ResourceGroupName --vnet-name $VNetName -n $subnetName --query "routeTable.id" -o tsv 2>$null
            if ($curNsg -and $curNsg -ne 'None') { Write-Host "    Currently attached NSG : $curNsg" } else { Write-Host "    Currently attached NSG : (none)" }
            if ($curRt  -and $curRt  -ne 'None') { Write-Host "    Currently attached RT  : $curRt" }

            $subnetId = az network vnet subnet show -g $ResourceGroupName --vnet-name $VNetName -n $subnetName --query "id" -o tsv 2>$null
            if ([string]::IsNullOrWhiteSpace($subnetId)) {
                Write-Host "    (could not resolve subnet ARM id - skipping detach)"
                continue
            }

            if ($WhatIf) {
                Write-Host "    [WhatIf] Would clear NSG / RouteTable / delegations / serviceEndpoints on $subnetName"
                continue
            }

            # -----------------------------------------------------------------
            # WHY `az resource update --set properties.X=null`:
            #   The dedicated flags are bugged:
            #     --network-security-group "" / --route-table "" build an empty-named
            #       resource ID and 404 with InvalidResourceReference.
            #     --delegations "" / --service-endpoints "" create a single empty-named
            #       entry -> ServiceNameOnDelegationNotSpecified.
            #   `az resource update --set properties.X=null` goes through the same
            #   authenticated CLI path as the network commands and works reliably.
            # -----------------------------------------------------------------
            az resource update --ids $subnetId `
                --set properties.networkSecurityGroup=null `
                      properties.routeTable=null `
                      properties.delegations='[]' `
                      properties.serviceEndpoints='[]' 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "    az resource update PATCH failed - retrying property-by-property..." -ForegroundColor Yellow
                foreach ($prop in 'networkSecurityGroup', 'routeTable', 'delegations', 'serviceEndpoints') {
                    $val = 'null'
                    if ($prop -eq 'delegations' -or $prop -eq 'serviceEndpoints') { $val = '[]' }
                    Wait-VNetIdle -Rg $ResourceGroupName -Vnet $VNetName -Label "pre-clear-$prop"
                    az resource update --ids $subnetId --set "properties.$prop=$val" 2>&1 | Out-Null
                    if ($LASTEXITCODE -ne 0) {
                        Write-Host "    (could not clear $prop on $subnetName)"
                    } else {
                        Write-Host "    Cleared $prop on $subnetName"
                    }
                }
            } else {
                Write-Host "    PATCH accepted (NSG / RT / delegations / serviceEndpoints cleared)"
            }
            Wait-VNetIdle -Rg $ResourceGroupName -Vnet $VNetName -Label "post-detach-patch"

            $remainingNsg = az network vnet subnet show -g $ResourceGroupName --vnet-name $VNetName -n $subnetName --query "networkSecurityGroup.id" -o tsv 2>$null
            if ($remainingNsg -and $remainingNsg -ne 'None') {
                Write-Host "    NSG still attached to $subnetName after PATCH: $remainingNsg" -ForegroundColor Yellow
            } else {
                Write-Host "    NSG cleared on $subnetName (verified by GET)"
            }
        }

        # ---------------------------------------------------------------------
        # PASS 2: Delete subnets SEQUENTIALLY (one write op per VNet at a time).
        # Subnets with surviving Service Association Links cannot be removed; logged.
        # ---------------------------------------------------------------------
        Write-Host ""
        Write-Host "  --- Pass 2/2: Deleting subnets (sequential) ---"
        Wait-VNetIdle -Rg $ResourceGroupName -Vnet $VNetName -Label "pre-subnet-delete"

        foreach ($subnetName in $subnets) {
            if ($WhatIf) {
                Write-Host "  [WhatIf] Would delete subnet: $subnetName from VNet: $VNetName"
                continue
            }

            Write-Host "  Deleting subnet: $subnetName from VNet: $VNetName"
            az network vnet subnet delete -g $ResourceGroupName --vnet-name $VNetName -n $subnetName 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "    Warning: Failed to delete subnet $subnetName" -ForegroundColor Yellow
                Write-Host "    Diagnosis - remaining references on ${subnetName}:"
                az network vnet subnet show -g $ResourceGroupName --vnet-name $VNetName -n $subnetName `
                    --query "{pe:privateEndpoints, ipconfigs:ipConfigurations, sal:serviceAssociationLinks, deleg:delegations, nsg:networkSecurityGroup.id, rt:routeTable.id}" `
                    -o json 2>$null
                $script:failedSubnets++
            } else {
                Write-Host "    Subnet $subnetName deleted" -ForegroundColor Green
                $script:deletedSubnets++
            }
            # Wait for the VNet to settle before deleting the next subnet, otherwise
            # the next call hits a still-Updating VNet and returns "Bad Request".
            Wait-VNetIdle -Rg $ResourceGroupName -Vnet $VNetName -Label "delete-$subnetName"
        }
    }

    # -------------------------------------------------------------------------
    # STEP 3: Delete the project NSGs (case-insensitive match), same as Step 8
    # of delete-services-if-disabled.sh. Pass 1 already detached the subnets,
    # but a silently-failed PATCH can leave an NSG bound -> the delete returns
    # InUseNetworkSecurityGroupCannotBeDeleted, so we self-heal first.
    # -------------------------------------------------------------------------
    if ($SkipNsgDeletion) {
        Write-Host ""
        Write-Host "  --- NSG deletion skipped (-SkipNsgDeletion) ---"
        return
    }

    Write-Host ""
    Write-Host "  --- Step 3: Deleting Network Security Groups for token '$Token' ---"
    $allNsgs = az network nsg list --resource-group $ResourceGroupName --query "[].name" -o tsv 2>$null
    $nsgs = @()
    if ($allNsgs) {
        $nsgs = $allNsgs -split "`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and ($_.ToLower().Contains($Token.ToLower())) }
    }

    if (-not $nsgs -or $nsgs.Count -eq 0) {
        Write-Host "  No project NSGs matched token '$Token'." -ForegroundColor Yellow
        return
    }

    Write-Host "  Matched $($nsgs.Count) project NSG(s):"
    $nsgs | ForEach-Object { Write-Host "    - $_" }

    foreach ($nsgName in $nsgs) {
        if ($WhatIf) {
            Write-Host "  [WhatIf] Would delete NSG: $nsgName"
            continue
        }

        Write-Host "  Deleting NSG: $nsgName"

        # ---------------------------------------------------------------------
        # SELF-HEAL: re-detach any subnet still referencing this NSG, otherwise
        # the delete returns InUseNetworkSecurityGroupCannotBeDeleted.
        # ---------------------------------------------------------------------
        $stillAttached = az network nsg show -g $ResourceGroupName -n $nsgName --query "subnets[].id" -o tsv 2>$null
        if ($stillAttached) {
            Write-Host "    Self-heal: $nsgName still attached to subnets - detaching now"
            foreach ($subnetId in ($stillAttached -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
                # subnet id form: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}
                $parts = $subnetId -split '/'
                $sRg = $parts[4]; $sVnet = $parts[8]; $sSub = $parts[10]
                Write-Host "      Detaching NSG from $sRg / $sVnet / $sSub"
                Wait-VNetIdle -Rg $sRg -Vnet $sVnet -Label "pre-nsg-detach"
                az resource update --ids $subnetId --set properties.networkSecurityGroup=null 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { Write-Host "      Detach PATCH accepted" } else { Write-Host "      Detach PATCH failed" -ForegroundColor Yellow }
                Wait-VNetIdle -Rg $sRg -Vnet $sVnet -Label "post-nsg-detach"
            }
        }

        # ---------------------------------------------------------------------
        # Delete NSG with retry. "Bad Request" here is almost always a transient
        # race (parent VNet still Updating after the detach PATCH). Retry/backoff.
        # ---------------------------------------------------------------------
        $nsgDeleted = $false
        foreach ($attempt in 1, 2, 3, 4) {
            az network nsg delete -g $ResourceGroupName -n $nsgName 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "    NSG $nsgName deleted (attempt $attempt)" -ForegroundColor Green
                $nsgDeleted = $true
                break
            }
            az network nsg show -g $ResourceGroupName -n $nsgName 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "    NSG $nsgName no longer present (attempt $attempt)" -ForegroundColor Green
                $nsgDeleted = $true
                break
            }
            Write-Host "    Attempt $attempt failed for $nsgName - backing off 20s and retrying"
            Start-Sleep -Seconds 20
        }

        if ($nsgDeleted) {
            $script:deletedNsgs++
        } else {
            Write-Host "    Warning: Failed to delete NSG $nsgName after retries" -ForegroundColor Yellow
            $script:failedNsgs++
        }
    }
}

# -----------------------------------------------------------------------------
# MAIN: loop over the project range, ONE project at a time.
# -----------------------------------------------------------------------------
for ($n = $fromInt; $n -le $toInt; $n++) {
    $token = "prj$($n.ToString('D3'))-"
    Remove-ProjectNetworking -Token $token
    Write-Host ""
}

Write-Host "=== Done ===" -ForegroundColor Cyan
if ($WhatIf) {
    Write-Host "WhatIf mode: no changes were made."
} else {
    Write-Host "Subnets deleted: $script:deletedSubnets | Subnets failed/skipped: $script:failedSubnets"
    Write-Host "NSGs deleted   : $script:deletedNsgs | NSGs failed/skipped   : $script:failedNsgs"
}

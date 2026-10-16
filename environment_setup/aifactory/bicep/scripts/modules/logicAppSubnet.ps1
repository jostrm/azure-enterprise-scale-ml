function ConvertTo-NetworkBoolean {
    param([string]$Value, [string]$Name)
    if ($Value.Trim() -notmatch '^(true|false)$') {
        throw "$Name must be true or false; empty values and unresolved pipeline macros are not allowed."
    }
    return $Value.Trim() -ieq 'true'
}

function Test-LogicAppSubnetRequired {
    param([string]$EnableLogicApps, [string]$LogicAppType, [string]$ByoASEv3, [string]$EnablePublicAccessWithPerimeter)
    $enabled = ConvertTo-NetworkBoolean $EnableLogicApps 'enableLogicApps'
    $ase = ConvertTo-NetworkBoolean $ByoASEv3 'byoASEv3'
    $public = ConvertTo-NetworkBoolean $EnablePublicAccessWithPerimeter 'enablePublicAccessWithPerimeter'
    if ($LogicAppType -cnotin @('Standard', 'Consumption')) {
        throw 'logicAppType must be Standard or Consumption.'
    }
    return $enabled -and $LogicAppType -ceq 'Standard' -and -not $ase -and -not $public
}

function Get-IPv4Range {
    param([string]$Cidr)
    if ($Cidr -notmatch '^(\d{1,3}\.){3}\d{1,3}/([0-9]|[12][0-9]|3[0-2])$') {
        throw 'Expected one canonical IPv4 CIDR; refusing unsafe allocation.'
    }
    $address, $mask = $Cidr.Split('/')
    $bytes = [System.Net.IPAddress]::Parse($address).GetAddressBytes()
    [array]::Reverse($bytes)
    $start = [uint64][BitConverter]::ToUInt32($bytes, 0)
    $size = [uint64][math]::Pow(2, 32 - [int]$mask)
    if ($start % $size -ne 0) { throw 'Unaligned IPv4 CIDR; refusing unsafe allocation.' }
    return @{ Start = $start; End = $start + $size - 1; Mask = [int]$mask }
}

function Assert-LogicAppSubnet {
    param($Subnet, [string]$ExpectedId)
    if (-not $Subnet -or -not $ExpectedId -or $Subnet.Id -ine $ExpectedId) {
        throw 'Logic Apps subnet is missing or does not match the exact expected resource ID.'
    }
    if ($Subnet.ProvisioningState -ine 'Succeeded') {
        throw 'Logic Apps subnet must have provisioningState Succeeded.'
    }
    $prefixes = @((@($Subnet.AddressPrefix) + @($Subnet.AddressPrefixes)) | Where-Object { $_ })
    if (@($prefixes).Count -ne 1 -or (Get-IPv4Range $prefixes[0]).Mask -gt 26) {
        throw 'Dedicated Logic Apps subnet must be /26 or larger; no existing subnet will be resized.'
    }
    $delegations = @($Subnet.Delegations | ForEach-Object {
        if ($_.ServiceName) { $_.ServiceName } else { $_.Properties.ServiceName }
    })
    if ($delegations.Count -ne 1 -or $delegations[0] -ine 'Microsoft.Web/serverFarms') {
        throw 'Dedicated Logic Apps subnet requires only Microsoft.Web/serverFarms delegation; no existing subnet will be mutated.'
    }
    if (@($Subnet.PrivateEndpoints | Where-Object { $_ }).Count -gt 0) {
        throw 'Logic Apps outbound subnet cannot contain private endpoints; use the nondelegated GenAI subnet for inbound private endpoints.'
    }
    if (@($Subnet.IpConfigurations | Where-Object { $_ }).Count -gt 0) {
        throw 'Dedicated Logic Apps subnet cannot contain NIC IP configurations.'
    }
}

function Read-LogicAppSubnet {
    param([string]$SubnetId, [string]$SubscriptionId, [string]$ResourceGroupName, [string]$VnetName)
    if ($env:GITHUB_ACTIONS -eq 'true' -or $env:AIFACTORY_USE_AZURE_CLI -eq 'true') {
        $json = & az network vnet subnet show --ids $SubnetId --subscription $SubscriptionId --only-show-errors --output json 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'Unable to read dedicated Logic Apps subnet. Verify access and run networking before integration.' }
        return ($json -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    }
    $vnet = Get-AzVirtualNetwork -ResourceGroupName $ResourceGroupName -Name $VnetName -ErrorAction Stop
    return $vnet.Subnets | Where-Object { $_.Id -ieq $SubnetId }
}

function New-SafeProjectSubnetScheme {
    param([hashtable]$RequiredSubnets, $Vnet, [string]$ProjectNumber,
          [Parameter(Mandatory = $true)][string]$ExpectedVnetId)
    # Retain the append allocator's ordering; reuse exact project subnets before reserving any new space.
    if ($Vnet.Id -ine $ExpectedVnetId -or $Vnet.Subnets -isnot [System.Collections.IList]) {
        throw 'VNet response must match the requested resource ID and contain a complete subnet array.'
    }
    $spaces = @($Vnet.AddressSpace.AddressPrefixes)
    if ($spaces.Count -ne 1) { throw 'Automatic allocation requires a single IPv4 VNet address space; use explicitly provisioned BYO subnets otherwise.' }
    $space = Get-IPv4Range $spaces[0]
    $ranges = @()
    foreach ($subnet in $Vnet.Subnets) {
        $prefixes = @((@($subnet.AddressPrefix) + @($subnet.AddressPrefixes)) | Where-Object { $_ })
        if (@($prefixes).Count -ne 1) { throw 'Existing subnet has an unsupported address layout; refusing unsafe allocation.' }
        $range = Get-IPv4Range $prefixes[0]
        if ($range.Start -lt $space.Start -or $range.End -gt $space.End) { throw 'Existing subnet is outside the VNet address space.' }
        foreach ($prior in $ranges) {
            if ($range.Start -le $prior.End -and $range.End -ge $prior.Start) { throw 'Existing subnets overlap; refusing unsafe allocation.' }
        }
        $ranges += $range
    }
    $next = $space.Start
    if ($ranges.Count) { $next = [uint64](($ranges | Measure-Object -Property End -Maximum).Maximum) + 1 }
    $suffixes = @{
        genaiSubnetCidr='genai'; aksSubnetCidr='aks'; aks2SubnetCidr='aks-002'
        acaSubnetCidr='aca'; aca2SubnetCidr='aca-002'; webappSubnetCidr='webapp'
        dbxPubSubnetCidr='dbxpub'; dbxPrivSubnetCidr='dbxpriv'; logicappSubnetCidr='logicapp'
    }
    $result = @{}
    foreach ($entry in ($RequiredSubnets.GetEnumerator() | Sort-Object Value, Key)) {
        $existing = @($Vnet.Subnets | Where-Object { $ProjectNumber -and $_.Name -ieq "snt-prj$ProjectNumber-$($suffixes[$entry.Key])" })
        if ($existing.Count -gt 1) { throw 'Duplicate project subnet names; refusing unsafe allocation.' }
        if ($existing.Count -eq 1) {
            if ($entry.Key -eq 'logicappSubnetCidr') {
                Assert-LogicAppSubnet $existing[0] "$ExpectedVnetId/subnets/snt-prj$ProjectNumber-logicapp"
            }
            $result[$entry.Key] = @((@($existing[0].AddressPrefix) + @($existing[0].AddressPrefixes)) | Where-Object { $_ })[0]
            continue
        }
        $mask = [int]$entry.Value
        if ($mask -lt 0 -or $mask -gt 32) { throw 'Invalid subnet mask.' }
        $size = [uint64][math]::Pow(2, 32 - $mask)
        $aligned = [uint64]([math]::Ceiling($next / $size) * $size)
        if ($aligned + $size - 1 -gt $space.End) { throw 'Full VNet: insufficient safe append space. No subnet is resized or overwritten; provision explicit BYO capacity.' }
        $bytes = [BitConverter]::GetBytes([uint32]$aligned)
        [array]::Reverse($bytes)
        $result[$entry.Key] = "$([System.Net.IPAddress]::new($bytes))/$mask"
        $next = $aligned + $size
    }
    return $result
}

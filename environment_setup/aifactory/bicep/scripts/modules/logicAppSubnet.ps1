function Test-LogicAppPrivateIntegration {
    param([string]$EnableLogicApps = 'false', [string]$LogicAppType = 'Standard',
        [string]$ByoASEv3 = 'false', [string]$EnablePublicAccessWithPerimeter = 'false')
    foreach ($value in @($EnableLogicApps, $ByoASEv3, $EnablePublicAccessWithPerimeter)) {
        if ($value.Trim() -notin @('true', 'false')) { throw "Invalid Logic App networking boolean '$value'." }
    }
    if ($LogicAppType -notin @('Standard', 'Consumption')) { throw "Invalid logicAppType '$LogicAppType'." }
    return $EnableLogicApps.Trim() -eq 'true' -and $LogicAppType -eq 'Standard' -and
        $ByoASEv3.Trim() -eq 'false' -and $EnablePublicAccessWithPerimeter.Trim() -eq 'false'
}

function Assert-LogicAppSubnetId {
    param([string]$SubnetId, [string]$VnetId)
    if ($SubnetId -notmatch '^/subscriptions/[^/\s]+/resourceGroups/[^/\s]+/providers/Microsoft\.Network/virtualNetworks/[^/\s]+/subnets/[\w.-]+$' -or
        $SubnetId -match '[<>$]' -or
        $SubnetId.Substring(0, $SubnetId.LastIndexOf('/subnets/', [StringComparison]::OrdinalIgnoreCase)) -ine $VnetId) {
        throw "Logic App subnet must be an explicit valid subnet ID in the configured VNet '$VnetId'."
    }
    if (($SubnetId -split '/')[-1] -match '^snt-prj\d+-(aks(-002)?|aca(-002)?|genai|webapp|dbxpub|dbxpriv)$') {
        throw 'Logic App outbound integration requires its dedicated subnet, not an AKS, Web App or private-endpoint subnet.'
    }
}

function Assert-LogicAppSubnet {
    param($Subnet, [string]$SubnetId)
    if ($null -eq $Subnet -or $Subnet.id -ine $SubnetId) { throw "Logic App subnet read returned a missing or mismatched identity: '$SubnetId'." }
    $properties = if ($null -ne $Subnet.properties) { $Subnet.properties } else { $Subnet }
    if ($properties.provisioningState -ine 'Succeeded') {
        throw "Logic App subnet '$SubnetId' must be Succeeded before integration (state '$($properties.provisioningState)')."
    }
    $prefixes = @($properties.addressPrefix) + @($properties.addressPrefixes) | Where-Object { $_ }
    $prefixes = @($prefixes | Select-Object -Unique)
    if ($prefixes.Count -ne 1 -or $prefixes[0] -notmatch '^(\d{1,3}\.){3}\d{1,3}/(\d{1,2})$') {
        throw "Logic App subnet '$SubnetId' must have one IPv4 prefix."
    }
    $address, $mask = $prefixes[0].Split('/')
    [uint64]$number = 0
    foreach ($octet in $address.Split('.')) {
        if ([int]$octet -gt 255 -or ([int]$octet).ToString() -ne $octet) { throw 'Invalid Logic App subnet IPv4 address.' }
        $number = $number * 256 + [int]$octet
    }
    if ([int]$mask -gt 26 -or [int]$mask -lt 1 -or $number % [math]::Pow(2, 32 - [int]$mask) -ne 0) {
        throw "Logic App subnet '$SubnetId' must be aligned /26 or larger; existing subnets are never resized."
    }
    $delegations = @($properties.delegations | ForEach-Object {
        if ($null -ne $_.properties) { $_.properties.serviceName } else { $_.serviceName }
    })
    if ($delegations.Count -ne 1 -or $delegations[0] -ine 'Microsoft.Web/serverFarms') {
        throw "Logic App subnet '$SubnetId' must already be delegated only to Microsoft.Web/serverFarms; no existing subnet is redelegated."
    }
    if (@($properties.privateEndpoints | Where-Object { $_ }).Count -gt 0 -or
        @($properties.ipConfigurations | Where-Object { $_ }).Count -gt 0) {
        throw "Logic App subnet '$SubnetId' contains private endpoints or NIC IP configurations."
    }
}

function Get-ValidatedLogicAppSubnet {
    param([string]$SubnetId, [string]$VnetId)
    Assert-LogicAppSubnetId -SubnetId $SubnetId -VnetId $VnetId
    if ($env:GITHUB_ACTIONS -eq 'true' -or $env:AIFACTORY_USE_AZURE_CLI -eq 'true') {
        $raw = & az rest --method get --url "${SubnetId}?api-version=2023-09-01" --only-show-errors --output json 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Cannot verify Logic App subnet '$SubnetId': $($raw -join ' '). Rerun networking; denied reads are not absence." }
        $subnet = ($raw -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
    } else {
        $response = Invoke-AzRestMethod -Method GET -Path "${SubnetId}?api-version=2023-09-01" -ErrorAction Stop
        if ($response.StatusCode -ne 200) { throw "Cannot verify Logic App subnet '$SubnetId': HTTP $($response.StatusCode)." }
        $subnet = $response.Content | ConvertFrom-Json -ErrorAction Stop
    }
    Assert-LogicAppSubnet -Subnet $subnet -SubnetId $SubnetId
    return $subnet
}

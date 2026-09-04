[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $VaultSubscription,

    [Parameter(Mandatory = $true)]
    [string] $VaultResourceGroup,

    [Parameter(Mandatory = $true)]
    [string] $VaultName,

    [Parameter(Mandatory = $true)]
    [string] $VnetSubscription,

    [Parameter(Mandatory = $true)]
    [string] $VnetResourceGroup,

    [Parameter(Mandatory = $true)]
    [string] $VnetName,

    [string] $DnsZoneSubscription = $VnetSubscription,

    [string] $DnsZoneResourceGroup = $VnetResourceGroup
)

$ErrorActionPreference = 'Stop'

function Invoke-AzJson {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Operation,

        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    $output = & az @Arguments --only-show-errors --output json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed: $($output -join [Environment]::NewLine)"
    }

    $json = $output -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($json)) {
        return $null
    }

    return $json | ConvertFrom-Json
}

function Invoke-AzCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Operation,

        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    $output = & az @Arguments --only-show-errors --output none 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed: $($output -join [Environment]::NewLine)"
    }
}

$dnsZoneName = 'privatelink.vaultcore.azure.net'
$vaultHostName = "$VaultName.vault.azure.net"

$vault = Invoke-AzJson -Operation 'Read seeding Key Vault' -Arguments @(
    'keyvault', 'show',
    '--subscription', $VaultSubscription,
    '--resource-group', $VaultResourceGroup,
    '--name', $VaultName
)
$privateEndpointConnections = @(Invoke-AzJson -Operation 'List seeding Key Vault private endpoint connections' -Arguments @(
    'network', 'private-endpoint-connection', 'list',
    '--id', $vault.id
))

$approvedConnection = $privateEndpointConnections |
    Where-Object {
        $state = if ($null -ne $_.privateLinkServiceConnectionState) {
            $_.privateLinkServiceConnectionState.status
        }
        else {
            $_.properties.privateLinkServiceConnectionState.status
        }
        $state -eq 'Approved'
    } |
    Select-Object -First 1

if ($null -eq $approvedConnection) {
    $pendingConnection = $privateEndpointConnections |
        Where-Object {
            $state = if ($null -ne $_.privateLinkServiceConnectionState) {
                $_.privateLinkServiceConnectionState.status
            }
            else {
                $_.properties.privateLinkServiceConnectionState.status
            }
            $state -eq 'Pending'
        } |
        Select-Object -First 1

    if ($null -ne $pendingConnection) {
        Write-Host "Approving pending Key Vault private endpoint connection '$($pendingConnection.id)'."
        Invoke-AzCommand -Operation 'Approve seeding Key Vault private endpoint connection' -Arguments @(
            'network', 'private-endpoint-connection', 'approve',
            '--id', $pendingConnection.id,
            '--description', 'Approved for the AI Factory private build agent'
        )
        $privateEndpointConnections = @(Invoke-AzJson -Operation 'Refresh seeding Key Vault private endpoint connections' -Arguments @(
            'network', 'private-endpoint-connection', 'list',
            '--id', $vault.id
        ))
        $approvedConnection = $privateEndpointConnections |
            Where-Object {
                $state = if ($null -ne $_.privateLinkServiceConnectionState) {
                    $_.privateLinkServiceConnectionState.status
                }
                else {
                    $_.properties.privateLinkServiceConnectionState.status
                }
                $state -eq 'Approved'
            } |
            Select-Object -First 1
    }
}

$privateEndpointId = if ($null -ne $approvedConnection.privateEndpoint) {
    $approvedConnection.privateEndpoint.id
}
else {
    $approvedConnection.properties.privateEndpoint.id
}
if ([string]::IsNullOrWhiteSpace($privateEndpointId)) {
    $connectionStates = @(
        $privateEndpointConnections |
            ForEach-Object {
                $state = if ($null -ne $_.privateLinkServiceConnectionState) {
                    $_.privateLinkServiceConnectionState.status
                }
                else {
                    $_.properties.privateLinkServiceConnectionState.status
                }
                "$($_.name):$state"
            }
    ) -join ', '
    throw "Key Vault '$VaultName' has no approved private endpoint connection. Connections: $connectionStates"
}

$privateEndpoint = Invoke-AzJson -Operation 'Read seeding Key Vault private endpoint' -Arguments @(
    'network', 'private-endpoint', 'show',
    '--ids', $privateEndpointId
)
$privateEndpointNicId = @($privateEndpoint.networkInterfaces)[0].id
if ([string]::IsNullOrWhiteSpace($privateEndpointNicId)) {
    throw "Private endpoint '$privateEndpointId' has no network interface."
}

$privateEndpointNic = Invoke-AzJson -Operation 'Read private endpoint network interface' -Arguments @(
    'network', 'nic', 'show',
    '--ids', $privateEndpointNicId
)
$privateEndpointIp = @($privateEndpointNic.ipConfigurations)[0].privateIPAddress
if ([string]::IsNullOrWhiteSpace($privateEndpointIp)) {
    throw "Private endpoint '$privateEndpointId' has no private IP address."
}

$vnet = Invoke-AzJson -Operation 'Read build-agent VNet' -Arguments @(
    'network', 'vnet', 'show',
    '--subscription', $VnetSubscription,
    '--resource-group', $VnetResourceGroup,
    '--name', $VnetName
)
$dnsZone = $null
$dnsZoneCandidates = @(
    [pscustomobject]@{ Subscription = $DnsZoneSubscription; ResourceGroup = $DnsZoneResourceGroup },
    [pscustomobject]@{ Subscription = $VnetSubscription; ResourceGroup = $VnetResourceGroup }
)
$checkedDnsLocations = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($candidate in $dnsZoneCandidates) {
    $candidateKey = "$($candidate.Subscription)/$($candidate.ResourceGroup)"
    if ([string]::IsNullOrWhiteSpace($candidate.Subscription) -or
        [string]::IsNullOrWhiteSpace($candidate.ResourceGroup) -or
        -not $checkedDnsLocations.Add($candidateKey)) {
        continue
    }

    $output = & az network private-dns zone show `
        --subscription $candidate.Subscription `
        --resource-group $candidate.ResourceGroup `
        --name $dnsZoneName `
        --only-show-errors `
        --output json 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dnsZone = ($output -join [Environment]::NewLine) | ConvertFrom-Json
        $DnsZoneSubscription = $candidate.Subscription
        $DnsZoneResourceGroup = $candidate.ResourceGroup
        Write-Host "Using Key Vault private DNS zone from '$DnsZoneSubscription/$DnsZoneResourceGroup'."
        break
    }

    Write-Warning "Key Vault private DNS zone is unavailable at '$candidateKey': $($output -join [Environment]::NewLine)"
}
if ($null -eq $dnsZone) {
    throw "Private DNS zone '$dnsZoneName' was not found in the configured or VNet-local DNS locations."
}

$vnetLinks = @(Invoke-AzJson -Operation 'List Key Vault private DNS VNet links' -Arguments @(
    'network', 'private-dns', 'link', 'vnet', 'list',
    '--subscription', $DnsZoneSubscription,
    '--resource-group', $DnsZoneResourceGroup,
    '--zone-name', $dnsZoneName
))
$matchingVnetLink = $vnetLinks |
    Where-Object { $_.virtualNetwork.id -ieq $vnet.id } |
    Select-Object -First 1
if ($null -eq $matchingVnetLink) {
    $vnetLinkName = "$VnetName-vaultcore"
    Write-Host "Creating private DNS VNet link '$vnetLinkName'."
    Invoke-AzCommand -Operation 'Create Key Vault private DNS VNet link' -Arguments @(
        'network', 'private-dns', 'link', 'vnet', 'create',
        '--subscription', $DnsZoneSubscription,
        '--resource-group', $DnsZoneResourceGroup,
        '--zone-name', $dnsZoneName,
        '--name', $vnetLinkName,
        '--virtual-network', $vnet.id,
        '--registration-enabled', 'false'
    )
}
else {
    Write-Host "Private DNS zone is linked to VNet '$VnetName' by '$($matchingVnetLink.name)'."
}

$privateEndpointIdParts = $privateEndpointId -split '/'
if ($privateEndpointIdParts.Count -lt 9) {
    throw "Unexpected private endpoint resource ID: $privateEndpointId"
}
$privateEndpointSubscription = $privateEndpointIdParts[2]
$privateEndpointResourceGroup = $privateEndpointIdParts[4]
$privateEndpointName = $privateEndpointIdParts[8]
$dnsZoneGroups = @(Invoke-AzJson -Operation 'List private endpoint DNS zone groups' -Arguments @(
    'network', 'private-endpoint', 'dns-zone-group', 'list',
    '--subscription', $privateEndpointSubscription,
    '--resource-group', $privateEndpointResourceGroup,
    '--endpoint-name', $privateEndpointName
))
$matchingDnsZoneGroup = $dnsZoneGroups |
    Where-Object {
        @($_.privateDnsZoneConfigs) |
            Where-Object { $_.privateDnsZoneId -ieq $dnsZone.id }
    } |
    Select-Object -First 1

if ($null -eq $matchingDnsZoneGroup) {
    foreach ($dnsZoneGroup in $dnsZoneGroups) {
        Write-Host "Removing incorrect private DNS zone group '$($dnsZoneGroup.name)'."
        Invoke-AzCommand -Operation 'Remove incorrect private endpoint DNS zone group' -Arguments @(
            'network', 'private-endpoint', 'dns-zone-group', 'delete',
            '--subscription', $privateEndpointSubscription,
            '--resource-group', $privateEndpointResourceGroup,
            '--endpoint-name', $privateEndpointName,
            '--name', $dnsZoneGroup.name
        )
    }

    Write-Host "Creating Key Vault private DNS zone group on '$privateEndpointName'."
    Invoke-AzCommand -Operation 'Create Key Vault private endpoint DNS zone group' -Arguments @(
        'network', 'private-endpoint', 'dns-zone-group', 'create',
        '--subscription', $privateEndpointSubscription,
        '--resource-group', $privateEndpointResourceGroup,
        '--endpoint-name', $privateEndpointName,
        '--name', 'aifactory-seeding-keyvault',
        '--private-dns-zone', $dnsZone.id,
        '--zone-name', 'vaultcore'
    )
}
else {
    Write-Host "Private endpoint DNS zone group '$($matchingDnsZoneGroup.name)' uses the expected zone."
}

for ($attempt = 1; $attempt -le 18; $attempt++) {
    Clear-DnsClientCache -ErrorAction SilentlyContinue
    $resolvedAddresses = @(
        Resolve-DnsName -Name $vaultHostName -Type A -ErrorAction SilentlyContinue |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_.IPAddress) } |
            Select-Object -ExpandProperty IPAddress -Unique
    )
    Write-Host "Key Vault private DNS check $attempt/18: expected=$privateEndpointIp resolved=$($resolvedAddresses -join ',')"
    if ($resolvedAddresses -contains $privateEndpointIp) {
        Write-Host "Key Vault '$vaultHostName' resolves to approved private endpoint IP '$privateEndpointIp'."
        return
    }
    Start-Sleep -Seconds 10
}

throw "Key Vault '$vaultHostName' did not resolve to private endpoint IP '$privateEndpointIp'. Verify the '$dnsZoneName' zone link and private endpoint DNS zone group."

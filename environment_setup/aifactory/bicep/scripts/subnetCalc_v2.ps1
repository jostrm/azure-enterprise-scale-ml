# Description:
#   This script is used to generate ARM parameters that contain subnet addressprefix specifications.
#   The generation is based on a caluclation performed on an existing virtual network. If gaps are detected these
#   will be filled. If no gaps are found, the subnets are appended to the end of the vnet subnet list. The required subnets
#   are specified in the $requiredSubnets PSObject.

param (
    # Optional JSON files (backwards compatibility)
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar1,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar2,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar3,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar4,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar5,
    # Required
    [Parameter(Mandatory = $true, HelpMessage = "Where to place the parameters.json file")][string]$filePath,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory environment [dev,test,prod]")][string]$env,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory subscription id for environment [dev,test,prod]")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project Azure resource suffix ")][string]$prjResourceSuffix,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory suffix for COMMON resource groups [dev,test,prod]")][string]$aifactorySuffixRGADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory suffix for COMMON resources [dev,test,prod]")][string]$commonResourceSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory data center region location westeurope, swedencentral ")][string]$locationADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory data center region location suffix weu, swc ")][string]$locationSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project type:[esml,genai-1]")][string]$projectTypeADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory COMMON RG, suffix ")][string]$commonRGNamePrefixVar,
    # optional parameters
    [Parameter(Mandatory = $false, HelpMessage = "Use service principal")][switch]$useServicePrincipal = $false,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the object id for service principal")][string]$spObjId,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,

    # Optional new way - Direct inline parameters from variables.yaml (as alternative to JSON files)
    [Parameter(Mandatory = $false, HelpMessage = "AI Factory suffix for resource groups")][string]$aifactorySuffixRG,
    [Parameter(Mandatory = $false, HelpMessage = "Common resource group name prefix")][string]$commonRGNamePrefix,
    [Parameter(Mandatory = $false, HelpMessage = "Location suffix")][string]$locationSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "Azure location")][string]$location,
    [Parameter(Mandatory = $false, HelpMessage = "Common resource suffix")][string]$commonResourceSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "Virtual network name base")][string]$vnetNameBase,
    [Parameter(Mandatory = $false, HelpMessage = "Tenant ID")][string]$tenantId,
    [Parameter(Mandatory = $false, HelpMessage = "Virtual network resource group base")][string]$vnetResourceGroupBase,
    [Parameter(Mandatory = $false, HelpMessage = "Virtual network resource group parameter override")][string]$vnetResourceGroup_param,
    [Parameter(Mandatory = $false, HelpMessage = "Virtual network full name parameter override")][string]$vnetNameFull_param,

    # Optional subnet CIDR overrides (defaults match legacy values for projectTypeADO=all)
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for GenAI subnet when projectType=all")][string]$genaiSubnetCidrAll = '25',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for standalone AKS subnet when projectType=all")][string]$aksSubnetCidrAll = '26',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for Azure ML's AKS subnet when projectType=all")][string]$aks2SubnetCidrAll = '24',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for ACA subnet when projectType=all")][string]$acaSubnetCidrAll = '23',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for secondary ACA subnet when projectType=all")][string]$aca2SubnetCidrAll = '23',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for DBX public subnet when projectType=all")][string]$dbxPubSubnetCidrAll = '26',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for DBX private subnet when projectType=all")][string]$dbxPrivSubnetCidrAll = '26'
)

filter ConvertTo-BinaryIP {
    [CmdletBinding()]
    [OutputType([String])]
    param (
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
        [string]$IPAddress
    )
    try {
        $ipObj = [System.Net.IPAddress]::Parse($IPAddress)
        $binaryOctets = $ipObj.GetAddressBytes() | ForEach-Object {
            [Convert]::ToString($_, 2).PadLeft(8, '0')
        }
        Write-Output ($binaryOctets -join '.')
    } catch {
        Write-Error "Invalid IP address: $IPAddress"
    }
}

filter ConvertTo-DottedDecimalIP {
    [CmdletBinding()]
    [OutputType([System.Net.IPAddress])]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
        [String]$IPAddress
    )
    switch -regex ($IPAddress) {
        '^([01]{8}\.){3}[01]{8}$' {
            [Byte[]]$bytes = $IPAddress -split '\.' | ForEach-Object {
                [Convert]::ToByte($_, 2)
            }
            Write-Output ([System.Net.IPAddress]::new($bytes))
        }
        '^\d+$' {
            $int = [UInt32]$IPAddress
            [Byte[]]$bytes = @(
                ($int -shr 24) -band 0xFF
                ($int -shr 16) -band 0xFF
                ($int -shr 8)  -band 0xFF
                $int           -band 0xFF
            )
            Write-Output ([System.Net.IPAddress]::new($bytes))
        }
        default { Write-Error "Cannot convert this format: $IPAddress" }
    }
}

function Find-NextIpAddress {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ipAddress
    )
    $ip = [System.Net.IPAddress]::Parse($ipAddress)
    $bytes = $ip.GetAddressBytes()
    [array]::Reverse($bytes)
    $intIp = [BitConverter]::ToUInt32($bytes, 0)
    $intIp++
    $nextBytes = [BitConverter]::GetBytes($intIp)
    [array]::Reverse($nextBytes)
    return ([System.Net.IPAddress]::new($nextBytes)).ToString()
}

function Get-SubnetFitting {
    param (
        [Parameter(Mandatory = $true)][string]$addressSpace,
        [Parameter(Mandatory = $true)][string]$cidrNotation,
        [Parameter(Mandatory = $false)][string]$endAddress,
        [Parameter(Mandatory = $false)][string]$excludeAddress = "None"
    )
    $addressSpaceIp, $addressSpaceCidr = $addressSpace -split "/"
    $possibleValues = @()
    $lastBroadcast = (Get-Subnet $addressSpaceIp -MaskBits $addressSpaceCidr).BroadcastAddress.IPAddressToString
    $startIp = $addressSpaceIp

    while ($true) {
        $subnet = Get-Subnet $startIp -MaskBits $cidrNotation
        $networkAddress = $subnet.NetworkAddress.IPAddressToString

        if ($endAddress -and $networkAddress -eq $endAddress) { break }

        if ($networkAddress -ne $excludeAddress) {
            $possibleValues += $networkAddress
        }

        $currentBroadcast = $subnet.BroadcastAddress.IPAddressToString
        if ($currentBroadcast -eq $lastBroadcast) { break }

        $startIp = Find-NextIpAddress $currentBroadcast
    }
    return ,$possibleValues
}

function Get-CidrValidity {
    <#
    .SYNOPSIS
    Checks if the given subnet cidr expression is valid within an address space
    Returns booleans
    
    .PARAMETER subnetCidr
    A string value that represents a possible subnet

    .PARAMETER possibleValues
    An array with all valid values. Such an array is calculated with the Get-SubnetFitting function
    
    .EXAMPLE
    Get-CidrValidity  subnetCidr "10.100.1.0" possibleValues $(Get-SubnetFitting  -addressSpace "10.100.0.0/16" -cidrNotation "/24")
    #>
    param (
        $subnetCidr,
        $possibleValues
    )
    if ($possibleValues.Contains($subnetCidr)) {
        return $true
    }
    else {
        return $false
    }
}

function Find-GapsInVnet {
    param (
        [Parameter(Mandatory = $true)]$vnetObj,
        [Parameter(Mandatory = $true)]$cidrs
    )

    $gaps = [PSCustomObject]@{
        allocatableNetworks = [PSCustomObject]@{}
    }

    # Prepare unique CIDRs to calculate
    $cidrsToCalculate = @($cidrs.GetEnumerator() | ForEach-Object { $_.value }) | Select-Object -Unique
    foreach ($cidr in $cidrsToCalculate) {
        $gaps.allocatableNetworks | Add-Member -Name $cidr -Type NoteProperty -Value @()
    }

    $vnetAddressSpaceSize = $vnetObj.AddressSpace.AddressPrefixes[0].split("/")[1]
    $existingSubnetCidrNotations = @($vnetObj.Subnets | ForEach-Object { $_.AddressPrefix } | Sort-Object)
    $existingSubnetAddresses = @($existingSubnetCidrNotations | ForEach-Object { $_.Split("/")[0] })

    for ($index = 0; $index -lt $existingSubnetCidrNotations.Count; $index++) {
        $current = $existingSubnetCidrNotations[$index]
        $address, $cidr = $current -split "/"
        $subnetObj = Get-Subnet $address -MaskBits $cidr
        $nextAddress = Find-NextIpAddress -ipAddress $subnetObj.BroadcastAddress.IPAddressToString

        $endAddress = $null
        if ($index + 1 -lt $existingSubnetCidrNotations.Count) {
            $endAddress = $existingSubnetCidrNotations[$index + 1].split("/")[0]
        }

        foreach ($calcCidr in $cidrsToCalculate) {
            if (-not $existingSubnetAddresses.Contains($nextAddress)) {
                $identifiedSubnetRanges = Get-SubnetFitting `
                    -addressSpace "$nextAddress/$vnetAddressSpaceSize" `
                    -cidrNotation $calcCidr `
                    -endAddress $endAddress `
                    -excludeAddress $address `
                    -ErrorAction Stop
                foreach ($x in $identifiedSubnetRanges) {
                    $gaps.allocatableNetworks.$calcCidr += $x
                }
            }
        }
    }
    return $gaps
}
function New-SubnetScheme {
    param (
        [Parameter(Mandatory = $true)]$map,
        [Parameter(Mandatory = $true)]$startIp,
        [Parameter(Mandatory = $true)]$possibleValuesMap,
        [Parameter(Mandatory = $false)][int]$maxRetries = 10
    )
    # Sort by subnet size descending (largest first)
    $sortedSubnetMap = $map.GetEnumerator() | Sort-Object -Property Value -Descending
    $allocatedIps = @()
    $result = @{}
    $startIpVnet = ($startIp -split '\.')[0..1] -join '.' # More robust vNet prefix
    $retryCount = @{}

    for ($index = 0; $index -lt $sortedSubnetMap.Count; $index++) {
        $currentKey = $sortedSubnetMap[$index].Key
        $currentValue = $sortedSubnetMap[$index].Value

        # Initialize retry counter for this subnet if not exists
        if (-not $retryCount.ContainsKey($currentKey)) {
            $retryCount[$currentKey] = 0
        }

        # If value is just a subnet mask (e.g., '24'), calculate CIDR
        if ($currentValue -match '^\d{1,2}$') {
            $subnet = Get-Subnet $startIp -MaskBits $currentValue
            $valid = Get-CidrValidity -subnetCidr $startIp -possibleValues $possibleValuesMap[$currentValue]

            if ($valid -and ($allocatedIps -notcontains $startIp)) {
                $result[$currentKey] = "$startIp/$currentValue"
                $allocatedIps += $startIp
                $startIp = Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString
                # Reset retry counter on success
                $retryCount[$currentKey] = 0
            } else {
                $retryCount[$currentKey]++
                
                if ($retryCount[$currentKey] -gt $maxRetries) {
                    Write-Host "Warning: Maximum retry attempts ($maxRetries) reached for subnet $currentKey. Skipping to next subnet."
                    continue
                }
                
                $startIp = Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString
                $currentVnet = ($startIp -split '\.')[0..1] -join '.'
                Write-Host "Start vNet $startIpVnet"
                Write-Host "Current vNet $currentVnet"
                if ($startIpVnet -ne $currentVnet) {
                    Write-Host "Error! Full vNet, cannot Find-NextIpAddress. Create new vNet or increase existing vNet - $startIpVnet"
                    break
                }
                # Decrement $index to retry the same subnet with the new IP address
                $index--
                continue
            }
        } else {
            # Already a full CIDR, just assign
            $result[$currentKey] = $currentValue
        }
    }
    return $result
}
Import-Module -Name "./modules/pipelineFunctions.psm1"
Import-Dependencies

# This function will convert the parameters nest of the arm tempate parameters file to global variables
if ($bicepPar1 -and $bicepPar2 -and $bicepPar3 -and $bicepPar4 -and $bicepPar5) {
    Write-Host "Loading parameters from JSON files..."
    $jsonParameters1 = Get-Content -Path $bicepPar1 | ConvertFrom-Json
    $jsonParameters2 = Get-Content -Path $bicepPar2 | ConvertFrom-Json
    $jsonParameters3 = Get-Content -Path $bicepPar3 | ConvertFrom-Json
    $jsonParameters4 = Get-Content -Path $bicepPar4 | ConvertFrom-Json
    $jsonParameters5 = Get-Content -Path $bicepPar5 | ConvertFrom-Json

    # all values that are present in parameters.json will be converted to variables
    ConvertTo-Variables -InputObject $jsonParameters1
    ConvertTo-Variables -InputObject $jsonParameters2
    ConvertTo-Variables -InputObject $jsonParameters3
    ConvertTo-Variables -InputObject $jsonParameters4
    ConvertTo-Variables -InputObject $jsonParameters5
}
else {
    Write-Host "Using inline parameters instead of JSON files..."
    # Use inline parameters when JSON files are not provided
}

# Override with inline parameters if they are provided (takes precedence over JSON)
if ($PSBoundParameters.ContainsKey('aifactorySuffixRG') -and $aifactorySuffixRG) { 
    Write-Host "Using inline parameter: aifactorySuffixRG = $aifactorySuffixRG"
}
if ($PSBoundParameters.ContainsKey('commonRGNamePrefix') -and $commonRGNamePrefix) { 
    Write-Host "Using inline parameter: commonRGNamePrefix = $commonRGNamePrefix"
}
if ($PSBoundParameters.ContainsKey('locationSuffix') -and $locationSuffix) { 
    Write-Host "Using inline parameter: locationSuffix = $locationSuffix"
}
if ($PSBoundParameters.ContainsKey('location') -and $location) { 
    Write-Host "Using inline parameter: location = $location"
}
if ($PSBoundParameters.ContainsKey('commonResourceSuffix') -and $commonResourceSuffix) { 
    Write-Host "Using inline parameter: commonResourceSuffix = $commonResourceSuffix"
}
if ($PSBoundParameters.ContainsKey('vnetNameBase') -and $vnetNameBase) { 
    Write-Host "Using inline parameter: vnetNameBase = $vnetNameBase"
}
if ($PSBoundParameters.ContainsKey('tenantId') -and $tenantId) { 
    Write-Host "Using inline parameter: tenantId = $tenantId"
}
if ($PSBoundParameters.ContainsKey('vnetResourceGroupBase') -and $vnetResourceGroupBase) { 
    Write-Host "Using inline parameter: vnetResourceGroupBase = $vnetResourceGroupBase"
}
if ($PSBoundParameters.ContainsKey('vnetResourceGroup_param') -and $vnetResourceGroup_param) { 
    Write-Host "Using inline parameter: vnetResourceGroup_param = $vnetResourceGroup_param"
}
if ($PSBoundParameters.ContainsKey('vnetNameFull_param') -and $vnetNameFull_param) { 
    Write-Host "Using inline parameter: vnetNameFull_param = $vnetNameFull_param"
}

$authSettings = @{
    useServicePrincipal = $useServicePrincipal
    tenantId            = $tenantId
    spObjId             = $spObjId
    spSecret            = $spSecret
    subscriptionId      = $subscriptionId
}

Connect-AzureContext @authSettings
$vnetObj = $null

if ($(Get-AzContext).Subscription -ne "") {
    write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"

    # This PSObject must be sorted by value in ascending order

    $requiredSubnets = $null
    if ($null -eq $projectTypeADO -or $projectTypeADO -eq "" ) 
    {
        write-host "projectTypeADO is null or empty"
        $requiredSubnets = [PsObject]@{
            dbxPubSubnetCidr  = '26' # 23-26
            dbxPrivSubnetCidr = '26' # 23-26
            aksSubnetCidr     = '24' # 26-27 Azure CNI, Kubenet
        }
    }
    else 
    {
        Write-Host "projectTypeADO: '$projectTypeADO'"

        if($projectTypeADO.Trim().ToLower() -eq "esml"){
            write-host "projectTypeADO=esml"
            $requiredSubnets = [PsObject]@{
                dbxPubSubnetCidr  = $dbxPubSubnetCidrAll # 23-26
                dbxPrivSubnetCidr = $dbxPrivSubnetCidrAll # 23-26
                aksSubnetCidr     = $aksSubnetCidrAll # # AKS: 24 since 26 provides error on 1 node cluster. Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
            }
        }
        elseif ($projectTypeADO.Trim().ToLower() -eq "genai-1"){
            write-host "projectTypeADO=genai-1"
            $requiredSubnets = [PsObject]@{
                genaiSubnetCidr  = $genaiSubnetCidrAll
                aksSubnetCidr     = $aksSubnetCidrAll # AKS: 24 since 26 provides error on 1 node cluster. Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
                acaSubnetCidr     = $acaSubnetCidrAll # Workload Profiles Environment: Minimum subnet size is /27. Consumption Only Environment: Minimum subnet size is /23
            }
        }
        elseif ($projectTypeADO.Trim().ToLower() -eq "all"){
            write-host "projectTypeADO=all"
            $requiredSubnets = [PsObject]@{
                genaiSubnetCidr   = $genaiSubnetCidrAll
                aksSubnetCidr     = $aksSubnetCidrAll # 26 is min Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
                aks2SubnetCidr    = $aks2SubnetCidrAll # AKS: 24 since 26 provides error on 1 node cluster. Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
                acaSubnetCidr     = $acaSubnetCidrAll # Workload Profiles Environment: Minimum subnet size is /27. Consumption Only Environment: Minimum subnet size is /23
                aca2SubnetCidr    = $aca2SubnetCidrAll # AI foundry project (v2, est 2025): The recommended size of the delegated Agent subnet is /24 (256 addresses) due to the delegation of the subnet to Microsoft.App/environment. Subnets smaller than /23 are rejected at provisioning time—the control plane can’t allocate enough addresses for the infrastructure scale sets—so the Cognitive Services RP keeps the account in Creating
                dbxPubSubnetCidr  = $dbxPubSubnetCidrAll # 23-26
                dbxPrivSubnetCidr = $dbxPrivSubnetCidrAll # 23-26
            }
        }
        else {
            write-host "projectTypeADO=not supported value: '$($projectTypeADO)'"
            $requiredSubnets = [PsObject]@{
                genaiSubnetCidr   = $genaiSubnetCidrAll
                aksSubnetCidr     = $aksSubnetCidrAll # 26 is min Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
                aks2SubnetCidr    = $aks2SubnetCidrAll # AKS: 24 since 26 provides error on 1 node cluster. Azure CNI, Kubenet. Pre***allocated IPs 29 exceeds IPs available 27 in Subnet Cidr 10.77.41.0/27
                acaSubnetCidr     = $acaSubnetCidrAll # Workload Profiles Environment: Minimum subnet size is /27. Consumption Only Environment: Minimum subnet size is /23
                aca2SubnetCidr    = $aca2SubnetCidrAll # AI foundry project (v2, est 2025): The recommended size of the delegated Agent subnet is /24 (256 addresses) due to the delegation of the subnet to Microsoft.App/environment. Subnets smaller than /23 are rejected at provisioning time—the control plane can’t allocate enough addresses for the infrastructure scale sets—so the Cognitive Services RP keeps the account in Creating
                dbxPubSubnetCidr  = $dbxPubSubnetCidrAll # 23-26
                dbxPrivSubnetCidr = $dbxPrivSubnetCidrAll # 23-26
            }
        }
    }

    # Handle variable assignments - ADO parameters take precedence, then inline parameters, then JSON parameters
    if ($null -ne $commonRGNamePrefixVar -and $commonRGNamePrefixVar -ne '') {
        $commonRGNamePrefix = $commonRGNamePrefixVar
    }
    elseif ($PSBoundParameters.ContainsKey('commonRGNamePrefix') -and $commonRGNamePrefix) {
        # Already set from inline parameter
    }
    
    if ($null -ne $locationSuffixADO -and $locationSuffixADO -ne '') {
        $locationSuffix = $locationSuffixADO
    }
    elseif ($PSBoundParameters.ContainsKey('locationSuffix') -and $locationSuffix) {
        # Already set from inline parameter
    }
    
    if ($null -ne $aifactorySuffixRGADO -and $aifactorySuffixRGADO -ne '') {
        $aifactorySuffix = $aifactorySuffixRGADO
    }
    elseif ($PSBoundParameters.ContainsKey('aifactorySuffixRG') -and $aifactorySuffixRG) {
        $aifactorySuffix = $aifactorySuffixRG
    }
    
    if ($null -ne $commonResourceSuffixADO -and $commonResourceSuffixADO -ne '') {
        $commonResourceSuffix = $commonResourceSuffixADO
    }
    elseif ($PSBoundParameters.ContainsKey('commonResourceSuffix') -and $commonResourceSuffix) {
        # Already set from inline parameter
    }

    $vnetName = if ($null -eq $vnetNameFull_param -or $vnetNameFull_param -eq "" ) 
    {
        "$vnetNameBase-$locationSuffix-$env$commonResourceSuffix" # 'esml-common-sdc-dev-002'
    }
    else {
        $vnetNameFull_param
    }

    $vnetResourceGroup = if ( $null -eq $vnetResourceGroup_param -or $vnetResourceGroup_param -eq "" )
    {
        "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffix-$env$aifactorySuffix" # 'acme-aif-esml-common-swedev-002'
    }
    else {
        $vnetResourceGroup_param
    }

    Write-Host "vnetName: $($vnetName)"
    Write-Host "vnetResourceGroup: $($vnetResourceGroup)"
    $vnetObj = Get-AzVirtualNetwork -ResourceGroupName $vnetResourceGroup -Name $vnetName

    $lastAllocatedNetwork, $lastAllocatedCidr = @($vnetObj.Subnets | Sort-Object { $_.AddressPrefix.split("/")[0] -as [Version]} -Bottom 1)[0].AddressPrefix.split("/") # JOSTRM fixed sort (version and no CIDR, instead of "string sort" and CIDR)
    $startIp  = Find-NextIpAddress $(Get-Subnet $lastAllocatedNetwork -MaskBits $lastAllocatedCidr).BroadcastAddress.IPAddressToString
    
    Write-Host "01 lastAllocatedNetwork: $($lastAllocatedNetwork)"
    Write-Host "02 lastAllocatedCidr: $($lastAllocatedCidr)"
    Write-Host "03 startIp: $($startIp)"

    $possibleValuesForCidrNotations = @{}
    $requiredSubnets.values | Select-Object -Unique | Sort-Object -Property Value | Foreach-Object {
        $possibleValuesForCidrNotations[$_] = Get-SubnetFitting -addressSpace $vnetObj.AddressSpace.AddressPrefixes[0] -cidrNotation $_
    }

    $result = New-SubnetScheme -map $requiredSubnets -startIp $startIp -possibleValuesMap $possibleValuesForCidrNotations
    Write-Host "Result:"
    Write-Host "Resource group for vNet: $($vnetResourceGroup)"
    Write-Host "vNet: $($vnetName)"
    
    $templateEsml = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetCidr": {
            "value": "$($result["aksSubnetCidr"])"
        },
        "dbxPrivSubnetCidr": {
            "value": "$($result["dbxPrivSubnetCidr"])"
        },
        "dbxPubSubnetCidr": {
            "value": "$($result["dbxPubSubnetCidr"])"
        },
        "vnetNameBase": {
            "value": "$vnetNameBase"
        },
        "location": {
            "value": "$location"
        },
        "locationSuffix": {
            "value": "$locationSuffix"
        },
        "vnetResourceGroup": {
            "value": "$vnetResourceGroup"
        },
        "commonResourceSuffix": {
            "value": "$commonResourceSuffix"
        }
    }
}
"@
    
    $templateGenAI = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetCidr": {
            "value": "$($result["aksSubnetCidr"])"
        },
        "acaSubnetCidr": {
            "value": "$($result["acaSubnetCidr"])"
        },
        "genaiSubnetCidr": {
            "value": "$($result["genaiSubnetCidr"])"
        },
        "vnetNameBase": {
            "value": "$vnetNameBase"
        },
        "location": {
            "value": "$location"
        },
        "locationSuffix": {
            "value": "$locationSuffix"
        },
        "vnetResourceGroup": {
            "value": "$vnetResourceGroup"
        },
        "commonResourceSuffix": {
            "value": "$commonResourceSuffix"
        }
    }
}
"@

 $templateAll = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetCidr": {
            "value": "$($result["aksSubnetCidr"])"
        },
        "aks2SubnetCidr": {
            "value": "$($result["aks2SubnetCidr"])"
        },
        "acaSubnetCidr": {
            "value": "$($result["acaSubnetCidr"])"
        },
        "aca2SubnetCidr": {
            "value": "$($result["aca2SubnetCidr"])"
        },
        "genaiSubnetCidr": {
            "value": "$($result["genaiSubnetCidr"])"
        },
         "dbxPrivSubnetCidr": {
            "value": "$($result["dbxPrivSubnetCidr"])"
        },
        "dbxPubSubnetCidr": {
            "value": "$($result["dbxPubSubnetCidr"])"
        },
        "vnetNameBase": {
            "value": "$vnetNameBase"
        },
        "location": {
            "value": "$location"
        },
        "locationSuffix": {
            "value": "$locationSuffix"
        },
        "vnetResourceGroup": {
            "value": "$vnetResourceGroup"
        },
        "commonResourceSuffix": {
            "value": "$commonResourceSuffix"
        }
    }
}
"@

    $template = "not set"

    if($projectTypeADO.Trim().ToLower() -eq "esml"){
        Write-host "Template for subnetParameters.json is projectType:esml"
        $template = $templateEsml
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "dbxPrivSubnetCidr: $($result["dbxPrivSubnetCidr"])"
        write-host "dbxPubSubnetCidr : $($result["dbxPubSubnetCidr"])"
    }
    elseif ($projectTypeADO.Trim().ToLower() -eq "genai-1"){
        Write-host "Template for subnetParameters.json is projectType:genai-1"
        $template = $templateGenAI
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "genaiSubnetCidr : $($result["genaiSubnetCidr"])"
        write-host "acaSubnetCidr : $($result["acaSubnetCidr"])"
    }
    elseif ($projectTypeADO.Trim().ToLower() -eq "all"){
        Write-host "Template for subnetParameters.json is projectType:all"
        $template = $templateAll
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "aks2SubnetCidr   : $($result["aks2SubnetCidr"])"
        write-host "genaiSubnetCidr : $($result["genaiSubnetCidr"])"
        write-host "acaSubnetCidr : $($result["acaSubnetCidr"])"
        write-host "aca2SubnetCidr : $($result["aca2SubnetCidr"])"
        write-host "dbxPrivSubnetCidr: $($result["dbxPrivSubnetCidr"])"
        write-host "dbxPubSubnetCidr : $($result["dbxPubSubnetCidr"])"
    }
    else{
        Write-host "Template for subnetParameters.json is projectType:unsupported value: '$projectTypeADO'"
        $template = $templateEsml
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "dbxPrivSubnetCidr: $($result["dbxPrivSubnetCidr"])"
        write-host "dbxPubSubnetCidr : $($result["dbxPubSubnetCidr"])"
    }

    $templateName = "subnetParameters.json"
    
    # Create directory if it doesn't exist
    if (!(Test-Path $filePath)) {
        Write-Host "Creating directory: $filePath" -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $filePath -Force | Out-Null
    }
    
    $template | Out-File (Join-Path $filePath $templateName)
    $fullPath = (Join-Path $filePath $templateName)
    $resolvedPath = Resolve-Path $fullPath
    Write-host "Template written to $resolvedPath"
    Write-host "Parameter: aifactorySuffixRG is: $aifactorySuffix"
    Write-host "Parameter: commonSuffixRGG is: $commonResourceSuffix"
    Write-host "Parameter: vnetResourceGroup is: $vnetResourceGroup"

}else{
    write-host "Failed to login"
}
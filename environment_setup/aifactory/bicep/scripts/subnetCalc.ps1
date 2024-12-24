# Description:
#   This script is used to generate ARM parameters that contain subnet addressprefix specifications.
#   The generation is based on a caluclation performed on an existing virtual network. If gaps are detected these
#   will be filled. If no gaps are found, the subnets are appended to the end of the vnet subnet list. The required subnets
#   are specified in the $requiredSubnets PSObject.

param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar1,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar2,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar3,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar4,
    [Parameter(Mandatory = $true, HelpMessage = "Where to place the parameters.json file")][string]$filePath,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory environment [dev,test,prod]")][string]$env,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory subscription id for environment [dev,test,prod]")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project Azure resource suffix ")][string]$prjResourceSuffix,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory suffix for COMMON resource groups [dev,test,prod]")][string]$aifactorySuffixRGADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory suffix for COMMON resources [dev,test,prod]")][string]$commonResourceSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory data center region location westeurope, swedencentral ")][string]$locationADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory data center region location suffix weu, swc ")][string]$locationSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project type:[esml,genai-1]")][string]$projectTypeADO,

    # optional parameters
    [Parameter(Mandatory = $false, HelpMessage = "Use service principal")][switch]$useServicePrincipal = $false,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the object id for service principal")][string]$spObjId,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar5
)

filter ConvertTo-BinaryIP {
    # props to: https://www.indented.co.uk/powershell-subnet-math/
    [CmdletBinding()]
    [OutputType([String])]
    param (
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
        [IPAddress]$IPAddress
    )
    
    $binaryOctets = $IPAddress.GetAddressBytes() | ForEach-Object { 
        [Convert]::ToString($_, 2).PadLeft(8, '0')
    }
    $binaryOctets -join '.'
}

filter ConvertTo-DottedDecimalIP {
    # props to: https://www.indented.co.uk/powershell-subnet-math/
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
        [String]$IPAddress
    )
        
    switch -regex ($IPAddress) {
        '^([01]{8}.){3}[01]{8}$' {
            [Byte[]]$bytes = $IPAddress -split '\.' | ForEach-Object {
                [Convert]::ToByte($_, 2)
            }
            [IPAddress]$bytes
        }
        '^\d+$' {
            $IPAddress = [UInt32]$IPAddress
            [Byte[]]$bytes = for ($i = 3; $i -ge 0; $i--) {
                $remainder = [UInt32]$IPAddress % [Math]::Pow(256, $i)
                [UInt32]$IPAddress - $remainder
                $IPAddress = $remainder
            }
            [IPAddress]$bytes
        }
        default { Write-Error "Cannot convert this format" }
    }
}

function Find-NextIpAddress {
    <#
    .SYNOPSIS
    Converts an IP address to binary and adds one bit before covnerting it back to dotted decimals again
    
    .DESCRIPTION
    Use this function to find the next IP in line for the given address. I.e. what comes after a broadcast address? 
    The next available network address
    
    .PARAMETER ipAddress
    The ip address that is used as a the starting point
    
    .EXAMPLE
    Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString --> Find-NextIpAddress "192.168.0.255"
    OUT: 192.168.1.0
    #>
    param (
        $ipAddress
    )
    $splitBytes = $(ConvertTo-BinaryIP $ipAddress).Split('.') 
    [array]::Reverse($splitBytes)
    $incrementationHasOccured = $false

    $bytes = @('')
    foreach ($byte in $splitBytes) {
        $bits = $byte.ToCharArray()
        [array]::Reverse($bits) # make sure to start at the end
        $index = 0
        while ($index -le 7 -and $incrementationHasOccured -eq $false) {
            if ($bits[$index] -eq "1") {
                $bits[$index] = "0"
            }
            else {
                $bits[$index] = "1"
                $incrementationHasOccured = $true
            }
            $index++
        }
        [array]::Reverse($bits)
        $byte = -join ($bits)
        $bytes += $byte
    }

    [array]::reverse($bytes)
    $a = $($bytes -join '.')
    $nextNetworkId = $a.Substring(0, $a.Length - 1)
    return $(ConvertTo-DottedDecimalIP $nextNetworkId)
}

function Get-SubnetFitting {
    <#
    .SYNOPSIS
    Calculates all possible network ranges for a given CIDR notation. 
    Returns an array with all possible values
    
    .DESCRIPTION
    Use this function to find all possible network ranges within an adress space for a given cidr notation
    
    .PARAMETER addressSpace
    An address space to begin with. I.e. 10.100.0.0/16
    
    .EXAMPLE
    Get-SubnetFitting  -addressSpace "10.100.0.0/16" -cidrNotation "/24"
    #>
    param (
        $addressSpace,
        $cidrNotation,
        [Parameter(Mandatory = $false)][string]$endAddress,
        [Parameter(Mandatory = $false)][string]$excludeAddress="None"
    )
    $addressSpaceIp = $addressSpace.split("/")[0]
    $addressSpaceCidr = $addressSpace.split("/")[1]
    $possibleValues = New-Object System.Collections.ArrayList
    $lastBroadcast = $(Get-Subnet $addressSpaceIp -MaskBits $addressSpaceCidr).BroadcastAddress.IPAddressToString
    $currentBroadcast = "0" # will take form of the current iterations broadcast address in while loop
    $startIp = $addressSpaceIp
    while ($currentBroadcast -ne $lastBroadcast) {
        $subnet = get-subnet $startIp -MaskBits $cidrNotation
        $networkAddress = $subnet.NetworkAddress.IPAddressToString

        if ($endAddress){
            if ($networkAddress -eq $endAddress){
                break
            }
        }
        
        if($networkAddress -ne $excludeAddress){
            $possibleValues += $networkAddress
        }
        # prepare for next iteration
        $currentBroadcast = $subnet.BroadcastAddress.IPAddressToString
        $startIp = Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString
    }
    return [System.Collections.ArrayList]$possibleValues 
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
    <#
    .SYNOPSIS
    Find and save all unallocated gaps between already existing subnets within a virtual network
    Returns the following object:
        gaps.allocatableNetworks=[PSCustomObject]@{
            24 = [System.Collections.ArrayList]
            23 = [System.Collections.ArrayList]
            22 = [System.Collections.ArrayList]
            ...
            ...
        }
    
    .PARAMETER subnetCidr
    vnetObj is an object that is returned with the Get-AzVirtualNetwork cmdlet

    .PARAMETER cidrs
    An object with required subnetmask notations
    
    .EXAMPLE
    Find-GapsInVnet -vnetObj $vnetObj -cidrs $requiredSubnets
    #>
    param (
        $vnetObj,
        $cidrs
    )
    $index = 0

    # Declare object to work with
    $gaps = [PSCustomObject]@{
        allocatableNetworks = [PSCustomObject]@{}
    }

    # Populate work object with required CIDR notations as keys and empty arrays as values.
    $cidrsToCalculate = @($cidrs.GetEnumerator() | ForEach-Object{ $_.value }) | Select-Object -Unique
    $cidrsToCalculate | ForEach-Object{
        $gaps.allocatableNetworks | Add-Member -Name $_ -Type NoteProperty -Value $(New-Object System.Collections.ArrayList)
    }

    $vnetAddressSpaceSize = $vnetObj.AddressSpace.AddressPrefixes[0].split("/")[1]
    $existingSubnetCidrNotations = @($vnetObj.Subnets | ForEach-Object{ $_.AddressPrefix } | Sort-Object )

    $nextAddress = $existingSubnetCidrNotations[0] # This is just a ranom value but will be modified during loop
    $existingSubnetAddresses = @($existingSubnetCidrNotations | ForEach-Object{$_.Split("/")[0]}) # split removes cidr notation elements in from existingSubnetCidrNotations
    $existingSubnetCidrNotations | ForEach-Object{
        $address = $_.split("/")[0]
        $cidr = $_.split("/")[1]
        $subnetObj = Get-Subnet $address -MaskBits $cidr
        $nextAddress = Find-NextIpAddress -ipAddress $subnetObj.BroadcastAddress.IPAddressToString
        $cidrsToCalculate | ForEach-Object{
            try{
                $endAddress = $existingSubnetCidrNotations[$index + 1].split("/")[0]
            }catch{ # IndexError
                $endAddress = $existingSubnetCidrNotations[-1]
            }
            
            # Whenever the nextAddress is not already allocated
            # We save all addresses for a specific subnet mask into the working object
            if (-not $existingSubnetAddresses.Contains("$nextAddress")){
                [array]$identifiedSubnetRanges = Get-SubnetFitting `
                -addressSpace $("$nextAddress/$vnetAddressSpaceSize") `
                -cidrNotation $_ `
                -endAddress $endAddress `
                -excludeAddress $address `
                -ErrorAction SilentlyContinue
                foreach($x in $identifiedSubnetRanges){
                    $gaps.allocatableNetworks.$_.Add($x)
                }
                
            }
        }
        $index++
    }
    return $gaps
}

function New-SubnetScheme {
    <#
    .SYNOPSIS
    calculates the bes possible subnet fittings within and address space. By sorting from biggest to smallest networks,
    and adding subnets to the end of the possible ranges.

    Converts:
        $requiredSubnets = @{
            aksSubnetCidr     = '24'
            dbxPubSubnetCidr  = '23'
            dbxPrivSubnetCidr = '23'
        } 
    To:
        $requiredSubnets = @{
            aksSubnetCidr     = '10.100.5.0/24'
            dbxPubSubnetCidr  = '10.100.0.0/23'
            dbxPrivSubnetCidr = '10.100.2.0/23'
        } 
    
    .PARAMETER map
    A hashmap that contains mappings for subnets where key is the name and value is cidr notation. See example.

    .PARAMETER startIp
    IP that the function should start calculation from

    .PARAMETER possibleValuesMap
    A hashmap that contains all possible values per cidr notation
    
    .EXAMPLE
    $requiredSubnets = @{
        aksSubnetCidr     = '24'
        dbxPubSubnetCidr  = '23'
        dbxPrivSubnetCidr = '23'
    } 
    New-SubnetScheme -map $requiredSubnets -startIp 10.100.0.0 -possibleValuesMap @{"24 = "$(Get-SubnetFitting  -addressSpace "10.100.0.0/16" -cidrNotation "/24"), "23" = "$(Get-SubnetFitting  -addressSpace "10.100.0.0/16" -cidrNotation "/23")}
    #>
    param (
        $map,
        $startIp,
        $possibleValuesMap
    )
    $sortedSubnetMap = $map.GetEnumerator() | Sort-Object -Property Value -Descending
    $index = 0
    $allocatedIps = @()
    $result = @{}
    $startIpVnet = $startIp.ToString().Substring(0,5) # 10.50


    while ($index -lt $($sortedSubnetMap.Key).Length) {
        $currentValue = $($sortedSubnetMap.Value)[$index]
        $currentKey = $($sortedSubnetMap.Key)[$index]
        # if the value is a subnet mask notation only (30, 29, 28 etc...) 
        # then it must be calucalted into a full CIDR notation that is valid to use
        # A valid (full)CIDR notation is: 10.100.16.0/24
        if ($currentValue.Length -le 2){ 
            $subnet = Get-Subnet $startIp -MaskBits $currentValue
            $valid = Get-CidrValidity -subnetCidr "$startIp" -possibleValues $possibleValuesMap[$currentValue]
            
            # if startIp is valid and not already in use then we allocate it
            # else we find the next possible startIp and try again
            if ( $valid -and $($allocatedIps -notcontains $startIp) ) {

                $result[$currentKey] = "$startIp/$currentValue"
                $allocatedIps += $startIp
                $startIp = Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString
                $index++
            }
            else {
                $startIp = Find-NextIpAddress $subnet.BroadcastAddress.IPAddressToString
                $currentVnet = $startIp.ToString().Substring(0,5) # 10.50
                
               write-host "Start vNet" $startIpVnet
               write-host "Current vNet" $currentVnet
                if ($startIpVnet -ne $currentVnet){ # vNet full...Now we are moving away, searching anohter vNet    
                    write-host "Error! Full vNet, cannot Find-NextIpAddress. Create new vNet or increase existing vNet - "  $startIpVnet
                    break
                }
            }
        # Or else nothing has to be done, in this case we just increment the index for next iteration
        # No calculation is needed because the value was already in the correct format
        }else{
            $result[$currentKey] = "$currentValue"
            $index++
        }
    }

    return $result
}

Import-Module -Name "./modules/pipelineFunctions.psm1"
Import-Dependencies

# This function will convert the parameters nest of the arm tempate parameters file to global variables
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

$authSettings = @{
    useServicePrincipal = $useServicePrincipal
    tenantId            = $tenantId
    spObjId             = $spObjId
    spSecret            = $spSecret
    subscriptionId      = $subscriptionId
}

Connect-AzureContext @authSettings

if ($(Get-AzContext).Subscription -ne "") {
    write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"

    # This PSObject must be sorted by value in ascending order

    $requiredSubnets = $null
    if ($null -eq $projectTypeADO -or $projectTypeADO -eq "" ) 
    {
        write-host "projectTypeADO is null or empty"
        $requiredSubnets = [PsObject]@{
            dbxPubSubnetCidr  = '23'
            dbxPrivSubnetCidr = '23'
            aksSubnetCidr     = '25'
        }
    }
    else 
    {
        Write-Host "projectTypeADO: '$projectTypeADO'"

        if($projectTypeADO.Trim().ToLower() -eq "esml"){
            write-host "projectTypeADO=esml"
            $requiredSubnets = [PsObject]@{
                dbxPubSubnetCidr  = '23'
                dbxPrivSubnetCidr = '23'
                aksSubnetCidr     = '25'
            }
        }
        elseif ($projectTypeADO.Trim().ToLower() -eq "genai-1"){
            write-host "projectTypeADO=genai-1"
            $requiredSubnets = [PsObject]@{
                genaiSubnetCidr  = '25'
                aksSubnetCidr     = '25'
            }
        }
        else {
            write-host "projectTypeADO=not supported value: '$($projectTypeADO)'"
            $requiredSubnets = [PsObject]@{
                dbxPubSubnetCidr  = '23'
                dbxPrivSubnetCidr = '23'
                aksSubnetCidr     = '25'
            }
        }
    }

    write-host "VARIABLES:"
    write-host "-STATIC (as input to vnetName and vnetResourceGroup): Static from PARAMETERS.json: commonRGNamePrefix,vnetResourceGroupBase"
    write-host "-DYNAMIC (as input to vnetName and vnetResourceGroup): Dynamic parameters as INPUT from ADO parameters: env,locationSuffixADO, commonResourceSuffixADO,aifactorySuffixRGADO"

    #$vnetName = "$vnetNameBase-$locationSuffixADO-$env$commonResourceSuffixADO" # '${vnetNameBase}-$locationSuffix-${env}${commonResourceSuffix}'
    #$vnetResourceGroup =  "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffixADO-$env$aifactorySuffixRGADO" # esml-common-weu-dev-001
    

    $vnetName = if ($null -eq $vnetNameFull_param -or $vnetNameFull_param -eq "" ) 
    {
        "$vnetNameBase-$locationSuffixADO-$env$commonResourceSuffixADO"
    }
    else {
        $vnetNameFull_param
    }

    $vnetResourceGroup = if ( $null -eq $vnetResourceGroup_param -or $vnetResourceGroup_param -eq "" )
    {
        "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffixADO-$env$aifactorySuffixRGADO"
    }
    else {
        $vnetResourceGroup_param
    }

    write-host "Debug 00 vnetName: $($vnetName)"
    write-host "Debug 00 vnetResourceGroup: $($vnetResourceGroup)"

    $vnetObj = Get-AzVirtualNetwork -ResourceGroupName $vnetResourceGroup -Name $vnetName

    $lastAllocatedNetwork, $lastAllocatedCidr = @($vnetObj.Subnets | Sort-Object { $_.AddressPrefix.split("/")[0] -as [Version]} -Bottom 1)[0].AddressPrefix.split("/") # JOSTRM fixed sort (version and no CIDR, instead of "string sort" and CIDR)
    $startIp  = Find-NextIpAddress $(Get-Subnet $lastAllocatedNetwork -MaskBits $lastAllocatedCidr).BroadcastAddress.IPAddressToString
    
    write-host "Debug 01 lastAllocatedNetwork: $($lastAllocatedNetwork)"
    write-host "Debug 02 lastAllocatedCidr: $($lastAllocatedCidr)"
    write-host "Debug 03 startIp: $($startIp)"
    #write-host "DEBUG 4"

    $possibleValuesForCidrNotations = @{}
    $requiredSubnets.values | Select-Object -Unique | Sort-Object -Property Value | Foreach-Object {
        $possibleValuesForCidrNotations[$_] = Get-SubnetFitting -addressSpace $vnetObj.AddressSpace.AddressPrefixes[0] -cidrNotation $_
    }

    write-host "DEBUG 4"

    $result = New-SubnetScheme -map $requiredSubnets -startIp $startIp -possibleValuesMap $possibleValuesForCidrNotations
    write-host "this is the result:"
    write-host "Resource group for vNet: $($vnetResourceGroup)"
    write-host "vNet: $($vnetName)"
    
    # projectName has been declared by ConvertTo-Variables called earlier
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
            "value": "$locationADO"
        },
        "locationSuffix": {
            "value": "$locationSuffixADO"
        },
        "vnetResourceGroup": {
            "value": "$vnetResourceGroup"
        },
        "commonResourceSuffix": {
            "value": "$commonResourceSuffixADO"
        }
    }
}
"@
    
    $templateGenaI = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetCidr": {
            "value": "$($result["aksSubnetCidr"])"
        },
        "genaiSubnetCidr": {
            "value": "$($result["genaiSubnetCidr"])"
        },
        "vnetNameBase": {
            "value": "$vnetNameBase"
        },
        "location": {
            "value": "$locationADO"
        },
        "locationSuffix": {
            "value": "$locationSuffixADO"
        },
        "vnetResourceGroup": {
            "value": "$vnetResourceGroup"
        },
        "commonResourceSuffix": {
            "value": "$commonResourceSuffixADO"
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
        $template = $templateGenaI
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "genaiSubnetCidr : $($result["genaiSubnetCidr"])"
    }
    else{
        Write-host "Template for subnetParameters.json is projectType:unsupported value: '$projectTypeADO'"
        $template = $templateEsml
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "dbxPrivSubnetCidr: $($result["dbxPrivSubnetCidr"])"
        write-host "dbxPubSubnetCidr : $($result["dbxPubSubnetCidr"])"
    }

    $templateName = "subnetParameters.json"
    
    # projectName has been declared by ConvertTo-Variables called earlier

    $template | Out-File "$filePath/$templateName"
    Write-host "Template written to $filePath/$templateName"
    Write-host "Parameter: aifactorySuffixRG is: $aifactorySuffixRGADO"
    Write-host "Parameter: commonSuffixRGG is: $commonResourceSuffixADO"

}else{
    write-host "Failed to login"
}
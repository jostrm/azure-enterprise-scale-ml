# Description:
#   This script is used to generate ARM parameters that contain subnet addressprefix specifications.
#   Allocate aligned free IPv4 gaps, preserving existing subnet identities and ranges.
#   Allocation is deterministic for a given Azure inventory; deployments sharing a VNet must be serialized.

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
    [Parameter(Mandatory = $false, HelpMessage = "Project number used in deployed subnet names, e.g. 001; otherwise read from the JSON parameters")][string]$projectNumber,

    # Optional subnet CIDR overrides (defaults match legacy values for projectTypeADO=all)
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for GenAI subnet when projectType=all")][string]$genaiSubnetCidrAll = '25',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for standalone AKS subnet when projectType=all")][string]$aksSubnetCidrAll = '26',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for Azure ML's AKS subnet when projectType=all")][string]$aks2SubnetCidrAll = '24',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for ACA subnet when projectType=all")][string]$acaSubnetCidrAll = '23',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for secondary ACA subnet when projectType=all")][string]$aca2SubnetCidrAll = '23',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for dedicated App Service/Function VNet integration subnet (Microsoft.Web/serverFarms). Min /28; /27 gives headroom")][string]$webappSubnetCidrAll = '27',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for DBX public subnet when projectType=all")][string]$dbxPubSubnetCidrAll = '26',
    [Parameter(Mandatory = $false, HelpMessage = "CIDR mask for DBX private subnet when projectType=all")][string]$dbxPrivSubnetCidrAll = '26'
)

$ErrorActionPreference = 'Stop'
$useAzureCli = $env:GITHUB_ACTIONS -eq 'true' -or $env:AIFACTORY_USE_AZURE_CLI -eq 'true'

function ConvertTo-IPv4Range {
    param([Parameter(Mandatory = $true)][string]$Cidr)
    if ($Cidr -notmatch '^(\d{1,3}\.){3}\d{1,3}/(0|[1-9]|[12]\d|3[0-2])$') {
        throw "Invalid IPv4 CIDR '$Cidr'; IPv6 allocation is not supported."
    }
    $address, $mask = $Cidr.Split('/')
    [uint64]$start = 0
    foreach ($octet in $address.Split('.')) {
        if ([int]$octet -gt 255 -or ([int]$octet).ToString() -ne $octet) {
            throw "Invalid IPv4 CIDR '$Cidr'."
        }
        $start = $start * 256 + [int]$octet
    }
    [uint64]$size = [math]::Pow(2, 32 - [int]$mask)
    if ($start % $size -ne 0) { throw "IPv4 CIDR '$Cidr' is not network-aligned." }
    # Exclusive ends use UInt64 so 255.255.255.255 never wraps around.
    [pscustomobject]@{ Start = $start; End = $start + $size; Cidr = $Cidr }
}

function ConvertFrom-IPv4Number {
    param([uint64]$Number)
    return (@(($Number -shr 24) -band 255; ($Number -shr 16) -band 255;
        ($Number -shr 8) -band 255; $Number -band 255) -join '.')
}

function New-SubnetScheme {
    param(
        [Parameter(Mandatory = $true)][hashtable]$map,
        [Parameter(Mandatory = $true)]$vnetObj,
        [Parameter(Mandatory = $true)][string]$projectNumber
    )
    if ($projectNumber -notmatch '^\d{1,3}$') {
        throw "A projectNumber of one to three digits is required to preserve deployed subnet identities."
    }
    $suffixes = @{
        aksSubnetCidr = 'aks'; aks2SubnetCidr = 'aks-002'
        acaSubnetCidr = 'aca'; aca2SubnetCidr = 'aca-002'
        genaiSubnetCidr = 'genai'; webappSubnetCidr = 'webapp'
        dbxPubSubnetCidr = 'dbxpub'; dbxPrivSubnetCidr = 'dbxpriv'
    }
    foreach ($entry in $map.GetEnumerator()) {
        if (-not $suffixes.ContainsKey($entry.Key) -or
            [string]$entry.Value -notmatch '^([1-9]|[12]\d|3[0-2])$') {
            throw "Invalid subnet mask or parameter '$($entry.Key)=$($entry.Value)'."
        }
    }
    $spaces = @($vnetObj.AddressSpace.AddressPrefixes | ForEach-Object {
        ConvertTo-IPv4Range $_
    } | Sort-Object Start)
    if ($spaces.Count -eq 0) { throw "VNet has no IPv4 address prefixes." }
    for ($i = 1; $i -lt $spaces.Count; $i++) {
        if ($spaces[$i].Start -lt $spaces[$i - 1].End) {
            throw "VNet address prefixes overlap."
        }
    }
    if ($null -eq $vnetObj.Subnets) { throw "VNet subnet inventory is missing." }
    $occupied = @()
    $byName = @{}
    foreach ($subnet in $vnetObj.Subnets) {
        if ([string]::IsNullOrWhiteSpace($subnet.Name) -or $byName.ContainsKey($subnet.Name)) {
            throw "VNet inventory contains a missing or duplicate subnet name."
        }
        $prefixes = @()
        if ($null -ne $subnet.AddressPrefixes) { $prefixes += @($subnet.AddressPrefixes) }
        if ($null -ne $subnet.AddressPrefix) { $prefixes += @($subnet.AddressPrefix) }
        foreach ($prefix in $prefixes) {
            if ($prefix -isnot [string] -or [string]::IsNullOrWhiteSpace($prefix)) {
                throw "Subnet '$($subnet.Name)' contains an invalid IPv4 CIDR value."
            }
        }
        $prefixes = @($prefixes | Select-Object -Unique)
        if ($prefixes.Count -eq 0) { throw "Subnet '$($subnet.Name)' has no address prefixes." }
        $ranges = @($prefixes | ForEach-Object { ConvertTo-IPv4Range $_ })
        foreach ($range in $ranges) {
            if (-not @($spaces | Where-Object {
                $range.Start -ge $_.Start -and $range.End -le $_.End
            }).Count) { throw "Subnet '$($subnet.Name)' is outside the VNet address prefixes." }
            $occupied += $range
        }
        $byName[$subnet.Name] = $ranges
    }
    $occupied = @($occupied | Sort-Object Start)
    for ($i = 1; $i -lt $occupied.Count; $i++) {
        if ($occupied[$i].Start -lt $occupied[$i - 1].End) {
            throw "Existing subnet address prefixes overlap."
        }
    }

    $result = @{}
    # Preserve even a legacy size that differs from today's defaults; never resize a deployed subnet.
    foreach ($key in $map.Keys) {
        $name = "snt-prj$projectNumber-$($suffixes[$key])"
        if ($byName.ContainsKey($name)) {
            if ($byName[$name].Count -ne 1) {
                throw "Project subnet '$name' has multiple prefixes; the Bicep addressPrefix parameter requires one."
            }
            $result[$key] = $byName[$name][0].Cidr
        }
    }
    # Match the registered API projection: largest first, then logical key (aca before aca2).
    foreach ($entry in ($map.GetEnumerator() | Sort-Object @{Expression = { [int]$_.Value }},
        @{Expression = { $_.Key -replace 'SubnetCidr$', '' }})) {
        if ($result.ContainsKey($entry.Key)) { continue }
        [uint64]$size = [math]::Pow(2, 32 - [int]$entry.Value)
        $chosen = $null
        foreach ($space in $spaces) {
            [uint64]$cursor = $space.Start
            $blocks = @($occupied | Where-Object {
                $_.Start -ge $space.Start -and $_.End -le $space.End
            } | Sort-Object Start)
            # The sentinel also checks the free tail and an entirely empty prefix.
            foreach ($block in @($blocks) + @([pscustomobject]@{ Start = $space.End; End = $space.End })) {
                [uint64]$aligned = [math]::Ceiling($cursor / $size) * $size
                if ($aligned + $size -le $block.Start) {
                    $chosen = [pscustomobject]@{ Start = $aligned; End = $aligned + $size }
                    break
                }
                $cursor = $block.End
            }
            if ($null -ne $chosen) { break }
        }
        if ($null -eq $chosen) {
            throw "No aligned free /$($entry.Value) range for '$($entry.Key)' in VNet; exhausted or fragmented. Existing subnets were not changed."
        }
        $result[$entry.Key] = "$(ConvertFrom-IPv4Number $chosen.Start)/$($entry.Value)"
        $occupied += $chosen
    }
    return $result
}

Import-Module -Name (Join-Path $PSScriptRoot 'modules/pipelineFunctions.psm1')
Import-Dependencies

# This function will convert the parameters nest of the arm tempate parameters file to global variables
if (($bicepPar1 -or $bicepPar2 -or $bicepPar3 -or $bicepPar4 -or $bicepPar5) -and
    -not ($bicepPar1 -and $bicepPar2 -and $bicepPar3 -and $bicepPar4 -and $bicepPar5)) {
    throw "Supply all five JSON parameter files or use inline parameters only."
}
if ($bicepPar1 -and $bicepPar2 -and $bicepPar3 -and $bicepPar4 -and $bicepPar5) {
    Write-Host "Loading parameters from JSON files..."
    $jsonParameters1 = Get-Content -Path $bicepPar1 | ConvertFrom-Json
    $jsonParameters2 = Get-Content -Path $bicepPar2 | ConvertFrom-Json
    $jsonParameters3 = Get-Content -Path $bicepPar3 | ConvertFrom-Json
    $jsonParameters4 = Get-Content -Path $bicepPar4 | ConvertFrom-Json
    $jsonParameters5 = Get-Content -Path $bicepPar5 | ConvertFrom-Json

    # Module-scoped globals are shadowed by script parameters. Load supported
    # parameters locally, in file order, without overriding explicit arguments.
    foreach ($parameters in @($jsonParameters1, $jsonParameters2, $jsonParameters3, $jsonParameters4, $jsonParameters5)) {
        if ($null -eq $parameters.parameters) { throw "JSON input is missing its parameters object." }
        foreach ($parameter in $parameters.parameters.PSObject.Properties) {
            if ($MyInvocation.MyCommand.Parameters.ContainsKey($parameter.Name) -and
                -not $PSBoundParameters.ContainsKey($parameter.Name)) {
                Set-Variable -Scope Script -Name $parameter.Name -Value $parameter.Value.value
            }
        }
    }
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

if ( $useServicePrincipal -eq $null -or $useServicePrincipal -eq "" -or $useServicePrincipal -eq $false )
{
    $useServicePrincipal = $false
    Write-Host $(if ($useAzureCli) { "Using authenticated Azure CLI context" } else { "Using current AzContext (AzurePowerShell task service connection)" })
}
else
{
    $authSettings = @{
        useServicePrincipal = $useServicePrincipal
        tenantId            = $tenantId
        spObjId             = $spObjId
        spSecret            = $spSecret
        subscriptionId      = $subscriptionId
    }

    Connect-AzureContext @authSettings
}
$vnetObj = $null

$hasAzureContext = $useAzureCli
if (-not $hasAzureContext) {
    $context = Get-AzContext
    $hasAzureContext = $null -ne $context.Subscription -and $context.Subscription.Id -eq $subscriptionId
}
if ($hasAzureContext) {
    if ($useAzureCli) {
        Write-Host "Using Azure CLI subscription '$subscriptionId'."
    }
    else {
        write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"
    }

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
                webappSubnetCidr  = $webappSubnetCidrAll # Dedicated App Service/Function VNet integration subnet (Microsoft.Web/serverFarms delegation). Min /28; /27 = 32 addresses
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
                webappSubnetCidr  = $webappSubnetCidrAll # Dedicated App Service/Function VNet integration subnet (Microsoft.Web/serverFarms delegation). Min /28; /27 = 32 addresses
                dbxPubSubnetCidr  = $dbxPubSubnetCidrAll # 23-26
                dbxPrivSubnetCidr = $dbxPrivSubnetCidrAll # 23-26
            }
        }
        else {
            throw "Unsupported projectTypeADO '$projectTypeADO'. Expected esml, genai-1 or all."
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
    if ($locationADO) { $location = $locationADO }

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
    if ($useAzureCli) {
        $vnetJson = & az network vnet show `
            --subscription $subscriptionId `
            --resource-group $vnetResourceGroup `
            --name $vnetName `
            --only-show-errors `
            --output json 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read VNet '$vnetResourceGroup/$vnetName': $($vnetJson -join [Environment]::NewLine)"
        }
        $vnetObj = ($vnetJson -join [Environment]::NewLine) | ConvertFrom-Json
    }
    else {
        $vnetObj = Get-AzVirtualNetwork -ResourceGroupName $vnetResourceGroup -Name $vnetName
    }

    $result = New-SubnetScheme -map $requiredSubnets -vnetObj $vnetObj -projectNumber $projectNumber
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
        "webappSubnetCidr": {
            "value": "$($result["webappSubnetCidr"])"
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
        "webappSubnetCidr": {
            "value": "$($result["webappSubnetCidr"])"
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
        write-host "webappSubnetCidr : $($result["webappSubnetCidr"])"
    }
    elseif ($projectTypeADO.Trim().ToLower() -eq "all"){
        Write-host "Template for subnetParameters.json is projectType:all"
        $template = $templateAll
        write-host "aksSubnetCidr    : $($result["aksSubnetCidr"])"
        write-host "aks2SubnetCidr   : $($result["aks2SubnetCidr"])"
        write-host "genaiSubnetCidr : $($result["genaiSubnetCidr"])"
        write-host "acaSubnetCidr : $($result["acaSubnetCidr"])"
        write-host "aca2SubnetCidr : $($result["aca2SubnetCidr"])"
        write-host "webappSubnetCidr : $($result["webappSubnetCidr"])"
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
    throw "No authenticated Azure context for subscription '$subscriptionId'."
}
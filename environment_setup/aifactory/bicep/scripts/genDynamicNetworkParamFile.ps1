
param (
    # required
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar1,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar2,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar3,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar4,
    [Parameter(Mandatory = $true, HelpMessage="Where to place the parameters.json file")][string]$filePath,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory environment [dev,test,prod]")][string]$env,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory subscription id for environment [dev,test,prod]")][string]$subscriptionId,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory COMMON RG, suffix ")][string]$aifactorySuffixRGADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory location suffix ")][string]$locationSuffixADO,
    [Parameter(Mandatory = $true, HelpMessage = "ESML projectNumber -makes a deployment unique per proj and env")][string]$projectNumber,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory project type:[esml,genai-1]")][string]$projectTypeADO,
    
    # optional
    [Parameter(Mandatory = $false, HelpMessage = "ESML AI Factory COMMON RG, suffix ")][string]$commonRGNamePrefixVar,
    [Parameter(Mandatory = $false, HelpMessage="Use service principal")][switch]$useServicePrincipal=$false,
    [Parameter(Mandatory = $false, HelpMessage="Specifies the object id for service principal")][string]$spObjId,
    [Parameter(Mandatory = $false, HelpMessage="Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar5,
    [Parameter(Mandatory = $false, HelpMessage = "Bring your own subnets, true or false string")][string]$BYO_subnets,
    [Parameter(Mandatory = $false, HelpMessage = "Bring your own subnets. <network_env> dev-, test-, prod- or other env name")][string]$network_env
)

function Set-DeployedOnTag {
    [CmdletBinding()]
    param (
        [Parameter(ValueFromPipeline)]
        $InputObject
    )
    process {
        $deployedOn = get-date -format "yyyy/MM/dd HH:mm"
        try {
            $obj = [PSCustomObject]@{
                value = @{Deployed=$deployedOn}
            }
            Add-Member -InputObject $InputObject.parameters -NotePropertyName "tags" -NotePropertyValue $obj -ErrorAction "Stop"
        }
        catch {
            Add-Member -InputObject $InputObject.parameters.tags.value -NotePropertyName "deployedOn" -NotePropertyValue $deployedOn 
        }
        $InputObject
    }
}

function Get-AzureSubnetId {
    param (
        [string]$subscriptionId,
        [string]$resourceGroupName,
        [string]$vnetName,
        [string]$subnetName,
        [string]$projectNumber = "",
        [string]$networkEnv = ""
    )
    
    # Replace placeholders if network environment is specified
    if ($networkEnv -ne "") {
        $vnetName = $vnetName -replace '<network_env>', $networkEnv
        $subnetName = $subnetName -replace '<network_env>', $networkEnv
    }
    if ($projectNumber -ne "") {
        $subnetName = $subnetName -replace '<xxx>', $projectNumber
    }
    
    return "/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Network/virtualNetworks/$vnetName/subnets/$subnetName"
}

Import-Module -Name "./modules/pipelineFunctions.psm1"
Import-Dependencies

$jsonParameters1 = Get-Content -Path $bicepPar1 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters1

$jsonParameters2 = Get-Content -Path $bicepPar2 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters2

$jsonParameters3 = Get-Content -Path $bicepPar3 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters3

$jsonParameters4 = Get-Content -Path $bicepPar4 | ConvertFrom-Json
Set-DeployedOnTag -InputObject $jsonParameters4
ConvertTo-Variables -InputObject $jsonParameters4

$jsonParameters5 = Get-Content -Path $bicepPar5 | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters5

## $tenantId comes from Parameters.json  - the rest is INPUT, as ADO parameters (see top of file)

if ( $useServicePrincipal -eq $null -or $useServicePrincipal -eq "" -or $useServicePrincipal -eq $false )
{
    $useServicePrincipal = $false
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

if ($null -ne $commonRGNamePrefixVar -and $commonRGNamePrefixVar -ne '') {
    $commonRGNamePrefix = $commonRGNamePrefixVar
}
if ($null -ne $locationSuffixADO -and $locationSuffixADO -ne '') {
    $locationSuffix = $locationSuffixADO
}
if ($null -ne $aifactorySuffixRGADO -and $aifactorySuffixRGADO -ne '') {
    $aifactorySuffix = $aifactorySuffixRGADO
}

$templateName = "dynamicNetworkParams.json"
$deploymentPrefix = "esml-p$projectNumber-$env-$locationSuffix$aifactorySuffix" # esml-p001-dev-sdc-002

write-host "PARAMETERS: Static and Dynamic used::"
write-host "-STATIC (vnetResourceGroup): Static parameters: [commonRGNamePrefix,vnetResourceGroupBase, locationSuffix] (from PARAMETERS.json)"
write-host "-DYNAMIC (vnetResourceGroup): Dynamic parameters as INPUT (from ADO parameters UI): [env,locationSuffixADO,aifactorySuffixRGADO] this Powershell generates(dynamicNetworkParams.json)"

#$vnetResourceGroup =  "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffixADO-$env$aifactorySuffixRGADO" # msft[esml-common]-swc-dev-001

$vnetResourceGroup = if ( $null -eq $vnetResourceGroup_param -or "" -eq $vnetResourceGroup_param )
{
    "$commonRGNamePrefix$vnetResourceGroupBase-$locationSuffix-$env$aifactorySuffix"
}
else {
    if ( $null -eq $network_env -or "" -eq $network_env )
    {
        $vnetResourceGroup_param
    }
    else { 
        $vnetResourceGroup_param -replace '<network_env>', $network_env # Replace <network_env> placeholder with actual network_env value
    }
    
}

write-host "RESULT (vnetResourceGroup): $($vnetResourceGroup)"
write-host "Deployment to lookup (earlier subnets): $($deploymentPrefix)SubnetDeplProj" # Deployment to lookup (earlier subnets): esml-p001-dev-swc-001SubnetDeplProj

# First, normalize the BYO_subnets parameter since it's a string
$BYO_subnets_bool = if ($null -eq $BYO_subnets -or "" -eq $BYO_subnets -or $BYO_subnets -eq "false") {
    $false
} else {
    $true
}

$aksSubnetId=""
$dbxPubSubnetName=""
$dbxPrivSubnetName=""
$genaiSubnetId=""

# Check if BYO_subnets is false
if ($BYO_subnets_bool -eq $false) {

    Write-host "The following parameters are added to template"

    $aksSubnetId=(Get-AzResourceGroupDeployment `
    -ResourceGroupName "$vnetResourceGroup" `
    -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.aksSubnetId.Value

    if($projectTypeADO.Trim().ToLower() -eq "esml"){
        $dbxPubSubnetName=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.dbxPubSubnetName.value

        $dbxPrivSubnetName=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.dbxPrivSubnetName.value
        
        Write-host "dbxPubSubnetName: $dbxPubSubnetName"
        Write-host "dbxPrivSubnetName: $dbxPrivSubnetName"
        Write-host "aksSubnetId: $aksSubnetId"
    }

    if($projectTypeADO.Trim().ToLower() -eq "genai-1"){
        $genaiSubnetId=(Get-AzResourceGroupDeployment `
        -ResourceGroupName "$vnetResourceGroup" `
        -Name "$($deploymentPrefix)SubnetDeplProj").Outputs.genaiSubnetId.Value
        Write-host "genaiSubnetId: $genaiSubnetId"
        Write-host "aksSubnetId: $aksSubnetId"
    }
}else {
    <# Action when all if and elseif conditions are false #>
    # Replace placeholders in vnet and subnet names
    $vnetName = $vnetNameFull_param -replace '<network_env>', $network_env

    if ($null -ne $subnetCommon -and $subnetCommon -ne "") {
        # Common subnets
        $subnetCommonId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommon -networkEnv $network_env
        $subnetCommonScoringId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommonScoring -networkEnv $network_env
        $subnetCommonPowerbiGwId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetCommonPowerbiGw -networkEnv $network_env

        Write-host "COMMON subnets: Just FYI - since these are specified directly in BICEP"
        Write-host "subnetCommonId: $subnetCommonId"
        Write-host "subnetCommonScoringId: $subnetCommonScoringId"
        Write-host "subnetCommonPowerbiGwId: $subnetCommonPowerbiGwId"
    }

    if($projectTypeADO.Trim().ToLower() -eq "esml"){

        if ($null -ne $subnetProjAKS -and $subnetProjAKS -ne "") {
            # ESML project subnets
            $aksSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjAKS -projectNumber $projectNumber -networkEnv $network_env

            $dbxPubSubnetName = $subnetProjDatabricksPublic -replace '<network_env>', $network_env
            $dbxPrivSubnetName = $subnetProjDatabricksPrivate -replace '<xxx>', $projectNumber

            # These can be full IDs if needed
            $dbxPubSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjDatabricksPublic -projectNumber $projectNumber -networkEnv $network_env
            $dbxPrivSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjDatabricksPrivate -projectNumber $projectNumber -networkEnv $network_env

            Write-host "Databricks: Only the name is needed. Just FYI:"
            Write-host "dbxPubSubnetId: $dbxPubSubnetId"
            Write-host "dbxPrivSubnetId: $dbxPrivSubnetId"

            Write-host "AKS full resoiurce ID, and Databrick subnet names:"
            Write-host "aksSubnetId: $aksSubnetId"
            Write-host "dbxPubSubnet Name: $dbxPubSubnetName"
            Write-host "dbxPrivSubnet Name: $dbxPrivSubnetName"
        }
        else {
            Write-host "AIF-WARNING:BYOSubnets:subnetProjAKS is not set. This is needed for AKS deployment. Please check your parameters.json file."
       }

    }

    if($projectTypeADO.Trim().ToLower() -eq "genai-1"){

        if ($null -ne $subnetProjGenAI -and $subnetProjGenAI -ne "") {
            $genaiSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjGenAI -projectNumber $projectNumber -networkEnv $network_env
            Write-host "genaiSubnetId: $genaiSubnetId"

            try {
                $aksSubnetId = Get-AzureSubnetId -subscriptionId $subscriptionId -resourceGroupName $vnetResourceGroup -vnetName $vnetName -subnetName $subnetProjAKS -projectNumber $projectNumber -networkEnv $network_env
                Write-host "aksSubnetId: $aksSubnetId"    
            }
            catch {
                Write-host "AIF-WARNING: aksSubnetId could not be generated. Please check your parameters.json file."    
            }
        }
    }
    else {
        Write-host "AIF-WARNING:BYOSubnets:subnetProjGenAI: subnetProjGenAI is not set. This is needed for GenAI deployment. Please check your parameters.json file."
   }
}

$templateEsml = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "dbxPubSubnetName": {
            "value": "$dbxPubSubnetName"
        },
        "dbxPrivSubnetName": {
            "value": "$dbxPrivSubnetName"
        },
        "aksSubnetId": {
            "value": "$aksSubnetId"
        }
    }
}
"@

$templateGenaI = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "aksSubnetId": {
            "value": "$aksSubnetId"
        },
        "genaiSubnetId": {
            "value": "$genaiSubnetId"
        }
    }
}
"@

$template = "not set"

if($projectTypeADO.Trim().ToLower() -eq "esml"){
    Write-host "Template for dynamicNetworkParams.json is projectType:esml"
    $template = $templateEsml
}
elseif ($projectTypeADO.Trim().ToLower() -eq "genai-1"){
    Write-host "Template for dynamicNetworkParams.json is projectType:genai-1"
    $template = $templateGenaI
}
else{
    Write-host "Template for dynamicNetworkParams.json is projectType:unsupported value: '$projectTypeADO'"
    $template = $templateEsml
}
$template | Out-File "$filePath/$templateName"
Write-Verbose "Template written to $filePath/$templateName"
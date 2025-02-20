
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
    [Parameter(Mandatory = $false, HelpMessage = "Specifies where the find the parameters file")][string]$bicepPar5
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
    $vnetResourceGroup_param
}

write-host "RESULT (vnetResourceGroup): $($vnetResourceGroup)"
write-host "Deployment to lookup (earlier subnets): $($deploymentPrefix)SubnetDeplProj" # Deployment to lookup (earlier subnets): esml-p001-dev-swc-001SubnetDeplProj

# project001dev

# Get-AzResourceGroupDeployment : Resource group 'msftesml-common-swcdev-001' could not be found.
# Deployment 'esml-p001-dev-swc-001SubnetDeplProj' could not be found.

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
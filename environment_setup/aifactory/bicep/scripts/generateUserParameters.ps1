
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies where the find the arm parameters file")][string]$armParameters,
    [Parameter(Mandatory=$true, HelpMessage="Where to place the parameters.json file")][string]$filePath,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AI Factory subscription id for environment [dev,test,prod]")][string]$subscriptionId,
    # optional parameters
    [Parameter(Mandatory=$false, HelpMessage="Use service principal")][switch]$useServicePrincipal=$false,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the object id for service principal")][string]$spObjId,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the secret for service principal")][string]$spSecret
)

Import-Module -Name "./modules/pipelineFunctions.psm1"
Import-Dependencies

$jsonParameters = Get-Content -Path $armParameters | ConvertFrom-Json
ConvertTo-Variables -InputObject $jsonParameters

$authSettings = @{
    useServicePrincipal = $useServicePrincipal
    tenantId            = $tenantId
    spObjId             = $spObjId
    spSecret            = $spSecret
    subscriptionId      = $subscriptionId
}

Connect-AzureContext @authSettings

$ownerId = (Get-AzADUser -Mail $tags.Owner).id
$technicalContactId = (Get-AzADUser -Mail $tags.TechnicalContact).id
$templateName = "esml-prj-rbac-parameters-23.json"
$template = @"
{
    "`$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "projectOwnerId": {
            "value": "$ownerId"
        },
        "projectOwnerEmail": {
            "value": "$($tags.Owner)"
        },
        "technicalContactId": {
            "value": "$technicalContactId"
        },
        "technicalContactEmail": {
            "value": "$($tags.TechnicalContact)"
        },
        "projectServicePrincipleName": {
            "value": ""
        },
        "projectServicePrincipleOID": {
            "value": ""
        },
        "projectServicePrincipleAppId": {
            "value": ""
        },
        "databricksOID": {
            "value": ""
        }
    }
}
"@

$template | Out-File "$filePath/$templateName"
Write-Verbose "Template written to $filePath/$templateName"
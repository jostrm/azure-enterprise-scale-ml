# USAGE: .\aifactory\esml-util\25-add-user-to-bastion.ps1 -tenantID 'your_tenant_id' -subscriptionID 'your_subscription_id' 
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the info")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the tenant")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the subscription")][string]$subscriptionID
)

if (-not [String]::IsNullOrEmpty($spSecret)) {
  Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"

  $SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
  $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
  Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID

  $context = Get-AzSubscription -SubscriptionId $subscriptionID
  Set-AzContext $context
} else {
  # The $spID parameter is null or empty
  Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
}

## EDIT per DSVM you want to deploy
$deplName = '25-add-user-to-bastion'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'
$technicalAdminsObjectID = '' # Comma separated ObjectIDs of users. 
$projectSP_OIDs = 'null'# Comma separated ObjectIDs of project service principals, usually only 1, `esml-project004-sp-oid`

$tags = @{
    "Application Name" = "Enterprise Scale ML (ESML)"
    "BA ID" = "NA"
    "BCIO"= "Robin"
    "Business Area"= "NA"
    "Cost Center"="123456"
    "Resource Managed By"="The Riddler"
    "TechnicalContact"="batman@gothamcity.dc"
    "Project"="Batcave upgrade"
    "Description"="ESML AI Factory"
   }

$location = 'westeurope'
$locationSuffix = 'weu'
$projectNumber = '001'
$env = 'dev'
$prjResourceSuffix = '-001'
$cmndev_keyvault_name = 'kv-cmndev-pgvr2-001'

$rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
Write-Host "RG" $rg
$vnetNameBase = 'vnt-esmlcmn'

####### AKS specic end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\25-add-user-to-bastion.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-projectNumber $projectNumber `
-env $env `
-commonRGNamePrefix $commonRGNamePrefix `
-locationSuffix $locationSuffix `
-aifactorySuffixRG $aifactorySuffixRG `
-commonResourceSuffix $commonResourceSuffix `
-vnetNameBase $vnetNameBase `
-technicalAdminsObjectID $technicalAdminsObjectID `
-cmndevKeyvault $cmndev_keyvault_name `
-projectSP_OID_list $projectSP_OIDs `
-Verbose

Write-Host "BICEP success!"

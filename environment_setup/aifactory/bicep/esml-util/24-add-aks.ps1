# USAGE: .\aifactory\esml-util\24-add-aks.ps1 -tenantID 'your_tenant_id' -subscriptionID 'your_subscription_id'
param (
    # required parameters
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the sp")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the tenant")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the subscription id")][string]$subscriptionID
)

if (-not [String]::IsNullOrEmpty($spSecret)) {
  Write-Host "The spSecret parameter is not null or empty. trying to authenticate to Azure with Service principal"

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
$deplName = '24-add-aks'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'

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

# Cross-region AKS (can be in another Subscription, in another vNet adn region - than Azure ML workspace)
$locationAks = 'westeurope'
$locationSuffixAks = 'weu'
$subscriptionIdAks = 'TODO AKS subscription ID-000000000000'

$projectNumber = '001'
$env = 'dev'
$prjResourceSuffix = '-001'

############# AKS VARS
$aks_dev_defaults = ( 
  'Standard_B4ms', # 4 cores, 16GB, 32GB storage: Burstable (2022-11 this was the default in Azure portal)
  'Standard_A4m_v2', # 4cores, 32GB, 40GB storage (quota:100)
  'Standard_D3_v2' # 4 cores, 14GB RAM, 200GB storage
)

$aks_testProd_defaults = (
  'Standard_DS13-2_v2', # 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' # 8 cores, 64GB RAM, 80GB storage (quota:100)
)

$projectRg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
$rg = "${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}"
Write-Host "RG" $rg

$vnetNameBase = 'vnt-esmlcmn'

####### AKS Specific
$aksSuffix = '' # 1 char only

$ownSSL = 'disabled'
$aksCert = ''
$aksCname = ''
$aksCertKey = ''
$aksSSLstatus = ''

####### AKS specic end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

New-AzResourceGroupDeployment -TemplateFile "aifactory\esml-util\24-add-aks.bicep" `
-Name $deplName `
-ResourceGroupName $rg `
-projectNumber $projectNumber `
-env $env `
-commonRGNamePrefix $commonRGNamePrefix `
-location $location `
-locationSuffix $locationSuffix `
-locationAks $locationAks `
-locationSuffixAks $locationSuffixAks `
-subscriptionIdAks $subscriptionIdAks `
-aifactorySuffixRG $aifactorySuffixRG `
-tags $tags `
-prjResourceSuffix $prjResourceSuffix `
-commonResourceSuffix $commonResourceSuffix `
-vnetNameBase $vnetNameBase `
-ownSSL $ownSSL `
-aksCert $aksCert `
-aksCname $aksCname `
-aksCertKey $aksCertKey `
-aksSSLstatus $aksSSLstatus `
-aksSuffix $aksSuffix `
-aksVmSku_dev $aks_dev_defaults[0] `
-aksVmSku_testProd $aks_testProd_defaults[0] `
-Verbose

Write-Host "BICEP success!"
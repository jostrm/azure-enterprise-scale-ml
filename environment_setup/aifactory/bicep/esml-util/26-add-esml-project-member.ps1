# BICEP 1: CONTRIBUTOR to PROJECT RG(aml, dsvm, kv, adf)
# BICEP 1: CONTRIBUTOR to DASHBOARD RG
# BICEP 1: READER on Bastion (in COMMON RG)
# BICEP 1: READER on Keyvault (in PROJECT RG)
# BICEP 1: CONTRIBUTOR on Bastion NSG
# BICEP 1: networkContributorRoleDefinition on vNET
# Separate powershell: ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1
# Separete powershell: AccessPolicy on Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1


# USAGE: .\aifactory\esml-util\25-add-user-to-bastion.ps1 -spSecret 'your_secret' -spID 'your_id' -tenantID 'your_tenant_id' -subscriptionID 'your_subscription_id' 
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$subscriptionID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem,
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$projectXXX,
    [Parameter(Mandatory = $false, HelpMessage = "Array of user Object Ids")][string[]]$userObjectIds,
    [Parameter(Mandatory = $false, HelpMessage = "Project service principle OID esml-project001-sp-oid")][string]$projectSPObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Common service principle OID common")][string]$commonSPObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Common AD group OID common. Set to TODO to ignore")][string]$commonADgroupObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Project AD group OID common. Set to TODO to ignore")][string]$projectADGroupObjectId,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the object id for service principal, to assign GET, LIST Access policy")][string]$targetObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory keyvault name")][string]$keyvaultName
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
$deplName = '26-add-esml-project-member'
$commonRGNamePrefix = 'abc-def-'
$commonResourceSuffix = '-001'
$aifactorySuffixRG = '-001'
$technicalAdminsObjectID = '' # Comma separated ObjectIDs of users. 
$projectSP_OIDs = ''# Comma separated ObjectIDs of project service principals, usually only 1, `esml-project004-sp-oid`

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
$project_keyvault_name = 'kv-prj001-pgvr2-001'

$rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
Write-Host "RG" $rg
$vnetNameBase = 'vnt-esmlcmn'
$vnetNameFull = "${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}"
$bastion_service_name = "bastion-${locationSuffix}-${env}${aifactorySuffixRG}"
$dashboard_resourcegroup_name = 'dashboards'

####### AKS specic end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

# 1) Kickoff BICEP 1
New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/26-add-esml-project-member.bicep" `
-Name $deplName `
-project_resourcegroup_name $rg `
-dashboard_resourcegroup_name $dashboard_resourcegroup_name `
-project_service_principle $projectSPObjectID `
-vNetName $vnetNameFull `
-user_object_ids $userObjectIds `
-common_kv_name $cmndev_keyvault_name `
-bastion_service_name $bastion_service_name
-Verbose

Write-Host "BICEP success! Now running powershell scripts for ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1 and AccessPolicy on Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1"

#[Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
#[Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem,
#[Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$projectXXX,
#[Parameter(Mandatory = $false, HelpMessage = "Array of user Object Ids")][string[]]$userObjectIds,
#[Parameter(Mandatory = $false, HelpMessage = "Project service principle OID esml-project001-sp-oid")][string]$projectSPObjectID,
#[Parameter(Mandatory = $false, HelpMessage = "Common service principle OID common")][string]$commonSPObjectID,
#[Parameter(Mandatory = $false, HelpMessage = "Common AD group OID common. Set to TODO to ignore")][string]$commonADgroupObjectID,
#[Parameter(Mandatory = $false, HelpMessage = "Project AD group OID common. Set to TODO to ignore")][string]$projectADGroupObjectId,
#[Parameter(Mandatory=$false, HelpMessage="Specifies the object id for service principal, to assign GET, LIST Access policy")][string]$targetObjectID,

& ".\25-add-users-to-datalake-acl-rbac.ps1" -spSecret @spSecret -spID @spID -tenantID @tenantID -storageAccount @storageAccount -adlsgen2filesystem @adlsgen2filesystem -projectXXX @projectXXX -userObjectIds @userObjectIds -projectSPObjectID @projectSPObjectID -commonSPObjectID @commonSPObjectID -commonADgroupObjectID @commonADgroupObjectID -projectADGroupObjectId @projectADGroupObjectId


#[Parameter(Mandatory=$true, HelpMessage="Specifies the object id for service principal, to assign GET, LIST Access policy")][string]$targetObjectID,
#[Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory keyvault name")][string]$keyvaultName,
#[Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory subscription id")][string]$subscriptionID

$ ".\25-add-users-to-kv-get-list-access-policy.ps1" -spSecret @spSecret -spID @spID -tenantID @tenantID -subscriptionID @subscriptionID -targetObjectID $targetObjectID -keyvaultName $keyvaultName
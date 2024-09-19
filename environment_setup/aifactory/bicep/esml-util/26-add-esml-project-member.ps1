# USAGE: 
# cd aifactory\esml-util
# .\26-add-esml-project-member.ps1 -spSecret 'abc' -spID '96483bab-9e36-46f0-8bb7-6633c49e87a1' -tenantID '720b637a-655a-40cf-816a-f22f40755c2c' -subscriptionID '7ec8e6b8-bef0-4811-91a9-6bf389d80de2' -storageAccount 'ingkagaipgvr2esml001dev' -adlsgen2filesystem 'lake3' -userObjectIds 'x,y,z' -projectSPObjectID 'dba0c027-1f5a-4580-a22c-671e32462d9a' -commonSPObjectID '86d6895c-19a7-4b03-a753-ebf645e1a91d' -commonADgroupObjectID 'NULL' -projectADGroupObjectId 'NULL' -projectKeyvaultName 'kv-p002-uks-dev-pgvr201' -commonRGNamePrefix 'ingka-genai-' -commonResourceSuffix '-001' -aifactorySuffixRG '-001' -locationSuffix 'uks' -projectNumber '002' -env 'dev'

param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$subscriptionID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem,
    [Parameter(Mandatory = $false, HelpMessage = "Array of user Object Ids")][string]$userObjectIds,
    [Parameter(Mandatory = $false, HelpMessage = "Project service principle OID esml-project001-sp-oid")][string]$projectSPObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Common service principle OID common")][string]$commonSPObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Common AD group OID common. Set to TODO to ignore")][string]$commonADgroupObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "Project AD group OID common. Set to TODO to ignore")][string]$projectADGroupObjectId,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the object id for user or service principal, to assign GET, LIST Access policy")][string]$keyvaultGetListObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "keyvault name: [kv-prj001-abvr4-001]")][string]$projectKeyvaultName,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory suffix. What suffix on common resources: abc-def-")][string]$commonRGNamePrefix,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory suffix. What suffix on common resource group: -001")][string]$commonResourceSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory suffix. What suffix on common resource group: -001")][string]$aifactorySuffixRG,
    [Parameter(Mandatory = $false, HelpMessage = "Region location prefix in ESML settings: [weu,uks,swe,sdc]")][string]$locationSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "Region location in ESML settings: [westeurope, swedencentral, uksouth]")][string]$location,
    [Parameter(Mandatory = $false, HelpMessage = "ESML Projectnumber, three digits: 001")][string]$projectNumber,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory environment: [dev,test,prod]")][string]$env,
    [Parameter(Mandatory = $false, HelpMessage = "BYOvNet Resource Group - BYOVnet")][string]$BYOvNetResourceGroup,
    [Parameter(Mandatory = $false, HelpMessage = "BYOvNet vNet Name")][string]$BYOvNetName
)

if (-not [String]::IsNullOrEmpty($spSecret)) {
  Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"
  #Write-Host "The spID: ${spID}"
  #Write-Host "The tenantID: ${tenantID}"
    
  $SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
  $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
  Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID
  $context = Get-AzSubscription -SubscriptionId $subscriptionID
  Set-AzContext $context
  Write-Host "Now connected & logged in with SP successfully!"

  if ($(Get-AzContext).Subscription -ne "") {
    write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"
  }
  else {
    Write-Host "Failed to login to Azure with Service Principal. Exiting..."
  }

  
}else {
  Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
}

# EDIT per your convention if it differs from ESML AIFactory defaults
$deplName = '26-add-esml-project-member'
$projectXXX = "project"+$projectNumber
$common_rg = "${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}" # dc-heroes-esml-common-weu-dev-001
$project_rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
Write-Host "Common RG" $common_rg
Write-Host "Project RG" $project_rg

$vnetNameBase = 'vnt-esmlcmn'
$vnetNameFull = "${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}"
$bastion_service_name = "bastion-${locationSuffix}-${env}${aifactorySuffixRG}"
$dashboard_resourcegroup_name = 'dashboards'

# EDIT end
Write-Host "Kicking off the BICEP..."
#Set-AzDefault -ResourceGroupName $rg

Write-Host "common_rg : ${common_rg}"
Write-Host "project_rg : ${project_rg}"
Write-Host "dashboard_rg : ${dashboard_resourcegroup_name}"
Write-Host "projectSP_id : ${projectSPObjectID}"
Write-Host "vnetName : ${vnetNameFull}"
Write-Host "userIds : ${userObjectIds}"
Write-Host "kv : ${projectKeyvaultName}"
Write-Host "bastion : ${bastion_service_name}"

if (-not [String]::IsNullOrEmpty($BYOvNetName)) {
  Write-Host "Running BYOVnet logic..."
  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsProjectMemberByoVnet.bicep" `
  -Name $deplName `
  -ResourceGroupName $BYOvNetResourceGroup `
  -vnet_resourcegroup_name $BYOvNetResourceGroup `
  -project_service_principle_oid $projectSPObjectID `
  -vnet_name $BYOvNetName `
  -user_object_ids $userObjectIds `
  -Verbose

  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsProjectMember.bicep" `
  -Name $deplName `
  -ResourceGroupName $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -user_object_ids $userObjectIds `
  -bastion_service_name $bastion_service_name `
  -storage_account_name_datalake $storageAccount `
  -Verbose
}
else{
  Write-Host "Running standard logic (not BYOVnet logic)..."
  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsProjectMember.bicep" `
  -Name $deplName `
  -ResourceGroupName $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -project_service_principle_oid $projectSPObjectID `
  -vnet_name $vnetNameFull `
  -user_object_ids $userObjectIds `
  -bastion_service_name $bastion_service_name `
  -storage_account_name_datalake $storageAccount `
  -Verbose

}

$inUserObjectIdsArray = $userObjectIds -split ','

$emptyArray = @()
$userObjectIdsArray = ($inUserObjectIdsArray + $emptyArray) | Sort-Object -Unique

Write-Host "BICEP success! Now running powershell scripts for ACL on Datalake: 25-add-users-to-datalake-acl-rbac.ps1 and AccessPolicy on Keyvault: 25-add-users-to-kv-get-list-access-policy.ps1"

Write-Host "spID: $spID"
Write-Host "tenantID: $tenantID"
Write-Host "storageAccount: $storageAccount"
Write-Host "adlsgen2filesystem: $adlsgen2filesystem"
Write-Host "projectXXX - full project name: $projectXXX"
Write-Host "userObjectIds: $userObjectIdsArray"
Write-Host "projectSPObjectID: $projectSPObjectID"
Write-Host "commonSPObjectID: $commonSPObjectID"
Write-Host "commonADgroupObjectID: $commonADgroupObjectID"
Write-Host "projectADGroupObjectId: $projectADGroupObjectId"

Write-Host "Not running add-users-to-datalake-acl"

& ".\25-add-users-to-datalake-acl-rbac.ps1" -spSecret $spSecret -spID $spID -tenantID $tenantID -storageAccount $storageAccount -adlsgen2filesystem $adlsgen2filesystem -projectXXX $projectXXX -userObjectIds $userObjectIdsArray -projectSPObjectID $projectSPObjectID -commonSPObjectID $commonSPObjectID -commonADgroupObjectID $commonADgroupObjectID -projectADGroupObjectId $projectADGroupObjectId

Write-Host "25-add-users-to-kv-get-list-access-policy"

& ".\25-add-users-to-kv-get-list-access-policy.ps1" -spSecret $spSecret -spID $spID -tenantID $tenantID -subscriptionID $subscriptionID -userObjectIds $userObjectIdsArray -projectOrCoreteam 'project' -keyvaultName $projectKeyvaultName

Write-Host "Finished!"
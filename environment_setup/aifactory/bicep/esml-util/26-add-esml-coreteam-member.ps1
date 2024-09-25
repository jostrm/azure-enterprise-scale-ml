# USAGE: 
# .\26-add-esml-coreteam-member.ps1 -spSecret 'abc' -spID 'abc' -tenantID 'abc' -subscriptionID 'abc' -storageAccount 'abc' -adlsgen2filesystem 'abc' -userObjectIds 'x','y','z' -projectSPObjectID 'abc' -projectKeyvaultNameSuffix '01' -commonKeyvaultNameSuffix '001' -aifactorySalt 'abcde' -commonRGNamePrefix 'abc-def-' -commonResourceSuffix '-001' -aifactorySuffixRG '-001' -locationSuffix 'weu' -projectNumber '001' -env 'dev'

param (
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$subscriptionID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem,
    [Parameter(Mandatory = $false, HelpMessage = "Array of user Object Ids")][string]$userObjectIds,
    [Parameter(Mandatory = $false, HelpMessage = "project keyvault suffix: 01 in kv-p003-uks-dev-abcde01")][string]$projectKeyvaultNameSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "common keyvaults suffix: 001 in kv-cmnadm-abcde-001 and kv-cmndev-abcde-001")][string]$commonKeyvaultNameSuffix,
    [Parameter(Mandatory = $false, HelpMessage = "AIFactory salt: abcde in any resource, such as kv-cmnadm-abcde-001")][string]$aifactorySalt,
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
$deplName1 = '26-add-esml-coreteam-member1'
$deplName2 = '26-add-esml-coreteam-member2'
$common_rg = "${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}" # dc-heroes-esml-common-weu-dev-001
$project_rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"

$projectKeyvaultName = "kv-p${projectNumber}-${locationSuffix}-${env}-${aifactorySalt}${projectKeyvaultNameSuffix}" # kv-p001-weu-dev-abcde01
$commonKeyvaultName = "kv-cmn${env}-${aifactorySalt}-${commonKeyvaultNameSuffix}" # kv-cmndev-abcde-001
$commonAdmKeyvaultName = "kv-cmnadm${env}-${aifactorySalt}-${commonKeyvaultNameSuffix}" # kv-cmnadmdev-abcde-001
$dashboard_resourcegroup_name = 'dashboards'

Write-Host "Common RG" $common_rg
Write-Host "Project RG" $project_rg
Write-Host "Common RG : ${common_rg}"
Write-Host "Project RG : ${project_rg}"
Write-Host "Dashboard RG : ${dashboard_resourcegroup_name}"
Write-Host "UserIds : ${userObjectIds}"
Write-Host "project kv : ${projectKeyvaultName}"
Write-Host "common kv : ${commonKeyvaultName}"
Write-Host "common adm kv : ${commonAdmKeyvaultName}"
Write-Host "BYOvNetResourceGroup: ${BYOvNetResourceGroup}"
Write-Host "BYOvNetName: ${BYOvNetName}"

Write-Host "Kicking off the BICEP..."

if (-not [String]::IsNullOrEmpty($BYOvNetName)) {
  Write-Host "Running BYOVnet logic, first step: addCoreaTeamAsMemberOfCommonRG"
  Set-AzDefault -ResourceGroupName $common_rg

  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsCoreteam.bicep" `
  -Name $deplName1 `
  -ResourceGroupName $common_rg `
  -common_resourcegroup_name $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -user_object_ids $userObjectIds `
  -storage_account_name_datalake $storageAccount `
  -Verbose

  Write-Host "Running BYOVnet logic, second and last step: addCoreTeamAsProjectMemberBYOVnet"
  Set-AzDefault -ResourceGroupName $BYOvNetResourceGroup

  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsCoreteamBYOVnet.bicep" `
  -Name $deplName2 `
  -ResourceGroupName $BYOvNetResourceGroup `
  -user_object_ids $userObjectIds `
  -vnet_resourcegroup_name $BYOvNetResourceGroup `
  -vnet_name $BYOvNetName `
  -Verbose

}else {
  Write-Host "Running standard logic (not BYOVnet logic)..."
  New-AzResourceGroupDeployment -TemplateFile "../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/addUserAsCoreteam.bicep" `
  -Name $deplName1 `
  -ResourceGroupName $common_rg `
  -common_resourcegroup_name $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -user_object_ids $userObjectIds `
  -storage_account_name_datalake $storageAccount `
  -Verbose
}

$inUserObjectIdsArray = $userObjectIds -split ','

$emptyArray = @()
$userObjectIdsArray = ($inUserObjectIdsArray + $emptyArray) | Sort-Object -Unique

Write-Host "- Now adding users Access policys (Get, List, Set) for COMMON Keyvault (example: kv-cmndev-abcde-001) - 25-add-users-to-kv-get-list-access-policy"

& ".\25-add-users-to-kv-get-list-access-policy.ps1" -spSecret $spSecret -spID $spID -tenantID $tenantID -subscriptionID $subscriptionID -userObjectIds $userObjectIdsArray -projectOrCoreteam 'coreteam' -keyvaultName $commonKeyvaultName

Write-Host "- Now adding users Access policys (Get, List, Set) for COMMON ADMIN Keyvault (example: kv-cmnadmdev-abcde-001) - 25-add-users-to-kv-get-list-access-policy"
& ".\25-add-users-to-kv-get-list-access-policy.ps1" -spSecret $spSecret -spID $spID -tenantID $tenantID -subscriptionID $subscriptionID -userObjectIds $userObjectIdsArray -projectOrCoreteam 'coreteam' -keyvaultName $commonAdmKeyvaultName

Write-Host "- Now adding users Access policys (Get, List, Set) for PROJECT Keyvault (example: kv-p001-weu-dev-abcde01) - 25-add-users-to-kv-get-list-access-policy"

& ".\25-add-users-to-kv-get-list-access-policy.ps1" -spSecret $spSecret -spID $spID -tenantID $tenantID -subscriptionID $subscriptionID -userObjectIds $userObjectIdsArray -projectOrCoreteam 'project' -keyvaultName $projectKeyvaultName

Write-Host "Finished!"
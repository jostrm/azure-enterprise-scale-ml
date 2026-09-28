# USAGE: 
# cd aifactory\esml-util
# .\26-add-esml-project-member.ps1 -spID -tenantID  -subscriptionID -storageAccount -adlsgen2filesystem -userObjectIds 'x,y,z' -projectSPObjectID -commonSPObjectID -commonADgroupObjectID 'NULL' -projectADGroupObjectId 'NULL' -projectKeyvaultName -commonRGNamePrefix -commonResourceSuffix '-001' -aifactorySuffixRG '-001' -locationSuffix -projectNumber -env 'dev'

param (
    # required parameters
    [Parameter(Mandatory = $false, HelpMessage = "Deprecated: use preauthenticated Azure CLI and Az PowerShell contexts")][string]$spSecret,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the App id for service principal")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$subscriptionID,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory = $true)][string]$storageResourceGroup,
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem = 'lake3',
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
    [Parameter(Mandatory = $true, HelpMessage = "ESML AIFactory environment: [dev,test,prod]")][ValidateSet('dev','test','prod')][string]$env,
    [Parameter(Mandatory = $false, HelpMessage = "BYOvNet Resource Group - BYOVnet")][string]$BYOvNetResourceGroup,
    [Parameter(Mandatory = $false, HelpMessage = "BYOvNet vNet Name")][string]$BYOvNetName,
    [Parameter(Mandatory = $false, HelpMessage = "useADGroups instead of User ObjectID")][bool]$useADGroups,
    [string[]]$managedIdentityObjectIds = @(),
    [string[]]$readOnlyObjectIds = @(),
    [switch]$LegacyLayout,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
if ($spSecret) {
  throw 'Secret-based login is no longer supported. Authenticate the approved deployment identity in Azure CLI and Az PowerShell first.'
}

# EDIT per your convention if it differs from ESML AIFactory defaults
$deplName1 = '26-add-esml-project-member-1'
$deplName2 = '26-add-esml-project-member-2'
$projectXXX = "project"+$projectNumber
$common_rg = "${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}" # dc-heroes-esml-common-weu-dev-001
$project_rg = "${commonRGNamePrefix}esml-project${projectNumber}-${locationSuffix}-${env}${aifactorySuffixRG}-rg"
$userObjectIdsArray = @($userObjectIds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique)
$aclParameters = @{
  tenantID = $tenantID
  subscriptionID = $subscriptionID
  storageAccount = $storageAccount
  storageResourceGroup = $storageResourceGroup
  adlsgen2filesystem = $adlsgen2filesystem
  projectXXX = $projectXXX
  environment = $env
  userObjectIds = $(if ($useADGroups) { @() } else { $userObjectIdsArray })
  projectSPObjectID = $projectSPObjectID
  projectADGroupObjectId = $(if ($useADGroups) { (@($projectADGroupObjectId) + $userObjectIdsArray | Where-Object { $_ }) -join ',' } else { $projectADGroupObjectId })
  managedIdentityObjectIds = $managedIdentityObjectIds
  readOnlyObjectIds = $readOnlyObjectIds
  LegacyLayout = $LegacyLayout
}
$aclScript = Join-Path $PSScriptRoot '25-add-users-to-datalake-acl-rbac.ps1'
# Validate and preview lake access before any ARM or Key Vault mutation.
& $aclScript @aclParameters
if (-not $Execute) {
  Write-Host 'Preview only. Supply -Execute to apply project-member ARM roles, lake ACLs and Key Vault policy.'
  return
}
$context = Get-AzContext
if (-not $context -or $context.Subscription.Id -ne $subscriptionID -or $context.Tenant.Id -ne $tenantID) {
  throw 'Az PowerShell context must already target the requested subscription and tenant. No account context is changed automatically.'
}
if ($storageResourceGroup -ne $common_rg) {
  throw 'This legacy ARM member caller requires the lake in its resolved common RG. For a BYO lake in another RG, run 25-add-users-to-datalake-acl-rbac.ps1 directly with its exact storageResourceGroup.'
}
if ($userObjectIdsArray.Count -gt 0 -and [string]::IsNullOrWhiteSpace($projectKeyvaultName)) {
  throw 'projectKeyvaultName is required when applying the legacy member Key Vault access policy.'
}
Write-Host "Common RG" $common_rg
Write-Host "Project RG" $project_rg

$vnetNameBase = 'vnt-esmlcmn'
$vnetNameFull = "${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}"
$bastion_service_name = "bastion-${locationSuffix}-${env}${aifactorySuffixRG}"
$dashboard_resourcegroup_name = 'dashboards'

# EDIT end
Write-Host "Kicking off the BICEP..."

Write-Host "common_rg : ${common_rg}"
Write-Host "project_rg : ${project_rg}"
Write-Host "dashboard_rg : ${dashboard_resourcegroup_name}"
Write-Host "projectSP_id : ${projectSPObjectID}"
Write-Host "vnetName : ${vnetNameFull}"
Write-Host "BYOvNetResourceGroup: ${BYOvNetResourceGroup}"
Write-Host "BYOvNetName: ${BYOvNetName}"
Write-Host "vnetName : ${vnetNameFull}"
Write-Host "kv : ${projectKeyvaultName}"
Write-Host "bastion : ${bastion_service_name}"
Write-Host "useADGroups: ${useADGroups}"

for ($i=0; $i -lt $userObjectIds.Length; $i++) {
  $userID = $userObjectIds[$i]
  Write-Host "userIds [$i] : ${userID}"
}

if (-not [String]::IsNullOrEmpty($BYOvNetName)) {
  Write-Host "Running BYOVnet logic - addUserAsProjectMemberByoVnet"
  New-AzResourceGroupDeployment -TemplateFile (Join-Path $PSScriptRoot '../modules/addUserAsProjectMemberByoVnet.bicep') `
  -Name $deplName1 `
  -ResourceGroupName $BYOvNetResourceGroup `
  -project_service_principle_oid $projectSPObjectID `
  -vnet_resourcegroup_name $BYOvNetResourceGroup `
  -vnet_name $BYOvNetName `
  -user_object_ids $userObjectIds `
  -useADGroups $useADGroups `
  -Verbose

  Write-Host "Running BYOVnet logic - addUserAsProjectMemberByoVnetRGs"
  New-AzResourceGroupDeployment -TemplateFile (Join-Path $PSScriptRoot '../modules/addUserAsProjectMemberByoVnetRGs.bicep') `
  -Name $deplName2 `
  -ResourceGroupName $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -user_object_ids $userObjectIds `
  -bastion_service_name $bastion_service_name `
  -storage_account_name_datalake $storageAccount `
  -lakeContainerName $adlsgen2filesystem `
  -useADGroups $useADGroups `
  -Verbose
}
else{
  Write-Host "Running standard logic (not BYOVnet logic)..."
  New-AzResourceGroupDeployment -TemplateFile (Join-Path $PSScriptRoot '../modules/addUserAsProjectMember.bicep') `
  -Name $deplName1 `
  -ResourceGroupName $common_rg `
  -project_resourcegroup_name $project_rg `
  -dashboard_resourcegroup_name $dashboard_resourcegroup_name `
  -project_service_principle_oid $projectSPObjectID `
  -vnet_name $vnetNameFull `
  -user_object_ids $userObjectIds `
  -bastion_service_name $bastion_service_name `
  -storage_account_name_datalake $storageAccount `
  -lakeContainerName $adlsgen2filesystem `
  -useADGroups $useADGroups `
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

& $aclScript @aclParameters -Execute

Write-Host "Applying project Key Vault get/list policy with the existing Az context"
# The legacy helper requires secret-login parameters; preserve its policy operation
# without reauthenticating or making a secret mandatory for this caller.
foreach ($targetObjectID in $userObjectIdsArray) {
  Set-AzKeyVaultAccessPolicy -VaultName $projectKeyvaultName -ObjectId $targetObjectID -PermissionsToSecrets get,list -BypassObjectIdValidation
}

Write-Host "Finished!"
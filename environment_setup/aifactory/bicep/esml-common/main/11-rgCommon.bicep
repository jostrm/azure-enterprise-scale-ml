targetScope = 'subscription'
@description('resource suffix, example: "-002" if this is a new ESML AI Factory')
param aifactorySuffixRG string =''

@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment. This name is reflected in resource group and sub-resources')
param env string
@description('Deployment location, westeurope, swedencentral')
param location string
@description('resource location awareness suffix. Example:"-weu"')
param locationSuffix string
@description('Specifies the tags that should be applied to newly created resources')
param tags object
@description('Specifies project owner email and will be used for tagging and RBAC')
param technicalContactEmail string = ''
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param technicalContactId string = ''
@description('Resource group prefix. If "rg-msft-word" then "rg-msft-word-{commonResourceName}-weu-dev-001"')
param commonRGNamePrefix string = ''
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsObjectID string = 'null'
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsEmail string = 'null'
param commonResourceGroup_param string = ''
param useAdGroups bool = false
param enableAdminVM bool = false
@description('Common resource name identifier. Default is "esml-common"')
param esmlCommonOverride string = 'esml-common'
param enableDefenderforAISubLevel bool = false
param enableDefenderforAIResourceLevel bool = false
param commonResourceSuffix string = ''

// CMK parameters (optional)
param cmk bool = false
param cmkKeyName string = ''
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
param inputKeyvaultSubscription string
param inputKeyvaultResourcegroup string

var technicalAdminsObjectID_array = array(split(technicalAdminsObjectID,','))
var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var technicalAdminsEmail_array_safe = technicalAdminsEmail == 'null'? []: technicalAdminsEmail_array
var subscriptionIdDevTestProd = subscription().subscriptionId

var commonResourceGroupName = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}${esmlCommonOverride}-${locationSuffix}-${env}${aifactorySuffixRG}' // aaa-bbb-{commonResourceName}-weu-dev-002 (31/90 chars)
var commonResourceGroupId = resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroupName)
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupId), 0, 5)

// CMK identity naming (needs to match 13-rgLevel usage)
var cmkIdentityName = 'id-cmn-cmk-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
var cmkIdentityIdString = resourceId(subscriptionIdDevTestProd, commonResourceGroupName, 'Microsoft.ManagedIdentity/userAssignedIdentities', cmkIdentityName)

module rgCommon '../../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'CommonRG${env}-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    rgName: commonResourceGroupName
    location: location
    tags: tags
  }
}

module contributorPermissions '../../modules/contributorRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'ContributorPermissionsOnRGCmn-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    //userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserIds: technicalAdminsObjectID_array_safe
    additionalUserEmails: technicalAdminsEmail_array_safe
    useAdGroups: useAdGroups
  }
  dependsOn:[
    rgCommon
  ]
}
module vmAdminLoginPermissions '../../modules/vmAdminLoginRbac.bicep' = if (enableAdminVM) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'VMAdminLoginPermissions-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    //userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserIds: technicalAdminsObjectID_array_safe
    additionalUserEmails: technicalAdminsEmail_array_safe
    useAdGroups: useAdGroups
  }
  dependsOn:[
    rgCommon
  ]
}

// CMK UAMI creation (moved earlier to allow propagation before 13-rgLevel)
module cmkIdentity '../../modules/mi.bicep' = if(cmk) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroupName)
  name: 'cmkIdentity-${uniqueInAIFenv}'
  params: {
    name: cmkIdentityName
    location: location
    tags: tags
  }
  dependsOn:[
    rgCommon
  ]
}

// Assign "Key Vault Crypto Service Encryption User" to the CMK Identity
module cmkRbac '../../modules/kvRbacSingleAssignment.bicep' = if (cmk) {
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
  name: 'cmkRbac-${uniqueInAIFenv}'
  params: {
    keyVaultName: inputKeyvault
    principalId: cmk ? reference(cmkIdentityIdString, '2023-01-31').principalId : ''
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6' // Key Vault Crypto Service Encryption User
    assignmentName: 'cmk-cmnrg-acr-rbac-${cmkIdentityName}'
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    cmkIdentity
  ]
}

// Deploy Microsoft Defender for Cloud at subscription level
module defenderForCloud '../security/defender.bicep' = if (enableDefenderforAISubLevel) {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'DefenderForCloud-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    enableAll: true
    pricingTier: 'Free'
    advancedPricingTier: 'Standard'
    enableDefenderForAI: enableDefenderforAISubLevel
    enableDefenderForKeyVault: true
    enableDefenderForStorage: true
    enableDefenderForContainers: false
    enableDefenderForCloudPosture: false
    enableDefenderForVirtualMachines: enableAdminVM
    enforce: 'False'
    enableAIPromptEvidence: false
    enableStorageMalwareScanning: true
    enableStorageSensitiveDataDiscovery: true
  }
  dependsOn:[
    rgCommon
  ]
}

// TODO 1 - Global private link scope, for Azure Monitor, one per Dev,Test, Prod
// https://docs.microsoft.com/en-us/azure/azure-monitor/logs/private-link-configure
// 1a) ESML CMN: resource symbolicname 'microsoft.insights/privateLinkScopes@2021-07-01-preview' = {
// 1b) ESML CMN: private link to the SCOPE network
// 1c) ESML CMN: Add Each Log Analytics Workspace (dev,test,prod)
// 1d) ESML CMN: Add workspace Queries to Each Log Analytics Workspace (dev,test,prod)
// 2)  ESML Project: When creating projects "applicationInsight", connect to correct Log Analytics Workspace (dev,test,prod)

targetScope = 'subscription'

// ================================================================
// CORE INFRASTRUCTURE DEPLOYMENT - Phase 2 Implementation
// This file deploys core infrastructure components including:
// - Storage Accounts (for AI/ML workloads)
// - Key Vault
// - Container Registry
// - Application Insights
// - Private Virtual Machine
// - Bing Search (if enabled)
// ================================================================

// ============================================================================
// SKU for services
// ============================================================================
param storageAccountSkuName string = 'Standard_LRS'
param containerRegistrySkuName string = 'Premium'
param bingSearchSKU string = 'S1'

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

// Resource exists flags from Azure DevOps
param keyvaultExists bool = false
param storageAccount1001Exists bool = false
param storageAccount2001Exists bool = false
param acrProjectExists bool = false
param applicationInsightExists bool = false
param vmExists bool = false
param bingExists bool = false

// Enable flags from parameter files
@description('Enable Bing Search deployment')
param serviceSettingDeployBingSearch bool = false

@description('Enable private VM deployment')
param serviceSettingDeployProjectVM bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// Required resource references
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// Key Vault specific
param keyvaultSoftDeleteDays int = 90
param keyvaultEnablePurgeProtection bool = true

// VM specific
param vmSKUSelectedArrayIndex int = 2
param vmSKU array = [
  'Standard_E2s_v3'
  'Standard_D4s_v3'
  'standard_D2as_v5'
]
param adminUsername string
param adminPassword string
param hybridBenefit bool = false

// Container Registry
param useCommonACR bool = true

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param restore bool = true

// Technical contact for access policies
param technicalContactId string = ''

// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string
param projectServicePrincipleAppID_SeedingKeyvaultName string
param projectServicePrincipleSecret_SeedingKeyvaultName string
param aifactorySalt10char string = ''
@description('Random value for deployment uniqueness')
param randomValue string = ''

// ============================================================================
// END - FROM JSON files
// ============================================================================

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId

// Calculated variables
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace('prj${projectNumber}', 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

var deploymentProjSpecificUniqueSuffix = '${projectNumber}${env}${targetResourceGroup}'

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: guid('naming-convention-03-core-infra',vnetResourceGroupName,deploymentProjSpecificUniqueSuffix)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue:randomValue
    aifactorySalt10char:aifactorySalt10char
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd:subscriptionIdDevTestProd
    acaSubnetId: acaSubnetId
    aksSubnetId:aksSubnetId
    genaiSubnetId:genaiSubnetId
  }
}

var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
var p011_genai_team_lead_email_array = namingConvention.outputs.p011_genai_team_lead_email_array
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array
var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
var randomSalt = namingConvention.outputs.randomSalt
var defaultSubnet = namingConvention.outputs.defaultSubnet
var aksSubnetName = namingConvention.outputs.aksSubnetName
var acaSubnetName = namingConvention.outputs.acaSubnetName
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var projectName = namingConvention.outputs.projectName
var genaiName = namingConvention.outputs.genaiName

// Import specific names needed for core infrastructure deployment
var keyvaultName = namingConvention.outputs.keyvaultName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var vmName = namingConvention.outputs.vmName
var bingName = namingConvention.outputs.bingName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
var kvNameCommon = 'kv-${namingConvention.outputs.cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var processedIpRulesKv = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]
var processedIpRulesSa = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]

// Network references using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, vnetResourceGroupName)
  name: vnetNameFull
}

resource subnet_aks 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: aksSubnetName
}

var subnet_aks_ref = {
  id: subnet_aks.id
}

// Get managed identity principal IDs using helper modules
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: 'getProjectMIPrincipalId-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

// Assumes the principals exists.
module getACAMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: 'getACAMIPrincipalId-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miACAName
  }
}

// Array vars - use principal IDs from helper modules
var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId
var var_miAca_PrincipalId = getACAMIPrincipalId.outputs.principalId

var mi_array = array(var_miPrj_PrincipalId)
var mi_array2 = array(var_miAca_PrincipalId)
var var_all_principals = union(p011_genai_team_lead_array, mi_array, mi_array2)

// Target resource group reference
resource resourceExists_struct 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: targetResourceGroup
  location: location
}

// ============== STORAGE ACCOUNTS ==============

// Main storage account for ML/AI workloads
module sacc '../modules/storageAccount.bicep' = if(!storageAccount1001Exists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AMLGenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    skuName: storageAccountSkuName
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    enablePublicGenAIAccess: enablePublicGenAIAccess
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}ml'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}ml'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}ml'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}ml'
    tags: tagsProject
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    vnetRules: [
      genaiSubnetId
      subnet_aks_ref.id
    ]
    ipRules: empty(processedIpRulesSa) ? [] : processedIpRulesSa
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.${location}.instances.azureml.ms'
          'https://457c18fd-a6d7-4461-999a-be092e9d1ec0.workspace.${location}.api.azureml.ms'
          'https://*.instances.azureml.ms'
          'https://*.azureml.ms'
        ]
        allowedMethods: [
          'GET'
          'HEAD'
          'POST'
          'PUT'
          'DELETE'
          'OPTIONS'
          'PATCH'
        ]
        maxAgeInSeconds: 2520
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== KEY VAULT ==============

module kv1 '../modules/keyVault.bicep' = if(!keyvaultExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AMGenAILKeyV4${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: tagsProject
    enablePurgeProtection: keyvaultEnablePurgeProtection
    soft_delete_days: keyvaultSoftDeleteDays
    tenantIdentity: tenant().tenantId
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      genaiSubnetId
      subnet_aks_ref.id
    ]
    accessPolicies: []
    ipRules: empty(processedIpRulesKv) ? [] : processedIpRulesKv
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== CONTAINER REGISTRY ==============

// Project-specific container registry (if not using common ACR)
module acr '../modules/containerRegistry.bicep' = if (!acrProjectExists && useCommonACR == false) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrProjectName
    skuName: containerRegistrySkuName
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}${locationSuffix}-containerreg-to-vnt-mlcmn'
    tags: tagsProject
    location: location
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Common container registry reference (if using common ACR)
// Reference maintained for infrastructure awareness but not directly used in current deployment
// TODO: Add common ACR integration logic if needed for cross-project container sharing

// ============== APPLICATION INSIGHTS ==============

module applicationInsightSWC '../modules/applicationInsightsRGmode.bicep' = if(!applicationInsightExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: applicationInsightName
    logWorkspaceName: laWorkspaceName
    logWorkspaceNameRG: commonResourceGroup
    tags: tagsProject
    location: location
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== VIRTUAL MACHINE ==============

module vmPrivate '../modules/virtualMachinePrivate.bicep' = if(!vmExists && serviceSettingDeployProjectVM == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'privVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: vmSKU[vmSKUSelectedArrayIndex]
    location: location
    vmName: vmName
    subnetName: defaultSubnet
    vnetId: vnet.id
    tags: tagsProject
    keyvaultName: keyvaultName
  }
  dependsOn: [
    resourceExists_struct
    kv1
  ]
}

// ============== BING SEARCH ==============

module bing '../modules/bing.bicep' = if(!bingExists && serviceSettingDeployBingSearch == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'BingSearch4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: bingName
    location: 'global'
    sku: bingSearchSKU
    tags: tagsProject
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== KEY VAULT SEEDING ==============

// External key vault for seeding secrets
resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

// Copy secrets from external key vault to project key vault
module addSecret '../modules/kvSecretsPrj.bicep' = if(!keyvaultExists) {
  name: 'kvSecretsS2P${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    spAppIDValue: externalKv.getSecret(projectServicePrincipleAppID_SeedingKeyvaultName)
    spOIDValue: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    spSecretValue: externalKv.getSecret(projectServicePrincipleSecret_SeedingKeyvaultName)
    keyvaultName: keyvaultName
    keyvaultNameRG: targetResourceGroup
  }
  dependsOn: [
    resourceExists_struct
    kv1
  ]
}

// ============== ACCESS POLICIES ==============

// Access policy definitions
var secretGetListSet = {
  secrets: [
    'get'
    'list'
    'set'
  ]
}
var secretGetList = {
  secrets: [
    'get'
    'list'
  ]
}
var secretGet = {
  secrets: [
    'get'
  ]
}

// Project key vault access policy for technical contact
module kvPrjAccessPolicyTechnicalContactAll '../modules/kvCmnAccessPolicys.bicep' = if(!keyvaultExists && !empty(technicalContactId)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'kvSecretsAP${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetListSet
    keyVaultResourceName: keyvaultName
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds: var_all_principals
  }
  dependsOn: [
    addSecret
    kv1
  ]
}

// Common key vault reference
resource commonKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvNameCommon
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// Common key vault access policy for technical contact
module kvCommonAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if(!empty(technicalContactId)) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'kvSecretsGL${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds: p011_genai_team_lead_array
  }
  dependsOn: [
    commonKv
  ]
}

// Service principal access to common key vault
module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'spGetList${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: commonKv.name
    policyName: 'add'
    principalId: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds: []
  }
  dependsOn: [
    commonKv
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Key Vault deployment status')
output keyVaultDeployed bool = !keyvaultExists

@description('Storage Account 1001 deployment status')
output storageAccount1001Deployed bool = !storageAccount1001Exists

@description('Container Registry deployment status')
output containerRegistryDeployed bool = (!acrProjectExists && useCommonACR == false)

@description('Application Insights deployment status')
output applicationInsightsDeployed bool = !applicationInsightExists

@description('Virtual Machine deployment status')
output virtualMachineDeployed bool = (!vmExists && serviceSettingDeployProjectVM)

@description('Bing Search deployment status')
output bingSearchDeployed bool = (!bingExists && serviceSettingDeployBingSearch)

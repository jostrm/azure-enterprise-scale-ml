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

// SKU for services
// ============================================================================
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS', 'Premium_LRS', 'Premium_ZRS', 'Standard_GZRS', 'Standard_RAGZRS'])
param storageAccountSkuName string = 'Standard_LRS'
@allowed(['Premium', 'Standard', 'Basic']) 
param containerRegistrySkuName string = 'Premium' // NB! Basic and Standard ACR SKUs don't support private endpoints.
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
param miACAExists bool = false
param miPrjExists bool = false

// Enable flags from parameter files
@description('Enable Bing Search deployment')
param serviceSettingDeployBingSearch bool = false

@description('Enable private VM deployment')
param serviceSettingDeployProjectVM bool = false

// Security and networking
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param allowPublicAccessWhenBehindVnet bool = false
param centralDnsZoneByPolicyInHub bool = false

// PS-Calculated and set by .JSON, that Powershell dynamically created in networking part.
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''
// Base parameters
param subnetCommon string = '' // Base parameter override (previous JSON)
param common_subnet_name string // Base parameter override (previous JSON)

// Users
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''

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
param adminUsername string ='aifactoryadmin'
param adminPassword string
param hybridBenefit bool = false

// Container Registry
param useCommonACR bool = true
param acr_adminUserEnabled bool = false
param acr_dedicated bool = true

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
param technicalContactId string = '' // TODO-Remove, Replaced by personas

// Principal type configuration
param useAdGroups bool = true

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
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'

// Sample Application parameters
@description('Enable deployment of sample applications')
param deploySampleApp bool = false

@description('Name of the authentication client secret in Key Vault')
param authClientSecretName string = 'aifactory-sample-app-1'

@description('Authentication client secret value for sample applications')
@secure()
param authClientSecret string = ''

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId

// Calculated variables
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd
var deploymentProjSpecificUniqueSuffix = '${projectNumber}${env}${targetResourceGroup}'
var commonSubnetName = !empty(subnetCommon)?replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('02-naming-${targetResourceGroup}', 64) // max 64 chars
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt10char: aifactorySalt10char
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
  }
}

var miACAName = namingConvention.outputs.miACAName
var miPrjName = namingConvention.outputs.miPrjName
//var p011_genai_team_lead_email_array = namingConvention.outputs.p011_genai_team_lead_email_array
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array
var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
//var randomSalt = namingConvention.outputs.randomSalt
var defaultSubnet = namingConvention.outputs.defaultSubnet
//var aksSubnetName = namingConvention.outputs.aksSubnetName
//var acaSubnetName = namingConvention.outputs.acaSubnetName
//var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var genaiName = namingConvention.outputs.genaiName

// Import specific names needed for core infrastructure deployment
var keyvaultName = namingConvention.outputs.keyvaultName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
//var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var acrProjectName = namingConvention.outputs.acrProjectName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var vmName = namingConvention.outputs.vmName
var bingName = namingConvention.outputs.bingName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
var kvNameCommon = namingConvention.outputs.kvNameCommon

// ============================================================================
// SPECIAL -Needs static name in existing
// ============================================================================
var bingName_Static = 'bing-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ACR - Common
var acrCommonName_Static = replace('acrcommon${uniqueInAIFenv_Static}${locationSuffix}${commonResourceSuffix}${env}','-','')
resource acrCommon 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = if (useCommonACR) {
  name: acrCommonName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// KV - Common
var cmnName_Static = 'cmn'
var kvCommonName_Static = 'kv-${cmnName_Static}${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource commonKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: kvCommonName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============================================================================
// SPECIAL - END
// ============================================================================

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

module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-getPrivDnsZ-${targetResourceGroup}', 64)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// Get managed identity principal IDs using helper modules
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('02-getPrMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

// Assumes the principals exists.
module getACAMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('02-getACAMI-${deploymentProjSpecificUniqueSuffix}', 64)
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
var mi_principals_only = union(mi_array, mi_array2)
//var var_all_principals = union(p011_genai_team_lead_array, mi_array, mi_array2)

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== DNS CONFIGURATIONS ==============
// DNS configurations for private endpoints - using dynamic outputs from modules

// ============== APPLICATION INSIGHTS ==============

module applicationInsightOtherType '../modules/applicationInsightsRGmode.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: applicationInsightName
    logWorkspaceName: laWorkspaceName
    logWorkspaceNameRG: commonResourceGroup
    tags: tagsProject
    location: location
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== STORAGE ACCOUNTS ==============

#disable-next-line BCP318
var var_sacc_dnsConfig = !storageAccount1001Exists? sacc.outputs.dnsConfig: []


// Main storage account for ML/AI workloads
module sacc '../modules/storageAccount.bicep' = if(!storageAccount1001Exists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-AMLGenAISto1${deploymentProjSpecificUniqueSuffix}', 64)
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
      aksSubnetId
    ]
    ipRules: empty(processedIpRulesSa) ? [] : processedIpRulesSa
    corsRules: [
      {
        allowedOrigins: [
          '*'
        ]
        allowedMethods: [
          'GET'
          'OPTIONS'
          'POST'
          'PUT'
        ]
        maxAgeInSeconds: 200
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
    existingTargetRG
  ]
}


#disable-next-line BCP318
var var_kv1_dnsConfig = !keyvaultExists? kv1.outputs.dnsConfig: []
#disable-next-line BCP318
var var_acr_dnsConfig = !acrProjectExists? acr.outputs.dnsConfig: []

// ============== KEY VAULT ==============

module kv1 '../modules/kvRbacKeyVault.bicep' = if(!keyvaultExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-AMGenAILKeyV4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: tagsProject
    enablePurgeProtection: keyvaultEnablePurgeProtection
    soft_delete_days: keyvaultSoftDeleteDays
    tenantIdentity: tenant().tenantId
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    enablePublicGenAIAccess:enablePublicGenAIAccess
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: '${keyvaultName}-pend'
    keyvaultNetworkPolicySubnets: [
      genaiSubnetId
      aksSubnetId
    ]
    ipRules: empty(processedIpRulesKv) ? [] : processedIpRulesKv
    secrets: deploySampleApp ? [
      {
        name: authClientSecretName
        value: authClientSecret ?? ''
      }
    ] : []
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== CONTAINER REGISTRY ==============
var processedIpRules = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]



// Project-specific container registry (if not using common ACR)
module acr '../modules/containerRegistry.bicep' = if (!acrProjectExists && !useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}', 64)
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
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    ipRules: processedIpRules
    existingIpRules: [] // Project-specific ACR has no existing rules initially
    adminUserEnabled: acr_adminUserEnabled
    dedicatedDataPoint: acr_dedicated
  }
  dependsOn: [
    existingTargetRG
  ]
}

// Get existing IP rules from common ACR if using common ACR
module getExistingAcrIpRules '../modules/get-acr-ip-rules.bicep' = if (useCommonACR) {
  name: take('02-getACRIpRules-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  params: {
    containerRegistryName: acrCommonName_Static
  }
}

#disable-next-line BCP318
var existingIpRules = useCommonACR ? getExistingAcrIpRules.outputs.ipRules : []

// Update since: "ACR sku cannot be retrieved because of internal error." when creating private endpoint.
// pend-acr-cmnsdc-containerreg-to-vnt-mlcmn
module acrCommonUpdate '../modules/containerRegistry.bicep' = if (useCommonACR == true){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: take('02-AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    containerRegistryName: acrCommonName_Static
    skuName: containerRegistrySkuName
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: commonSubnetName // snet-esml-cmn-001
    privateEndpointName: 'pend-acr-cmn${locationSuffix}-containerreg-to-vnt-mlcmn' // snet-esml-cmn-001
    tags: tagsProject
    location: location
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    ipRules: processedIpRules
    existingIpRules: existingIpRules
    adminUserEnabled: acr_adminUserEnabled
    dedicatedDataPoint: acr_dedicated
  }

  dependsOn: [
    acrCommon
  ]
}
// Common container registry reference (if using common ACR)  
// Reference maintained for infrastructure awareness but not directly used in current deployment
// TODO: Add common ACR integration logic if needed for cross-project container sharing

// ============== MANAGED IDENTITY FOR CONTAINER APPS ==============

// Array vars - use principal IDs from helper modules
var miAcaPrincipalId = getACAMIPrincipalId.outputs.principalId!

module miRbacCmnACR '../modules/miRbac.bicep' = if(useCommonACR && !miACAExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('02-miRbacCmnACR-${deployment().name}-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    containerRegistryName: useCommonACR? acrCommonName_Static: acrProjectName
    principalId: miAcaPrincipalId
  }
}

var miPrjPrincipalId = getProjectMIPrincipalId.outputs.principalId!

module miPrjRbacCmnACR '../modules/miRbac.bicep' = if(useCommonACR && !miPrjExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('02-miPrjRbacCmnACR-${deployment().name}-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    containerRegistryName: useCommonACR? acrCommonName_Static: acrProjectName
    principalId: miPrjPrincipalId
  }
}

// ============== VIRTUAL MACHINE ==============

module vmPrivate '../modules/virtualMachinePrivate.bicep' = if(!vmExists && serviceSettingDeployProjectVM == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-privVM4${deploymentProjSpecificUniqueSuffix}', 64)
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
    existingTargetRG
    kv1
  ]
}

// ============== BING SEARCH ==============

// ============== KEY VAULT SEEDING ==============

// External key vault for seeding secrets
resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = if (!empty(inputKeyvault) && !empty(inputKeyvaultResourcegroup) && !empty(inputKeyvaultSubscription)) {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

// Copy secrets from external key vault to project key vault
module addSecret '../modules/kvSecretsPrj.bicep' = if(!keyvaultExists && !empty(inputKeyvault)) {
  name: take('02-kvSecretsS2P${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    spAppIDValue: (!empty(inputKeyvault) && !empty(inputKeyvaultResourcegroup) && !empty(inputKeyvaultSubscription)) ? externalKv!.getSecret(projectServicePrincipleAppID_SeedingKeyvaultName) : ''
    spOIDValue: (!empty(inputKeyvault) && !empty(inputKeyvaultResourcegroup) && !empty(inputKeyvaultSubscription)) ? externalKv!.getSecret(projectServicePrincipleOID_SeedingKeyvaultName) : ''
    spSecretValue: (!empty(inputKeyvault) && !empty(inputKeyvaultResourcegroup) && !empty(inputKeyvaultSubscription)) ? externalKv!.getSecret(projectServicePrincipleSecret_SeedingKeyvaultName) : ''
    keyvaultName: keyvaultName
    keyvaultNameRG: targetResourceGroup
  }
  dependsOn: [
    existingTargetRG
    kv1
  ]
}

// ============== KEY VAULT RBAC ASSIGNMENTS ==============

// Key Vault role definitions
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' // Can get, list, set secrets
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6' // Can get, list secrets
var keyVaultContributorRoleId = 'f25e0fa2-a7c8-4377-a976-54943a77a395' // Management operations

// Project key vault RBAC assignments for technical contact and team
module kvPrjRbacAssignments '../modules/kvRbacAssignments.bicep' = if(!keyvaultExists && !empty(technicalContactId)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-kvRbacPrj${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultName: keyvaultName
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: [] // Will be handled separately
    managedIdentityIds: mi_principals_only // Both project and ACA managed identities
    useAdGroups: useAdGroups
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId
    keyVaultContributorRoleId: keyVaultContributorRoleId
  }
  dependsOn: [
    addSecret
    kv1
  ]
}

// Note: Common key vault still uses access policies (not changed per requirements)
// Common key vault access policy for technical contact
module kvCommonAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if(!empty(technicalContactId)) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('02-kvSecretsGL${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultPermissions: {
      secrets: [
        'get'
        'list'
      ]
    }
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds: p011_genai_team_lead_array
  }
  dependsOn: [
    commonKv
  ]
}

// Service principal access to common key vault (keeping access policy model)
module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if (!empty(inputKeyvault) && !empty(inputKeyvaultResourcegroup) && !empty(inputKeyvaultSubscription)) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('02-spGetList${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultPermissions: {
      secrets: [
        'get'
      ]
    }
    keyVaultResourceName: commonKv.name
    policyName: 'add'
    principalId: externalKv!.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds: []
  }
  dependsOn: [
    commonKv
  ]
}

// ============== PRIVATE DNS MODULES ==============

// Storage Account Private DNS
module privateDnsStorage '../modules/privateDns.bicep' = if(!storageAccount1001Exists && centralDnsZoneByPolicyInHub == false) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-corePrivDnsSA${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_sacc_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    existingTargetRG
  ]
}

// Key Vault Private DNS
module privateDnsKeyVault '../modules/privateDns.bicep' = if(!keyvaultExists && centralDnsZoneByPolicyInHub == false) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-corePrivDnsKV${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_kv1_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    existingTargetRG
  ]
}

// Container Registry Private DNS
module privateDnsContainerRegistry '../modules/privateDns.bicep' = if(!acrProjectExists && !centralDnsZoneByPolicyInHub && !useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('02-corePrivDnsACR${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    dnsConfig: var_acr_dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    CmnZones
    existingTargetRG
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

//@description('Bing Search deployment status')
//output bingSearchDeployed bool = (!bingExists && serviceSettingDeployBingSearch)

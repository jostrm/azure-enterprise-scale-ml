targetScope = 'subscription'
// ================================================================
// ML PLATFORM DEPLOYMENT - Phase 6 Implementation
// This file deploys ML and AI platform services including:
// - AI Foundry Hub and Project (pre 2025)
// - RBAC and permissions for AI platform
// ================================================================

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
param aiHubExists bool = false
param aifProjectExists bool = false
param miPrjExists bool = false

// Enable flags from parameter files
param enableAIFoundryHub bool = false
param addAIFoundryHub bool = false
param enableAzureOpenAI bool = false
param enableAISearch bool = false
param enableAIServices bool = false
param addAISearch bool = false

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Enable Customer Managed Keys (CMK) encryption')
param cmk bool = false

@description('Name of the Customer Managed Key in Key Vault')
param cmkKeyName string = ''

// AI Models deployment parameters
@description('Whether to deploy GPT-X model')
param deployModel_gpt_X bool = false
@description('GPT-X model name if deploying')
param modelGPTXName string = 'gpt-5-mini'
@description('GPT-X model version if deploying')
param modelGPTXVersion string = '1'
@allowed(['Standard','DataZoneStandard','GlobalStandard'])
param modelGPTXSku string = 'DataZoneStandard'
@description('TPM:Tokens per Minute Rate Limit in K=1000) 30 meaning 30K')
param modelGPTXCapacity int = 30

@description('Whether to deploy text-embedding-ada-002 model')
param deployModel_text_embedding_ada_002 bool = false
@description('Whether to deploy text-embedding-3-large model')
param deployModel_text_embedding_3_large bool = false
@description('Whether to deploy text-embedding-3-small model')
param deployModel_text_embedding_3_small bool = false
@description('Default capacity for embedding models')
param default_embedding_capacity int = 25

@description('Default capacity for GPT models')
param default_gpt_capacity int = 40
@description('Whether to deploy GPT-4o model')
param deployModel_gpt_4o bool = false
param default_gpt_4o_version string = '2024-11-20' // '2024-08-06'
@description('Whether to deploy GPT-4o-mini model')
param deployModel_gpt_4o_mini bool = false
param default_gpt_4o_mini_version string = '2024-07-18' // All models works with Bing search, except gpt-4o-mini,version: 2024-07-18 

@description('Default SKU for models')
@allowed(['Standard','DataZoneStandard','GlobalStandard'])
param default_model_sku string = 'Standard'

@description('Keyvault seeding configuration')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string

// Security and networking
param enablePublicGenAIAccess bool = false
param allowPublicAccessWhenBehindVnet bool = false
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// ============================================================================
// PS-Networking: Needs to be here, even if not used, since .JSON file
// ============================================================================
@description('Required subnet IDs from subnet calculator')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string
@description('Optional subnets from subnet calculator')
param aca2SubnetId string = ''
param aks2SubnetId string = ''
@description('if projectype is not genai-1, but instead all')
param dbxPubSubnetName string = ''
param dbxPrivSubnetName string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param common_subnet_name string // TODO - 31-network.bicep for own subnet
param subnetCommon string = ''
param subnetCommonScoring string = ''
// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// Tags
param tagsProject object = {}
param tags object = {}

// IP Rules
param IPwhiteList string = ''

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string

// Naming convention module
param aifactorySalt10char string = ''
param randomValue string
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// Common ACR usage
param useCommonACR bool = true

// Technical contact and user groups
param useAdGroups bool = false
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

// ============== VARIABLES ==============

// Calculated variables
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

// Random salt for unique naming - using uniqueString for deterministic salt
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// ============================================================================
// COMPUTED VARIABLES - Networking subnets
// ============================================================================
var segments = split(genaiSubnetId, '/')
var vnetName = segments[length(segments) - 3] // Get the vnet name
var defaultSubnet = genaiSubnetName
var commonSubnetPends = subnetCommon != '' ? replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

// Get the subnet resource ID for the common subnet used for private endpoints
resource commonSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = {
  name: '${vnetNameFull}/${commonSubnetPends}'
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
}
var commonSubnetResourceId = commonSubnet.id

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('06-naming-${targetResourceGroup}', 64)
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
    acaSubnetId: acaSubnetId
    aksSubnetId:aksSubnetId
    genaiSubnetId:genaiSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    addAIFoundryHub: addAIFoundryHub
  }
}

// MI
var miPrjName = namingConvention.outputs.miPrjName
var miACAName = namingConvention.outputs.miACAName

// AML
var amlName = namingConvention.outputs.amlName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
//var aksClusterName = namingConvention.outputs.aksClusterName

// AI Foundry Hub
var aifV1HubName = namingConvention.outputs.aifV1HubName
var aifV1ProjectName = namingConvention.outputs.aifV1ProjectName

// AI Foundry V2
var aifV2ProjectName = namingConvention.outputs.aifV2Name
var aifV2Name = namingConvention.outputs.aifV2PrjName

// Optional dependencies: AI Search, AI Services
var safeNameAISearchOrg = enableAISearch? namingConvention.outputs.safeNameAISearch: ''

var cleanRandomValue = take(namingConvention.outputs.randomSalt,2)

var safeNameAISearchBase = (enableAISearch && !empty(safeNameAISearchOrg))
  ? take(safeNameAISearchOrg, max(length(safeNameAISearchOrg) - 3, 0))
  : ''

var safeNameAISearchSuffix = (enableAISearch && !empty(safeNameAISearchOrg))
  ? substring(
      safeNameAISearchOrg,
      max(length(safeNameAISearchOrg) - 3, 0),
      min(3, length(safeNameAISearchOrg))
    )
  : ''

var aiSearchName = (enableAISearch && !empty(safeNameAISearchOrg))
  ? take(
      addAISearch
        ? '${safeNameAISearchBase}${cleanRandomValue}${safeNameAISearchSuffix}'
        : safeNameAISearchOrg,
      60
    )
  : ''

var aiServicesName = enableAIServices? namingConvention.outputs.aiServicesName: ''

// Common: AML, AI Fondry Hub
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var var_acr_cmn_or_prj = useCommonACR ? acrCommonName : acrProjectName
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var aksSubnetName = namingConvention.outputs.aksSubnetName
var genaiName = namingConvention.outputs.projectTypeGenAIName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var keyvaultName = namingConvention.outputs.keyvaultName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: replace(ip, '/32', '')]

// Normalize IP addresses: add /32 to single IPs if not present
var ipWhitelist_normalized = [for ip in ipWhitelist_array: contains(trim(ip), '/') ? trim(ip) : '${trim(ip)}/32']

var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRulesAIHub = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]

resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

// Private DNS zones (simplified structure)
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('06-getPrivDnsZ-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============================================================================
// SPECIAL -Needs static name in existing
// ============================================================================
var cmnName_Static = 'cmn'
var laWorkspaceName_Static = 'la-${cmnName_Static}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ALTERNATIVE WAY - NO WARNING of BCP318
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('05-getPrjMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}
var miPrjPrincipalId = getProjectMIPrincipalId.outputs.principalId!

// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing MI. Needs static name in existing
// ============================================================================
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

var randomSaltLogic = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 0, 10): aifactorySalt10char
var miPrjName_Static = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${randomSaltLogic}${resourceSuffix}'

resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: miPrjName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_miPrj_PrincipalId = miPrjREF.properties.principalId

module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: take('06-spAndMI2Array-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    managedIdentityOID: var_miPrj_PrincipalId
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    namingConvention
  ]
}
#disable-next-line BCP318
var spAndMiArray = spAndMI2ArrayModule.outputs.spAndMiArray
// ============================================================================
// END SPECIAL
// ============================================================================


// ============== AI FOUNDRY V2 - 2025 ==============

// Dynamically build array of models to deploy based on parameters
var aiModels = concat(
  deployModel_gpt_X ? [{
    modelName: modelGPTXName
    version: modelGPTXVersion
    capacity: modelGPTXCapacity
    skuLocation: modelGPTXSku
  }] : [],
  deployModel_gpt_4o_mini ? [{
    modelName: 'gpt-4o-mini'
    version: default_gpt_4o_mini_version
    capacity: default_gpt_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_gpt_4o ? [{
    modelName: 'gpt-4o'
    version: default_gpt_4o_version
    capacity: default_gpt_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_ada_002 ? [{
    modelName: 'text-embedding-ada-002'
    version: '2'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_3_large ? [{
    modelName: 'text-embedding-3-large'
    version: '1'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : [],
  deployModel_text_embedding_3_small ? [{
    modelName: 'text-embedding-3-small'
    version: '1'
    capacity: default_embedding_capacity
    skuLocation: default_model_sku
  }] : []
)

// ============== AI FOUNDRY HUB ==============

module aiHub '../modules/machineLearningAIHub.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('06-aiHubModule${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV1HubName
    managedIdentities: {
      systemAssigned: true 
      /* // v1.22
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miACAName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)) : []
      )
      */
    }
    defaultProjectName: aifV1ProjectName
    aiHubExists:aiHubExists
    location: location
    cmk: cmk
    cmkKeyName: cmkKeyName
    env: env
    tags: tagsProject
    aifactorySuffix: aifactorySuffixRG
    applicationInsightsName: applicationInsightName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    keyVaultName: keyvaultName
    privateEndpointName: 'p-aihub-${projectName}${locationSuffix}${env}${genaiName}amlworkspace'
    aifactoryProjectNumber: projectNumber
    storageAccountName: storageAccount1001Name
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    aiSearchName: aiSearchName
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    kindAIHub: 'Hub'
    aiServicesName: aiServicesName
    logWorkspaceName: logAnalyticsWorkspaceOpInsight.name
    logWorkspaceResoureGroupName: commonResourceGroup
    locationSuffix: locationSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt: namingConvention.outputs.uniqueInAIFenv
    //ipRules: empty(processedIpRulesAIHub) ? [] : processedIpRulesAIHub // OLD
    ipRules: empty(processedIpRulesAzureML) ? [] : processedIpRulesAzureML
    //ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32 // OLD
    ipWhitelist_array: empty(ipWhitelist_normalized) ? [] : ipWhitelist_normalized
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}

// ============== RBAC FOR PROJECT-SPECIFIC ACR ==============

module rbacAcrProjectspecific '../modules/acrRbac.bicep' = if(useCommonACR == false && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('06-rbacAcrProject${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    acrName: var_acr_cmn_or_prj
    aiHubName: aifV1HubName
    aiHubRgName: targetResourceGroup
  }
  dependsOn: [
    ...(!aiHubExists && enableAIFoundryHub ? [aiHub] : [])
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment


@description('AI Foundry Hub deployment status')
output aiFoundryHubDeployed bool = (!aiHubExists && enableAIFoundryHub)

@description('Project-specific ACR RBAC deployment status')
output acrRbacDeployed bool = (useCommonACR == false && enableAIFoundryHub)

@description('Storage Reader Role 1001 deployment status')
output storageReaderRole1001Deployed bool = (!aiHubExists && enableAIFoundryHub)

@description('Storage Reader Role 2001 deployment status')
output storageReaderRole2001Deployed bool = (!aiHubExists && enableAIFoundryHub)

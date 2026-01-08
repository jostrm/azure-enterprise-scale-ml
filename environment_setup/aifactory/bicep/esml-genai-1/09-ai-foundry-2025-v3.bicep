targetScope = 'subscription'

// ================================================================
// AI FOUNDRY 2025 DEPLOYMENT - Phase 9 Implementation
// This file deploys the latest AI Foundry 2025 platform including:
// - Microsoft Foundry Hub with advanced capabilities: Agents. AI Gateway with private integration, Defender for AI, Capabilty host for private Agents.
// - Foundry Project: Default
// - Model deployments (GPT, embedding models)
// - Private endpoints and networking
// - RBAC and security configurations
// ================================================================

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string
param containerAppsEnvExists bool = false
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

// FOUNDRY
@description('Enable AI Foundry 2 features')
param enableAIFoundry bool = false
param aiFoundryV2Exists bool = false
param enableAIFactoryCreatedDefaultProjectForAIFv2 bool = true
param aiFoundryV2ProjectExists bool = false
// 2 phase logic & flags
param foundryV22AccountOnly bool = false
param useAVMFoundry bool = false // https://github.com/Azure/bicep-registry-modules/tree/main/avm/ptn/ai-ml/ai-foundry#example-5-waf-aligned
param updateAIFoundry bool = false
param addAIFoundry bool = false
param Use_APIM_Project bool = true

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'


@description('Enable Capability host for AI Foundry - BYO network and resources for thread, vector, storage')
param enableCaphost bool = true
@description('Enable AI Search integration')
param enableAISearch bool = true
@description('Enable shared private link connections from Azure AI Search')
param enableAISearchSharedPrivateLink bool = true

@description('Enable Customer Managed Keys (CMK) encryption')
param cmk bool = false

@description('Name of the Customer Managed Key in Key Vault')
param cmkKeyName string = ''

@description('Enable Cosmos DB integration')
param enableCosmosDB bool = false

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
param deployModel_text_embedding_3_small bool = true
@description('Default capacity for embedding models')
param default_embedding_capacity int = 25

@description('Default capacity for GPT models')
param default_gpt_capacity int = 40
@description('Whether to deploy GPT-4o model')
param deployModel_gpt_4o bool = false
param default_gpt_4o_version string = '2024-11-20'
@description('Whether to deploy GPT-4o-mini model')
param deployModel_gpt_4o_mini bool = true
param default_gpt_4o_mini_version string = '2024-07-18'

@description('Default SKU for models')
@allowed(['Standard','DataZoneStandard','GlobalStandard'])
param default_model_sku string = 'Standard'

// Security and networking
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false

// ============================================================================
// PS-Networking: Needs to be here, even if not used, since .JSON file
// ============================================================================
@description('Required subnet IDs from subnet calculator: genai-1')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string
@description('Optional subnets from subnet calculator: all')
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
param common_subnet_name string
param subnetCommon string = ''

// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// Tags
param tagsProject object = {}

// Dependencies and naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param aifactorySalt10char string = ''
param randomValue string
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param addAISearch bool = false

// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string
param useAdGroups bool = true

param IPwhiteList string = ''
param enablePublicGenAIAccess bool = false
param allowPublicAccessWhenBehindVnet bool = false
@description('Disable agent network injection even when agentSubnetResourceId is provided.')
param disableAgentNetworkInjection bool = false
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'
@description('Optional existing API Management resource ID used for private endpoint wiring.')
param apiManagementResourceId string = ''
param enableDefenderforAISubLevel bool = false
param enableDefenderforAIResourceLevel bool = false

// ============== VARIABLES ==============

// Note: Ensure useAdGroups is set correctly based on your principal types
// If you're using Azure AD Groups, set useAdGroups = true
// If you're using individual users, set useAdGroups = false
// Mismatch will cause: UnmatchedPrincipalType error

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

// Random salt for unique naming
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// Subnet calculations
var commonSubnetPends = subnetCommon != '' ? replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var filteredIpWhitelist_array = filter(ipWhitelist_array, ip => length(ip) > 5)
var processedIpRules_ensure_32 = [for ip in filteredIpWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRules_remove32 = [for ip in filteredIpWhitelist_array: {
  action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]

// Get the subnet resource ID for the common subnet used for private endpoints
#disable-next-line no-unused-existing-resources
resource commonSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = {
  name: '${vnetNameFull}/${commonSubnetPends}'
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
}

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('09-naming-${targetResourceGroup}', 64)
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
  }
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============================================================================
// LOG ANALYTICS WORKSPACE - Fetch existing for diagnostic settings
// ============================================================================
var cmnName_Static = 'cmn'
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var laWorkspaceName_Static = 'la-${cmnName_Static}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============================================================================
// SPECIAL - Get PRINICPAL ID from KV. Needs static name in existing
// ============================================================================

var miPrjName = namingConvention.outputs.miPrjName
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('09-getMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId

var miAcaName = namingConvention.outputs.miACAName
module getAcaMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('09-getAcaMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miAcaName
  }
}

var var_miAca_PrincipalId = getAcaMIPrincipalId.outputs.principalId

resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}


// Get the Key Vault secret as a string using reference function
module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: take('09-spAndMI2Array-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    managedIdentityOID: var_miPrj_PrincipalId
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
      getProjectMIPrincipalId
  ]
}
#disable-next-line BCP318
var spAndMiArray = spAndMI2ArrayModule.outputs.spAndMiArray

var aifV2Name = addAIFoundry? namingConvention.outputs.aifV2NameAdd: namingConvention.outputs.aifV2Name
var aifV2ProjectName = addAIFoundry? namingConvention.outputs.aifV2PrjNameAdd: namingConvention.outputs.aifV2PrjName 

var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var projectCapHostName  = '${aifV2Name}caphost'
var defaultProjectName = enableAIFactoryCreatedDefaultProjectForAIFv2 ? aifV2ProjectName : '${aifV2ProjectName}def'
var defaultProjectDescription = 'Enterprise Scale AI Factory (v1.24) Foundry creation of project for with enterprise grade security and your corp networking.'

// Private DNS zones
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('09-getPrivDnsZ-${targetResourceGroup}', 64)
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

// Extract DNS zone IDs to ensure they are resolved as string literals
var openaiDnsZoneId = privateLinksDnsZones.openai.id
var cognitiveServicesDnsZoneId = privateLinksDnsZones.cognitiveservices.id

var aiFoundryZones = !enablePublicAccessWithPerimeter? [
  openaiDnsZoneId
  cognitiveServicesDnsZoneId
] : []

// Only create networkAcls when there are IP rules OR when public access is explicitly enabled
var shouldCreateNetworkAcls = !empty(processedIpRules_remove32) || enablePublicGenAIAccess || enablePublicAccessWithPerimeter || allowPublicAccessWhenBehindVnet

var networkAclVirtualNetworkRules = concat(
  [
    {
      id: genaiSubnetId
      ignoreMissingVnetServiceEndpoint: true // keep true so service endpoint isn’t required
    }
  ],
  !empty(aca2SubnetId) ? [
    {
      id: aca2SubnetId
      ignoreMissingVnetServiceEndpoint: true
    }
  ] : []
)

var networkAcls = shouldCreateNetworkAcls ? {
  defaultAction: enablePublicGenAIAccess && empty(processedIpRules_remove32) ? 'Allow' : 'Deny'
  virtualNetworkRules: networkAclVirtualNetworkRules
  ipRules: empty(processedIpRules_remove32) ? [] : processedIpRules_remove32
} : null

var networkAclsEmpty = {
  defaultAction: 'Deny'
  virtualNetworkRules: []
  ipRules: []
}

var networkAclsObject = networkAcls

// ============================================================================
// COGNITIVE SERVICES & OPENAI ROLE ASSIGNMENTS
// ============================================================================

var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// Cognitive Services and OpenAI role definition IDs
var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68' // Cognitive Services Contributor
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User  
var openAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442' // Cognitive Services OpenAI Contributor
var openAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
var azureAIDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee' // Azure AI Developer - CRITICAL for Chat with data

// Additional roles for complete AI Foundry functionality
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User - for Agent secrets
var keyVaultContributorRoleId = 'f25e0fa2-a7c8-4377-a976-54943a77a395' // Key Vault Contributor - for managing secrets
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' // Key Vault Secrets Officer - for Agent operations
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor - for resource management
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Reader - for resource access

@description('RBAC Security Phase 7 deployment completed successfully')
output rbacSecurityPhaseCompleted bool = true


var cleanRandomValue2 = take(namingConvention.outputs.randomSalt,2)
var safeNameAISearchOrg = enableAISearch? namingConvention.outputs.safeNameAISearch: ''
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
        ? '${safeNameAISearchBase}${cleanRandomValue2}${safeNameAISearchSuffix}'
        : safeNameAISearchOrg,
      60
    )
  : ''

  
// Get AI Search principal ID conditionally
module getAISearchInfo '../modules/get-ai-search-info.bicep' = if (enableAISearch && !foundryV22AccountOnly) {
  name: take('09-getAISearch-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: aiSearchName
  }
}

var aiSearchPrincipalId = enableAISearch ? getAISearchInfo!.outputs.principalId : ''

// Create role assignments module to build the dynamic array
module roleAssignmentsBuilder '../modules/csFoundry/buildRoleAssignments.bicep' = if(enableAIFoundry && !foundryV22AccountOnly && (!aiFoundryV2Exists || updateAIFoundry)) {
  name: take('09-roleBuilder-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    azureAIDeveloperRoleId: azureAIDeveloperRoleId // Add Azure AI Developer role
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId // Add Key Vault roles
    keyVaultContributorRoleId: keyVaultContributorRoleId
    storageBlobDataReaderRoleId: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1' // Storage Blob Data Reader for AI Search
    useAdGroups: useAdGroups
    enableAISearch: enableAISearch
    aiSearchPrincipalId: aiSearchPrincipalId
  }
  dependsOn: [
    spAndMI2ArrayModule
    namingConvention
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

#disable-next-line BCP318
var aiFoundryRoleAssignments = (enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly)) ? roleAssignmentsBuilder.outputs.roleAssignments : []

var aiFoundryDeployments = [
  for model in aiModels: {
    name: model.modelName
    model: {
      name: model.modelName
      format: 'OpenAI'
      version: model.version
    }
    sku: {
      name: model.skuLocation
      capacity: model.capacity
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
]

// Customer Managed Key (CMK) configuration - applies to all AI Foundry deployments
var customerManagedKey = cmk ? {
  keyName: cmkKeyName
  keyVaultResourceId: resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault)
  userAssignedIdentityResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)
} : null

var hasModelDeploymentsV22 = length(aiFoundryDeployments) > 0
var defaultModelDeploymentV22 = hasModelDeploymentsV22 ? aiFoundryDeployments[0] : {
  name: 'gpt-4o'
  model: {
    name: 'gpt-4o'
    format: 'OpenAI'
    version: default_gpt_4o_version
  }
  sku: {
    name: default_model_sku
    capacity: default_gpt_capacity
  }
  raiPolicyName: 'Microsoft.DefaultV2'
  versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
}
var extraModelDeploymentsV22 = (hasModelDeploymentsV22 && length(aiFoundryDeployments) > 1) ? skip(aiFoundryDeployments, 1) : []
var defaultModelNameV22 = string(defaultModelDeploymentV22.model.name)
var defaultModelFormatV22 = string(defaultModelDeploymentV22.model.format)
var defaultModelVersionV22 = string(defaultModelDeploymentV22.model.version)
var defaultModelSkuNameV22 = string(defaultModelDeploymentV22.sku.name)
var defaultModelCapacityV22 = int(defaultModelDeploymentV22.sku.capacity)

var aiFoundryNetworkingConfig = union({
  aiServicesPrivateDnsZoneResourceId: privateLinksDnsZones.servicesai.id
  cognitiveServicesPrivateDnsZoneResourceId: cognitiveServicesDnsZoneId
  openAiPrivateDnsZoneResourceId: openaiDnsZoneId
}, (!disableAgentNetworkInjection && !empty(aca2SubnetId)) ? {
  agentServiceSubnetResourceId: aca2SubnetId
} : {})

var aiFoundryDefinitionBase = {
  baseName: aifV2Name
  includeAssociatedResources: false
  location: location
  enableTelemetry: false
  tags: tagsProject
  privateEndpointSubnetResourceId: genaiSubnetId
  aiModelDeployments: aiFoundryDeployments
  aiFoundryConfiguration: {
    accountName: aifV2Name
    allowProjectManagement: true
    createCapabilityHosts: enableCaphost
    location: location
    disableLocalAuth: true
    networking: aiFoundryNetworkingConfig
    project: {
      name: defaultProjectName
      displayName: defaultProjectName
    }
    roleAssignments: aiFoundryRoleAssignments
    sku: 'S0'
  }
}

var aiFoundryDefinition = union(
  aiFoundryDefinitionBase,
  deployAvmFoundry && enableAISearch ? {
    aiSearchConfiguration: {
      existingResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Search/searchServices', aiSearchName)
      // privateDnsZoneResourceId: privateLinksDnsZones.searchService.id // Disabled to prevent duplicate PE creation
      roleAssignments: []
    }
  } : {},
  deployAvmFoundry ? {
    keyVaultConfiguration: {
      existingResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.KeyVault/vaults', namingConvention.outputs.keyvaultName)
      // privateDnsZoneResourceId: privateLinksDnsZones.vault.id // Disabled to prevent duplicate PE creation
      roleAssignments: []
    }
    storageAccountConfiguration: {
      existingResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', storageAccount1001Name)
      // blobPrivateDnsZoneResourceId: privateLinksDnsZones.blob.id // Disabled to prevent duplicate PE creation
      roleAssignments: []
    }
    storageAccountSecondaryConfiguration: {
      existingResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', storageAccount2001Name)
      // blobPrivateDnsZoneResourceId: privateLinksDnsZones.blob.id // Disabled to prevent duplicate PE creation
      roleAssignments: []
    }
  } : {},
  deployAvmFoundry && enableCosmosDB ? {
    cosmosDbConfiguration: {
      existingResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.DocumentDB/databaseAccounts', namingConvention.outputs.cosmosDBName)
      // privateDnsZoneResourceId: privateLinksDnsZones.cosmosdbnosql.id // Disabled to prevent duplicate PE creation
      roleAssignments: []
    }
  } : {}
)

// Subnet delegation for Container Apps
var aca2SubnetName = namingConvention.outputs.aca2SubnetName
var requiresAcaDelegation = enableAIFoundry && !aiFoundryV2Exists && !disableAgentNetworkInjection
module subnetDelegationAca '../modules/subnetDelegation.bicep' = if (requiresAcaDelegation) {
  name: take('09-snetDelegACA${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetNameFull
    subnetName: aca2SubnetName
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    delegations: [
      {
        name: 'aca-delegation'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

// Safe domain construction to avoid InvalidDomainName errors
var safeLocation = toLower(location)

// Create location-specific domains for all regions - Azure Container Apps and MCR are widely available
var acaLocationEndpoint = '${safeLocation}.ext.azurecontainerapps.dev'
var mcrLocationEndpoint = '${safeLocation}.data.mcr.microsoft.com'

// Raw FQDN array with potential empty strings
var fqdnRaw = [
  // Private link FQDNs for networking
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.documents.azure.com'
  'privatelink.file.${environment().suffixes.storage}'
  'privatelink.openai.azure.com'
  'privatelink.search.windows.net'
  'privatelink.services.ai.azure.com'
  
  // Public FQDNs for specific Azure services
  // Storage Account 1 - Blob, File, Queue endpoints
  '${namingConvention.outputs.storageAccount1001Name}.blob.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount1001Name}.file.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount1001Name}.queue.${environment().suffixes.storage}'
  
  // Storage Account 2 - Blob, File, Queue endpoints
  '${namingConvention.outputs.storageAccount2001Name}.blob.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount2001Name}.file.${environment().suffixes.storage}'
  '${namingConvention.outputs.storageAccount2001Name}.queue.${environment().suffixes.storage}'
  
  // AI Search endpoint (conditionally included)
  enableAISearch ? '${aiSearchName}.search.windows.net' : ''
  
  // Key Vault endpoint
  '${namingConvention.outputs.keyvaultName}${environment().suffixes.keyvaultDns}'
  
  // Cosmos DB endpoint (conditionally included)
  enableCosmosDB ? '${namingConvention.outputs.cosmosDBName}.documents.azure.com' : ''
  
  // AI Services endpoint
  '${aifV2Name}.cognitiveservices.azure.com'
  '${aifV2Name}.openai.azure.com'
  
  // #### Azure Container Apps (ACA) required FQDNs for AI agents ####
  
  // All scenarios - Microsoft Container Registry (MCR)
  'mcr.microsoft.com'
  // '*.data.mcr.microsoft.com' - replaced with regional endpoints
  mcrLocationEndpoint // Safe location-based endpoint
  // Aspire Dashboard 
  acaLocationEndpoint // Safe location-based ACA endpoint

  // Not inACA documented but required for various functionalities, Microsoft Graph API
  'graph.microsoft.com'

   // *.identity.azure.net
  'login.identity.azure.net'
  '${tenant().tenantId}.identity.azure.net'
  'sts.identity.azure.net'

  // '*.login.microsoft.com' - replaced with environment-specific endpoints
  
  'login.microsoft.com'
  'account.login.microsoft.com'
  'portal.login.microsoft.com'
  'oauth.login.microsoft.com'
  'secure.login.microsoft.com'
  'sso.login.microsoft.com'
  'device.login.microsoft.com'
  
  /*
  replace(environment().authentication.loginEndpoint, 'https://', '')
  'account.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'portal.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'oauth.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'secure.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'sso.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  'device.${replace(environment().authentication.loginEndpoint, 'https://', '')}'
  */

  // Docker Hub Registry (if needed)
  'hub.docker.com'
  'registry-1.docker.io'
  'production.cloudflare.docker.com'
]

// Filter out empty strings and remove duplicates to ensure valid FQDN list for Azure validation
var fqdnFiltered = filter(fqdnRaw, fqdnEntry => !empty(fqdnEntry))
var fqdn = reduce(fqdnFiltered, [], (current, next) => contains(current, next) ? current : union(current, [next]))

var deployAvmFoundry = useAVMFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly)
var shouldDeployFoundryPrivateEndpoints = !foundryV22AccountOnly && enableAIFoundry // ensures PE creation for full V21/V22 builds

// Reference to existing AI Account created in first deployment (when foundryV22AccountOnly was true)
// Used in second deployment to get principal ID without relying on module outputs from previous deployment
#disable-next-line BCP081
resource aiAccountExistingFromFirstDeployment 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = if(Use_APIM_Project && !foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && aiFoundryV2Exists) {
  name: aifV2Name
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

module aiFoundry2025NoAvmV22AccountOnly '../modules/csFoundry/aiFoundry2025AvmOffApimAccount.bicep' = if(Use_APIM_Project && foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && !aiFoundryV2Exists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV22-NoAvmAccountOnly_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    allowedFqdnList: fqdn // Now properly filtered to exclude empty strings
    location: location
    foundryV22AccountOnly: foundryV22AccountOnly
    aiAccountName: aifV2Name
    firstProjectName: defaultProjectName
    projectDescription: defaultProjectDescription
    displayName: defaultProjectName
    privateEndpointSubnetResourceId: genaiSubnetId
    agentSubnetResourceId: (!disableAgentNetworkInjection && !empty(aca2SubnetId)) ? aca2SubnetId : ''
    disableAgentNetworkInjection: disableAgentNetworkInjection
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    ipAllowList: filteredIpWhitelist_array
    enableCapabilityHost: enableCaphost
    projectCapHost: projectCapHostName
    userRoleObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    useAdGroups: useAdGroups
    extraModelDeployments: extraModelDeploymentsV22
    modelName: defaultModelNameV22
    modelFormat: defaultModelFormatV22
    modelVersion: defaultModelVersionV22
    modelSkuName: defaultModelSkuNameV22
    modelCapacity: defaultModelCapacityV22
    enableCosmosDb: enableCosmosDB
    enableAISearch: enableAISearch
    enableProject: enableAIFactoryCreatedDefaultProjectForAIFv2
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    restrictOutboundNetworkAccess: false
    tags: tagsProject
    privateLinksDnsZones: privateLinksDnsZones
    apiManagementResourceId: apiManagementResourceId
    azureStorageAccountResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', namingConvention.outputs.storageAccount1001Name)
    azureStorageAccountResourceIdSecondary: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', namingConvention.outputs.storageAccount2001Name)
    azureCosmosDBAccountResourceId: enableCosmosDB ? resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.DocumentDB/databaseAccounts', namingConvention.outputs.cosmosDBName) : ''
    aiSearchResourceId: enableAISearch ? resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Search/searchServices', aiSearchName) : ''
    customerManagedKey: customerManagedKey
  }
  dependsOn: [
    existingTargetRG
    namingConvention
    spAndMI2ArrayModule
    CmnZones
    subnetDelegationAca
  ]
}

module aiFoundry2025NoAvmV22 '../modules/csFoundry/aiFoundry2025AvmOffApim.bicep' = if(Use_APIM_Project && !foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && (!aiFoundryV2Exists || updateAIFoundry)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV22-NoAvm_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    allowedFqdnList: fqdn // Now properly filtered to exclude empty strings
    location: location
    foundryV22AccountOnly: foundryV22AccountOnly
    aiAccountName: aifV2Name
    firstProjectName: defaultProjectName
    projectDescription: defaultProjectDescription
    displayName: defaultProjectName
    privateEndpointSubnetResourceId: genaiSubnetId
    agentSubnetResourceId: (!disableAgentNetworkInjection && !empty(aca2SubnetId)) ? aca2SubnetId : ''
    disableAgentNetworkInjection: disableAgentNetworkInjection
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess: enablePublicGenAIAccess
    ipAllowList: filteredIpWhitelist_array
    enableCapabilityHost: enableCaphost
    projectCapHost: projectCapHostName
    userRoleObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    useAdGroups: useAdGroups
    extraModelDeployments: extraModelDeploymentsV22
    modelName: defaultModelNameV22
    modelFormat: defaultModelFormatV22
    modelVersion: defaultModelVersionV22
    modelSkuName: defaultModelSkuNameV22
    modelCapacity: defaultModelCapacityV22
    enableCosmosDb: enableCosmosDB
    enableAISearch: enableAISearch
    enableProject: enableAIFactoryCreatedDefaultProjectForAIFv2
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    restrictOutboundNetworkAccess: false
    tags: tagsProject
    privateLinksDnsZones: privateLinksDnsZones
    privDnsSubscription: privDnsSubscription_param
    privDnsResourceGroupName: privDnsResourceGroupName
    apiManagementResourceId: apiManagementResourceId
    azureStorageAccountResourceId: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', namingConvention.outputs.storageAccount1001Name)
    azureStorageAccountResourceIdSecondary: resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Storage/storageAccounts', namingConvention.outputs.storageAccount2001Name)
    azureCosmosDBAccountResourceId: enableCosmosDB ? resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.DocumentDB/databaseAccounts', namingConvention.outputs.cosmosDBName) : ''
    aiSearchResourceId: enableAISearch ? resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.Search/searchServices', aiSearchName) : ''
    cmk: cmk
    cmkKeyName: cmkKeyName
    cmkKeyVaultResourceId: cmk ? resourceId(inputKeyvaultSubscription, inputKeyvaultResourcegroup, 'Microsoft.KeyVault/vaults', inputKeyvault) : ''
  }
  dependsOn: [
    existingTargetRG
    namingConvention
    spAndMI2ArrayModule
    CmnZones
    subnetDelegationAca
  ]
}

// AI Foundry V2.1 - AI factory (Alternative Implementation, customer high regulatory reqs enforcement on top of WAF)
module aiFoundry2025NoAvm '../modules/csFoundry/aiFoundry2025AvmOff.bicep' = if(!Use_APIM_Project && !foundryV22AccountOnly && !deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2-NoAvm_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV2Name
    kind: 'AIServices'
    sku: 'S0'
    location: location
    enableTelemetry: false
    tags: tagsProject
    customSubDomainName: aifV2Name // aif2SubdomainName // aifV2Name // optional
    allowedFqdnList: fqdn // Now properly filtered to exclude empty strings
    restrictOutboundNetworkAccess: false // Agents need outbound access for various services such as AI Search, Key Vault, Storage, etc.
    publicNetworkAccess: enablePublicAccessWithPerimeter || enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet || !empty(processedIpRules_remove32) ? 'Enabled' : 'Disabled'
    agentSubnetResourceId: aca2SubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    disableAgentNetworkInjection: enablePublicAccessWithPerimeter? true: disableAgentNetworkInjection
    allowProjectManagement: true
    defaultProjectName: defaultProjectName
    #disable-next-line BCP318
    roleAssignments: roleAssignmentsBuilder.outputs.roleAssignments
    networkAcls: shouldCreateNetworkAcls ? networkAclsObject : networkAclsEmpty
    managedIdentities: {
      systemAssigned: true
      /* v1.22
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miAcaName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miAcaName)) : []
      )
      */
    }
    deployments: aiFoundryDeployments
    privateEndpointSubnetRID: genaiSubnetId
    privateLinksDnsZones: privateLinksDnsZones
    createPrivateEndpointsAIFactoryWay: true
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    customerManagedKey: customerManagedKey
    /*
    privateEndpoints: !enablePublicAccessWithPerimeter ? [
      {
        name: '${aifV2Name}-pend'
        subnetResourceId: commonSubnetResourceId
        privateDnsZoneResourceIds: aiFoundryZones
        service: 'account'
        location: location
      }
    ] : null
    */
  }
  dependsOn: [
    existingTargetRG
    roleAssignmentsBuilder
    spAndMI2ArrayModule
    namingConvention
    subnetDelegationAca
  ]
}

// AVM Option
module aiFoundry2025Avm '../modules/csFoundry/aiFoundry2025AvmOn.bicep' = if(deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly) && !foundryV22AccountOnly) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2-Avm_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    aiFoundry: aiFoundryDefinition
    enableTelemetry: false
  }
  dependsOn: [
    existingTargetRG
    roleAssignmentsBuilder
    spAndMI2ArrayModule
    namingConvention
    subnetDelegationAca
  ]
}
#disable-next-line BCP081
resource aiFoundryAccountAvm 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = if(deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly)) {
  name: aifV2Name
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

// Simplified: Get system-assigned managed identity principal ID based on deployment scenario
#disable-next-line BCP318
var aiFoundrySystemAssignedPrincipalId = foundryV22AccountOnly
  ? aiFoundry2025NoAvmV22AccountOnly!.outputs.aiAccountPrincipalId
  : (Use_APIM_Project
      // In second deployment, use existing resource if account was created in first deployment
      ? (aiFoundryV2Exists ? (aiAccountExistingFromFirstDeployment!.identity!.principalId ?? '') : aiFoundry2025NoAvmV22!.outputs.aiAccountPrincipalId)
      : (deployAvmFoundry
          ? (aiFoundryAccountAvm!.identity!.principalId ?? '')
          : aiFoundry2025NoAvm!.outputs.systemAssignedMIPrincipalId!))

// Project module - only for scenario 2b (non-APIM)
// Scenario 2a (APIM) creates project internally within aiFoundry2025NoAvmV22
var projectModuleEnabled = enableAIFactoryCreatedDefaultProjectForAIFv2

module projectV21 '../modules/csFoundry/aiFoundry2025project.bicep' = if(!Use_APIM_Project && projectModuleEnabled && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_Prj_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    storageName2: namingConvention.outputs.storageAccount2001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundryAccountNameOutput
    aiSearchName: enableAISearch ? aiSearchName : ''
    cosmosDBname: enableCosmosDB? namingConvention.outputs.cosmosDBName : ''
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    }
    dependsOn: [
      existingTargetRG
      // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
      ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
      ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
    ]
}

// AI Foundry Private Endpoints - deployed after main service
// Deploys when: not using public access, not using AVM, and in phase 2 (foundryV22AccountOnly=false)
// Executes last in both scenario 2a (APIM) and 2b (non-APIM)
module aiFoundryPrivateEndpoints '../modules/csFoundry/aiFoundry2025pend.bicep' = if(!enablePublicAccessWithPerimeter && !deployAvmFoundry && shouldDeployFoundryPrivateEndpoints && (updateAIFoundry || !foundryV22AccountOnly) && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21-PrivateEndpoints_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cognitiveServiceName: aiFoundryAccountNameOutput
    #disable-next-line BCP318
    cognitiveServiceId: Use_APIM_Project
      ? (aiFoundryV2Exists ? aiAccountExistingFromFirstDeployment!.id : aiFoundry2025NoAvmV22!.outputs.aiAccountId)
      : aiFoundry2025NoAvm!.outputs.resourceId
    location: location
    tags: tagsProject
    privateEndpointSubnetRID: genaiSubnetId
    privateLinksDnsZones: privateLinksDnsZones
    createPrivateEndpointsAIFactoryWay: true
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    apiManagementResourceId: apiManagementResourceId
  }
  dependsOn: [
    // Primary AI Foundry account deployment (scenario 2a or 2b)
    //     TODO Jocke (1st work IA) ...(Use_APIM_Project ? [aiFoundry2025NoAvmV22] : [aiFoundry2025NoAvm])
    // Match exact deployment conditions to avoid referencing non-existent modules
    ...(Use_APIM_Project && !foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvmV22] : [])
    ...(!Use_APIM_Project && !foundryV22AccountOnly && !deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvm] : [])
    // TODO Jocke end
    existingTargetRG
    // For scenario 2b (non-APIM), wait for external project/RBAC modules
    ...(!Use_APIM_Project && projectModuleEnabled ? [projectV21] : [])
    ...(!Use_APIM_Project && projectModuleEnabled ? [assignCognitiveServicesRoles] : [])
    ...(!Use_APIM_Project && enableAISearch ? [rbacAISearchForAIFv21] : [])
    ...(!Use_APIM_Project ? [rbacAIStorageAccountsForAIFv21] : [])
    ...(!Use_APIM_Project ? [rbacProjectKeyVaultForAIFoundry] : [])
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// ============================================================================
// AI FOUNDRY ACCOUNT DIAGNOSTIC SETTINGS
// ============================================================================
module aiFoundryAccountDiagnostics '../modules/diagnostics/cognitiveServicesDiagnostics.bicep' = if(enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2-Diagnostics_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cognitiveServiceName: aifV2Name
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    // Wait for AI Foundry account to be created in any scenario - match exact deployment conditions
    ...(Use_APIM_Project && foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && !aiFoundryV2Exists ? [aiFoundry2025NoAvmV22AccountOnly] : [])
    ...(Use_APIM_Project && !foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvmV22] : [])
    ...(!Use_APIM_Project && !foundryV22AccountOnly && !deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvm] : [])
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [])
  ]
}

#disable-next-line BCP318
var projectPrincipal = (projectModuleEnabled && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly) && !foundryV22AccountOnly) ? projectV21.outputs.projectPrincipalId : ''
#disable-next-line BCP318
var projectWorkspaceId = (projectModuleEnabled && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry || !foundryV22AccountOnly) && !foundryV22AccountOnly) ? projectV21.outputs.projectWorkspaceId : ''

// Function to assign roles to users and service principals for a cognitive services account
// Only executes in scenario 2b (non-APIM), as scenario 2a handles RBAC internally
@description('Function to assign roles to users and service principals for a cognitive services account')
module assignCognitiveServicesRoles '../modules/csFoundry/aiFoundry2025rbac.bicep' = if(!Use_APIM_Project && projectModuleEnabled && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  name: '07-AifV21_UserRBAC-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    projectPrincipalId: projectPrincipal
    cognitiveServicesAccountName: aiFoundryAccountNameOutput
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    useAdGroups: useAdGroups
  }
  dependsOn: [
    spAndMI2ArrayModule
    namingConvention
    // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
    projectV21
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

module rbacPreCaphost '../modules/csFoundry/aiFoundry2025caphostRbac1.bicep' = if(!Use_APIM_Project && enableCaphost && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && enableCosmosDB && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_RBACpreCH_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    projectPrincipalId: projectPrincipal
    cosmosAccountName: namingConvention.outputs.cosmosDBName
  }
  dependsOn: [
    projectV21
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// Sets RBAC roles: Search Service Contributor, Search Index Data Reader, Search Index Data Contributor on AI Search for the AI Foundry system-assigned identity
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search
// Assign RBAC in Task 2 (when foundryV22AccountOnly=false)
// Only executes in scenario 2b (non-APIM)
module rbacAISearchForAIFv21 '../modules/csFoundry/rbacAISearchForAIFv2.bicep' = if(!Use_APIM_Project && enableAISearch && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacAISearch-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    aiSearchName: aiSearchName
    aiFoundryAccountName: aifV2Name
    projectPrincipalId: projectModuleEnabled ? projectPrincipal : ''
    searchServiceContributorRoleId: searchServiceContributorRoleId
    searchIndexDataReaderRoleId: searchIndexDataReaderRoleId
    searchIndexDataContributorRoleId: searchIndexDataContributorRoleId
    azureAIDeveloperRoleId: azureAIDeveloperRoleId
  }
  dependsOn: [
    // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
    namingConvention
    ...(projectModuleEnabled ? [projectV21] : [])
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// Sets RBAC roles: Storage Blob Data Contributor, Storage File Data Privileged Contributor, Storage Queue Data Contributor on Azure Storage accounts for the AI Foundry system-assigned identity
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var storageFileDataSMBPrivilegedContributorRoleId = '0c867c2a-1d8c-454a-a3db-ab2ea1bdc8bb'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
// Assign RBAC in Task 2 (when foundryV22AccountOnly=false)
// Only executes in scenario 2b (non-APIM)
module rbacAIStorageAccountsForAIFv21 '../modules/csFoundry/rbacAIStorageAccountsForAIFv2.bicep'= if(!Use_APIM_Project && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacStorage-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiFoundryAccountName: aifV2Name
    projectPrincipalId: projectModuleEnabled ? projectPrincipal : ''
    storageBlobDataContributorRoleId: storageBlobDataContributorRoleId
    storageFileDataPrivilegedContributorRoleId: storageFileDataPrivilegedContributorRoleId
    storageFileDataSMBPrivilegedContributorRoleId: storageFileDataSMBPrivilegedContributorRoleId
    storageQueueDataContributorRoleId: storageQueueDataContributorRoleId
  }
  dependsOn: [
    // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
    namingConvention
    ...(projectModuleEnabled ? [projectV21] : [])
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// This module creates the capability host for the project and account
// Only executes in scenario 2b (non-APIM)
module addProjectCapabilityHost '../modules/csFoundry/aiFoundry2025caphost.bicep' = if(!Use_APIM_Project && enableCaphost && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && enableCosmosDB && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_PrjCapHost_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    accountName: aifV2Name
    projectName: aifV2ProjectName
    #disable-next-line BCP318
    cosmosDBConnection: namingConvention.outputs.cosmosDBName
    #disable-next-line BCP318
    azureStorageConnection: namingConvention.outputs.storageAccount1001Name
    #disable-next-line BCP318
    aiSearchConnection: aiSearchName
    projectCapHostName: projectCapHostName
  }
  dependsOn: [
    rbacPreCaphost
    projectV21  // CRITICAL: Must wait for project and all connections to be fully created
    rbacAISearchForAIFv21
    rbacAIStorageAccountsForAIFv21
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

module formatProjectWorkspaceId '../modules/formatWorkspaceId2Guid.bicep' = if(!Use_APIM_Project && enableCaphost && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && enableCosmosDB && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_PrjWID_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    projectWorkspaceId: projectWorkspaceId
  }
  dependsOn: [
    addProjectCapabilityHost
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// START CAPHOST RBAC: Some RBAC for COSMOS & STORAGE must be assigned AFTER the CAPABILITY HOST is created
// - The Storage Blob Data Owner role must be assigned after.
// - The Cosmos Built-In Data Contributor role must be assigned after.
module rbacPostCaphost '../modules/csFoundry/aiFoundry2025caphostRbac2.bicep' = if(!Use_APIM_Project && enableCaphost && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && enableCosmosDB && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  name: take('09-AifV21_RBACpostCH_${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    projectPrincipalId: projectPrincipal
    storageName: storageAccount1001Name
    #disable-next-line BCP318
    projectWorkspaceId: formatProjectWorkspaceId.outputs.projectWorkspaceIdGuid
    cosmosAccountName: namingConvention.outputs.cosmosDBName
  }
  dependsOn: [
    addProjectCapabilityHost
    formatProjectWorkspaceId
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}
// END CAPHOST RBAC

// CRITICAL: Add Key Vault RBAC for Agent playground functionality
// Assign RBAC in Task 2 (when foundryV22AccountOnly=false)
// Only executes in scenario 2b (non-APIM)
module rbacKeyVaultForAgents '../modules/csFoundry/rbacKeyVaultForAgents.bicep' = if(!Use_APIM_Project && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacKeyVault-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultName: namingConvention.outputs.keyvaultName
    aiFoundryAccountName: aifV2Name
    projectPrincipalId: projectModuleEnabled ? projectPrincipal : ''
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId
    keyVaultContributorRoleId: keyVaultContributorRoleId
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
  }
  dependsOn: [
    // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
    namingConvention
    ...(projectModuleEnabled ? [projectV21] : [])
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// ADDITIONAL: Assign specific Key Vault roles to the AI Foundry managed identity for the project Key Vault 
// Assign RBAC in Task 2 (when foundryV22AccountOnly=false)
// Only executes in scenario 2b (non-APIM)
module rbacProjectKeyVaultForAIFoundry '../modules/kvRbacAIFoundryMI.bicep' = if(!Use_APIM_Project && enableAIFoundry && !foundryV22AccountOnly && !aiFoundryV2ProjectExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacPrjKV-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultName: namingConvention.outputs.keyvaultName
    aiFoundryAccountName: aifV2Name
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId
  }
  dependsOn: [
    // Scenario 2b: depends on aiFoundry2025NoAvm or deployAvmFoundry path
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [aiFoundry2025NoAvm])
    namingConvention
    ...(requiresAcaDelegation ? [subnetDelegationAca] : [])
  ]
}

// Simplified: Determine which module was deployed based on scenario
// Scenario 1: foundryV22AccountOnly=true -> aiFoundry2025NoAvmV22AccountOnly
// Scenario 2a: Use_APIM_Project=true && foundryV22AccountOnly=false -> aiFoundry2025NoAvmV22
// Scenario 2b: Use_APIM_Project=false && foundryV22AccountOnly=false -> aiFoundry2025NoAvm
// AVM is separate path (deployAvmFoundry)

#disable-next-line BCP318
var aiFoundryAccountNameOutput = foundryV22AccountOnly
  ? aiFoundry2025NoAvmV22AccountOnly!.outputs.aiAccountName
  : (Use_APIM_Project
      ? (aiFoundryV2Exists ? aiAccountExistingFromFirstDeployment!.name : aiFoundry2025NoAvmV22!.outputs.aiAccountName)
      : (deployAvmFoundry
          ? aiFoundry2025Avm!.outputs.aiServicesName
          : aiFoundry2025NoAvm!.outputs.name))

#disable-next-line BCP318
var aiFoundryResourceIdOutput = foundryV22AccountOnly
  ? aiFoundry2025NoAvmV22AccountOnly!.outputs.aiAccountId
  : (Use_APIM_Project
      ? (aiFoundryV2Exists ? aiAccountExistingFromFirstDeployment!.id : aiFoundry2025NoAvmV22!.outputs.aiAccountId)
      : (deployAvmFoundry
          ? resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.CognitiveServices/accounts', aiFoundry2025Avm!.outputs.aiServicesName)
          : aiFoundry2025NoAvm!.outputs.resourceId))

// ============== AI FOUNDRY HUB ==============

// ==== Shared private link Azure AI Search to foundry
var enableSharedLinkDeployment = enableAISearchSharedPrivateLink && enableAISearch && enableAIFoundry && !foundryV22AccountOnly

module aiSearchSharedPrivateLink '../modules/aiSearchSharedPrivateLinkFoundry.bicep' = if (enableSharedLinkDeployment) {
  name: take('09-aiSearchSPL-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: aiSearchName
    aiFoundryResourceId: aiFoundryResourceIdOutput
    location: location
  }
  dependsOn: [
    // Primary AI Foundry deployment based on scenario - match exact deployment conditions
    ...(deployAvmFoundry ? [aiFoundry2025Avm] : [])
    ...(Use_APIM_Project && !foundryV22AccountOnly && enableAIFoundry && !useAVMFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvmV22] : [])
    ...(!Use_APIM_Project && !foundryV22AccountOnly && !deployAvmFoundry && enableAIFoundry && (!aiFoundryV2Exists || updateAIFoundry) ? [aiFoundry2025NoAvm] : [])
    // Scenario 2b only: wait for RBAC
    ...(!Use_APIM_Project && enableAISearch ? [rbacAISearchForAIFv21] : [])
    // Wait for private endpoints if they are being deployed
    ...(!enablePublicAccessWithPerimeter && shouldDeployFoundryPrivateEndpoints ? [aiFoundryPrivateEndpoints] : [])
  ]
}
// Approve the shared private link request on the Azure AI Foundry account after deployment.

	// Enables Defender for AI, if not enabled already on Subscription level
module defenderForAIAccount '../modules/security/defender-for-cs.bicep' = if(!enableDefenderforAISubLevel && enableDefenderforAIResourceLevel) {
	name: take('defender-for-ai-${deploymentProjSpecificUniqueSuffix}', 64)
	scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
	params: {
		aiAccountName: aifV2Name
		profileName: 'default'
	}
	dependsOn: [
		rbacKeyVaultForAgents
	]
}

// ============== OUTPUTS ==============

@description('AI Models configuration for debugging')
output aiModelsConfiguration array = aiModels

@description('AI Foundry V2 deployment status')
output aiFoundryV2Deployed bool = enableAIFoundry

@description('AI Foundry V2 name')
output aiFoundryV2Name string = enableAIFoundry ? aiFoundryAccountNameOutput : ''

@description('AI Foundry V2 resource ID')
output aiFoundryV2ResourceId string = enableAIFoundry ? aiFoundryResourceIdOutput : ''

@description('AI Foundry Project deployment status')
output aiFoundryProjectDeployed bool = foundryV22AccountOnly
  ? false
  : (Use_APIM_Project
      ? (aiFoundryV2Exists ? false : aiFoundry2025NoAvmV22!.outputs.aiFoundryProjectDeployed)
      : (enableAIFoundry && projectModuleEnabled))

@description('AI Models deployed count')
output aiModelsDeployed int = length(aiModels)

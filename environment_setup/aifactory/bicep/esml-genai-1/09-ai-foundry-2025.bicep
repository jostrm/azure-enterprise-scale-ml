targetScope = 'subscription'

// ================================================================
// AI FOUNDRY 2025 DEPLOYMENT - Phase 9 Implementation
// This file deploys the latest AI Foundry 2025 platform including:
// - AI Foundry Hub with advanced capabilities
// - AI Foundry Projects
// - Model deployments (GPT, embedding models)
// - Private endpoints and networking
// - RBAC and security configurations
// ================================================================

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

param updateAIFoundryV21 bool = false
param addAIFoundryV21 bool = false
param containerAppsEnvExists bool = false
param enableAIFactoryCreatedDefaultProjectForAIFv2 bool = true
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

// Enable flags
@description('Enable AI Foundry 2 features')
param enableAIFoundryV2 bool = false
param enableAIFoundryV21 bool = false
param aiFoundryV2Exists bool = false

@description('Enable Capability host for AI Foundry - BYO network and resources for thread, vector, storage')
param enableCaphost bool = true
@description('Enable AI Search integration')
param enableAISearch bool = true

@description('Enable Cosmos DB integration')
param serviceSettingDeployCosmosDB bool = false

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

// Networking subnet IDs
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

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
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'

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

// ============== VARIABLES ==============

// Note: Ensure useAdGroups is set correctly based on your principal types
// If you're using Azure AD Groups, set useAdGroups = true
// If you're using individual users, set useAdGroups = false
// Mismatch will cause: UnmatchedPrincipalType error

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
  //action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]

// Get the subnet resource ID for the common subnet used for private endpoints
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
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
  }
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

// AI Foundry V2 specific names (12)
// Ensure domain name compliance: lowercase, no special chars, proper length
var cleanRandomValue = !empty(randomValue) ? toLower(replace(replace(randomValue, '-', ''), '_', '')) : randomSalt
var aifRandom = take('aif${cleanRandomValue}',12)
var aifpRandom = take('aifp${cleanRandomValue}',12)

var aif2SubdomainName = cleanRandomValue
var aifV2Name = addAIFoundryV21? aifRandom: namingConvention.outputs.aifV2Name // aif2qoygyc7e
var aifV2ProjectName = addAIFoundryV21? aifpRandom: namingConvention.outputs.aifV2PrjName // aif2pqoygyc7
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var projectCapHost= '${aifV2Name}caphost'

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

var networkAcls = shouldCreateNetworkAcls ? {
  defaultAction: enablePublicGenAIAccess && empty(processedIpRules_remove32) ? 'Allow' : 'Deny'
  virtualNetworkRules: [
    {
      id: genaiSubnetId
      ignoreMissingVnetServiceEndpoint: false
    }
  ]
  ipRules: empty(processedIpRules_remove32) ? [] : processedIpRules_remove32
} : null

var networkAclsEmpty = {
  defaultAction: 'Deny'
  virtualNetworkRules: []
  ipRules: []
}

var networkAclsObject = networkAcls

/*
module aiFoundry2025 '../modules/csFoundry/aiFoundry2025.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV2Name
    defaultProjectName: enableAIFactoryCreatedDefaultProjectForAIFv2? null: '${aifV2ProjectName}-d2'
    allowProjectManagement: true
    location:location
    // Provided subnet must be of the proper address space. Please provide a subnet which has address space in the range of 172 or 192
    agentSubnetResourceId: acaSubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    enablePublicGenAIAccess: enablePublicGenAIAccess
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    networkAcls: shouldCreateNetworkAcls ? networkAclsObject : networkAclsEmpty
    enableTelemetry:false
    tags: tagsProject
    aiModelDeployments: [
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
    privateEndpointSubnetResourceId: commonSubnetResourceId
    privateDnsZoneResourceIds:aiFoundryZones
    //roleAssignments: allRoleAssignments
    //lock:
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}
*/

/*
module project '../modules/csFoundry/aiFoundry2025project.bicep' = if(enableAIFoundryV2 && enableAIFactoryCreatedDefaultProjectForAIFv2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2_Prj_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cosmosDBname: serviceSettingDeployCosmosDB? namingConvention.outputs.cosmosDBName : ''
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    storageName2: namingConvention.outputs.storageAccount2001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundry2025.outputs.name
    aiSearchName: enableAISearch ? namingConvention.outputs.safeNameAISearch : ''
    }
    dependsOn: [
      existingTargetRG
      aiFoundry2025
    ]
}
*/

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

// Get AI Search principal ID conditionally
module getAISearchInfo '../modules/get-ai-search-info.bicep' = if (enableAISearch) {
  name: take('09-getAISearch-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: namingConvention.outputs.safeNameAISearch
  }
}

var aiSearchPrincipalId = enableAISearch ? getAISearchInfo!.outputs.principalId : ''

// Create role assignments module to build the dynamic array
module roleAssignmentsBuilder '../modules/csFoundry/buildRoleAssignments.bicep' = if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
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
  ]
}

// Subnet delegation for Container Apps
var acaSubnetName = namingConvention.outputs.acaSubnetName
module subnetDelegationAca '../modules/subnetDelegation.bicep' = if ((!containerAppsEnvExists) && (enableAIFoundryV21 && !aiFoundryV2Exists && !disableAgentNetworkInjection)) {
  name: take('09-snetDelegACA${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetNameFull
    subnetName: acaSubnetName
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

var fqdn = [
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
  
  // AI Search endpoint
  '${namingConvention.outputs.safeNameAISearch}.search.windows.net'
  
  // Key Vault endpoint
  '${namingConvention.outputs.keyvaultName}${environment().suffixes.keyvaultDns}'
  
  // Cosmos DB endpoint (if enabled)
  serviceSettingDeployCosmosDB ? '${namingConvention.outputs.cosmosDBName}.documents.azure.com' : ''
  
  // AI Services endpoint
  '${aifV2Name}.cognitiveservices.azure.com'
  '${aifV2Name}.openai.azure.com'
]

// AI Foundry V2.1 - AI factory (Alternative Implementation, customer high regulatory reqs enforcement on top of WAF)
module aiFoundry2025NoAvm '../modules/csFoundry/aiFoundry2025AvmOff.bicep' = if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV2-NoAvm_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV2Name
    kind: 'AIServices'
    sku: 'S0'
    location: location
    enableTelemetry: false
    tags: tagsProject
    customSubDomainName: aif2SubdomainName // aifV2Name // optional
    //allowedFqdnList: fqdn
    restrictOutboundNetworkAccess: false // Agents need outbound access for various services such as AI Search, Key Vault, Storage, etc.
    publicNetworkAccess: enablePublicAccessWithPerimeter || enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet || !empty(processedIpRules_remove32) ? 'Enabled' : 'Disabled'
    agentSubnetResourceId: acaSubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    disableAgentNetworkInjection: disableAgentNetworkInjection
    allowProjectManagement: true
    defaultProjectName: enableAIFactoryCreatedDefaultProjectForAIFv2 ? aifV2ProjectName : '${aifV2ProjectName}def'
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
    deployments: [
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
    privateEndpointSubnetRID: genaiSubnetId
    privateLinksDnsZones: privateLinksDnsZones
    createPrivateEndpointsAIFactoryWay: true
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
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
    ...(!disableAgentNetworkInjection && !containerAppsEnvExists ? [subnetDelegationAca] : [])
  ]
}

// Add the new FDP cognitive services module
module projectV21 '../modules/csFoundry/aiFoundry2025project.bicep' = if((enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_Prj_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    storageName2: namingConvention.outputs.storageAccount2001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundry2025NoAvm.outputs.name
    aiSearchName: enableAISearch ? namingConvention.outputs.safeNameAISearch : ''
    cosmosDBname: serviceSettingDeployCosmosDB? namingConvention.outputs.cosmosDBName : ''
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    }
    dependsOn: [
      existingTargetRG
      aiFoundry2025NoAvm
    ]
}

// AI Foundry Private Endpoints - deployed after main service
module aiFoundryPrivateEndpoints '../modules/csFoundry/aiFoundry2025pend.bicep' = if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21-PrivateEndpoints_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    cognitiveServiceName: aifV2Name
    #disable-next-line BCP318
    cognitiveServiceId: aiFoundry2025NoAvm.outputs.resourceId
    location: location
    tags: tagsProject
    privateEndpointSubnetRID: genaiSubnetId
    privateLinksDnsZones: privateLinksDnsZones
    createPrivateEndpointsAIFactoryWay: true
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    aiFoundry2025NoAvm
    existingTargetRG
    projectV21
    assignCognitiveServicesRoles // Add... some extra dependencies, to not having AI Foundry "Account in state accepted" errror
    rbacAISearchForAIFv21 // Add..
    rbacAIStorageAccountsForAIFv21 // Add
    rbacProjectKeyVaultForAIFoundry // Add
  ]
}

#disable-next-line BCP318
var projectPrincipal = projectV21.outputs.projectPrincipalId
#disable-next-line BCP318
var projectWorkspaceId = projectV21.outputs.projectWorkspaceId

// Function to assign roles to users and service principals for a cognitive services account
@description('Function to assign roles to users and service principals for a cognitive services account')
module assignCognitiveServicesRoles '../modules/csFoundry/aiFoundry2025rbac.bicep' = if((enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2) && (!aiFoundryV2Exists)) {
  name: '07-AifV21_UserRBAC-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    projectPrincipalId: projectPrincipal
    cognitiveServicesAccountName: aifV2Name
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    useAdGroups: useAdGroups
  }
  dependsOn: [
    spAndMI2ArrayModule
    namingConvention
    aiFoundry2025NoAvm
    projectV21
  ]
}

module rbacPreCaphost '../modules/csFoundry/aiFoundry2025caphostRbac1.bicep' = if((enableCaphost && enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && serviceSettingDeployCosmosDB) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_RBACpreCH_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    projectPrincipalId: projectPrincipal
    cosmosAccountName: namingConvention.outputs.cosmosDBName
  }
  dependsOn: [projectV21]
}

// This module creates the capability host for the project and account
module addProjectCapabilityHost '../modules/csFoundry/aiFoundry2025caphost.bicep' = if((enableCaphost && enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && serviceSettingDeployCosmosDB) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
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
    aiSearchConnection: namingConvention.outputs.safeNameAISearch
    projectCapHost: projectCapHost
  }
  dependsOn: [
    rbacPreCaphost
  ]
}

module formatProjectWorkspaceId '../modules/formatWorkspaceId2Guid.bicep' = if((enableCaphost && enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && serviceSettingDeployCosmosDB) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-AifV21_PrjWID_${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    projectWorkspaceId: projectWorkspaceId
  }
  dependsOn: [
    addProjectCapabilityHost
  ]
}

// START CAPHOST RBAC: Some RBAC for COSMOS & STORAGE must be assigned AFTER the CAPABILITY HOST is created
// - The Storage Blob Data Owner role must be assigned after.
// - The Cosmos Built-In Data Contributor role must be assigned after.
module rbacPostCaphost '../modules/csFoundry/aiFoundry2025caphostRbac2.bicep' = if((enableCaphost && enableAIFoundryV21 && enableAIFactoryCreatedDefaultProjectForAIFv2 && enableAISearch && serviceSettingDeployCosmosDB) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
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
  ]
}
// END CAPHOST RBAC

// Sets RBAC roles: Search Service Contributor, Search Index Data Reader,Search Index Data Contributor on AI Search, for aiFoundry2025NoAvm.systemAssignedMIPrincipalId
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search
module rbacAISearchForAIFv21 '../modules/csFoundry/rbacAISearchForAIFv2.bicep' = if((enableAISearch && enableAIFoundryV21) && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacAISearch-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    aiSearchName: namingConvention.outputs.safeNameAISearch
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    projectPrincipalId: projectPrincipal
    searchServiceContributorRoleId: searchServiceContributorRoleId
    searchIndexDataReaderRoleId: searchIndexDataReaderRoleId
    searchIndexDataContributorRoleId: searchIndexDataContributorRoleId
    azureAIDeveloperRoleId: azureAIDeveloperRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}

// Sets RBAC roles: Storage Blob Data Contributor, Storage File Data Privileged Contributor, Storage Queue Data Contributor on Azure Storage accounts, for aiFoundry2025NoAvm.systemAssignedMIPrincipalId
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
module rbacAIStorageAccountsForAIFv21 '../modules/csFoundry/rbacAIStorageAccountsForAIFv2.bicep'= if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacStorage-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: namingConvention.outputs.storageAccount2001Name
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    projectPrincipalId: projectPrincipal
    storageBlobDataContributorRoleId: storageBlobDataContributorRoleId
    storageFileDataPrivilegedContributorRoleId: storageFileDataPrivilegedContributorRoleId
    storageQueueDataContributorRoleId: storageQueueDataContributorRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}

// CRITICAL: Add Key Vault RBAC for Agent playground functionality
module rbacKeyVaultForAgents '../modules/csFoundry/rbacKeyVaultForAgents.bicep' = if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacKeyVault-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultName: namingConvention.outputs.keyvaultName
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    projectPrincipalId: projectPrincipal
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId
    keyVaultContributorRoleId: keyVaultContributorRoleId
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}

// ADDITIONAL: Assign specific Key Vault roles to AI Foundry MI for project Key Vault 
module rbacProjectKeyVaultForAIFoundry '../modules/kvRbacAIFoundryMI.bicep' = if(enableAIFoundryV21 && (!aiFoundryV2Exists || updateAIFoundryV21)) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('09-rbacPrjKV-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    keyVaultName: namingConvention.outputs.keyvaultName
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    keyVaultSecretsOfficerRoleId: keyVaultSecretsOfficerRoleId
    keyVaultSecretsUserRoleId: keyVaultSecretsUserRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}

// ============== OUTPUTS ==============

@description('AI Models configuration for debugging')
output aiModelsConfiguration array = aiModels

@description('AI Foundry V2 deployment status')
output aiFoundryV2Deployed bool = enableAIFoundryV21

@description('AI Foundry V2 name')
output aiFoundryV2Name string = enableAIFoundryV21 ? aiFoundry2025NoAvm!.outputs.name : ''

@description('AI Foundry V2 resource ID')
output aiFoundryV2ResourceId string = enableAIFoundryV21 ? aiFoundry2025NoAvm!.outputs.resourceId : ''

@description('AI Foundry Project deployment status')
output aiFoundryProjectDeployed bool = enableAIFoundryV21

@description('AI Models deployed count')
output aiModelsDeployed int = length(aiModels)

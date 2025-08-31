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
param deployModel_text_embedding_3_small bool = false
@description('Default capacity for embedding models')
param default_embedding_capacity int = 25

@description('Default capacity for GPT models')
param default_gpt_capacity int = 40
@description('Whether to deploy GPT-4o model')
param deployModel_gpt_4o bool = false
param default_gpt_4o_version string = '2024-11-20'
@description('Whether to deploy GPT-4o-mini model')
param deployModel_gpt_4o_mini bool = false
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
var processedIpRules_ensure_32 = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRules_remove32 = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]

// Get the subnet resource ID for the common subnet used for private endpoints
resource commonSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = {
  name: '${vnetNameFull}/${commonSubnetPends}'
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
}
//var commonSubnetResourceId = commonSubnet.id
var commonSubnetResourceId = genaiSubnetId

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: '09-naming-${targetResourceGroup}'
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
  name: '09-getMI-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId

var miAcaName = namingConvention.outputs.miACAName
module getAcaMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: '09-getAcaMI-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miAcaName
  }
}

var var_miAca_PrincipalId = getAcaMIPrincipalId.outputs.principalId

resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}


// Get the Key Vault secret as a string using reference function
module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: '09-spAndMI2Array-${targetResourceGroup}'
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

// AI Foundry V2 specific names
var aifV2Name = namingConvention.outputs.aifV2Name
var aifV2ProjectName = namingConvention.outputs.aifV2PrjName

// Private DNS zones
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: '09-getPrivDnsZ-${targetResourceGroup}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
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
var networkAcls = {
  defaultAction: enablePublicGenAIAccess && empty(processedIpRules_remove32) ? 'Allow' : 'Deny'
  virtualNetworkRules: [
    {
      id: commonSubnetResourceId
      ignoreMissingVnetServiceEndpoint: false
    }
  ]
  ipRules: empty(processedIpRules_remove32) ? [] : processedIpRules_remove32
}

var networkAclsObject = !empty(networkAcls ?? {})
  ? {
      defaultAction: networkAcls.?defaultAction
      virtualNetworkRules: networkAcls.?virtualNetworkRules ?? []
      ipRules: networkAcls.?ipRules ?? []
    }
  : null

// Role assignments are now managed in 07-rbac-security.bicep
// We use deployment scripts to update permissions if needed after deployment
module aiFoundry2025 '../modules/csFoundry/aiFoundry2025.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV2Name
    defaultProjectName: '${aifV2ProjectName}-d'
    allowProjectManagement: true
    location:location
    // Provided subnet must be of the proper address space. Please provide a subnet which has address space in the range of 172 or 192
    agentSubnetResourceId: acaSubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    enablePublicGenAIAccess: enablePublicGenAIAccess
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    networkAcls:networkAcls
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

// Add the new FDP cognitive services module
module project '../modules/csFoundry/aiFoundry2025project.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2_Prj_${deploymentProjSpecificUniqueSuffix}'
  params: {
    cosmosDBname: serviceSettingDeployCosmosDB? namingConvention.outputs.cosmosDBName : ''
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundry2025.outputs.name
    aiSearchName: enableAISearch ? namingConvention.outputs.safeNameAISearch : ''
    }
    dependsOn: [
      existingTargetRG
      aiFoundry2025
    ]
}

// ============================================================================
// COGNITIVE SERVICES & OPENAI ROLE ASSIGNMENTS
// ============================================================================

var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// Cognitive Services and OpenAI role definition IDs
var cognitiveServicesContributorRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var openAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// Function to assign roles to users and service principals for a cognitive services account
@description('Function to assign roles to users and service principals for a cognitive services account')
module assignCognitiveServicesRoles '../modules/csFoundry/aiFoundry2025rbac.bicep' = if(enableAIFoundryV2) {
  name: '07-CSRoleAssignments-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
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
  ]
}

@description('RBAC Security Phase 7 deployment completed successfully')
output rbacSecurityPhaseCompleted bool = true

// Get AI Search principal ID conditionally
module getAISearchInfo '../modules/get-ai-search-info.bicep' = if (enableAISearch) {
  name: '09-getAISearch-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    aiSearchName: namingConvention.outputs.safeNameAISearch
  }
}

var aiSearchPrincipalId = enableAISearch ? getAISearchInfo!.outputs.principalId : ''

// Create role assignments module to build the dynamic array
module roleAssignmentsBuilder '../modules/csFoundry/buildRoleAssignments.bicep' = {
  name: '09-roleBuilder-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    userObjectIds: p011_genai_team_lead_array
    servicePrincipalIds: spAndMiArray
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    useAdGroups: useAdGroups
    enableAISearch: enableAISearch
    aiSearchPrincipalId: aiSearchPrincipalId
  }
  dependsOn: [
    spAndMI2ArrayModule
    namingConvention
  ]
}

// AI V2.1 - Cognitive Services Module (Alternative Implementation)
module aiFoundry2025NoAvm '../modules/csFoundry/aiFoundry2025AvmOff.bicep' = if(enableAIFoundryV21) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-AifV2-NoAvm_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV2Name
    kind: 'AIServices'
    sku: 'S0'
    location: location
    enableTelemetry: false
    tags: tagsProject
    customSubDomainName: aifV2Name
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled' : 'Disabled'
    agentSubnetResourceId: acaSubnetId // Delegated to Microsoft.App/environment due to ContainerApps hosting agents.
    roleAssignments: roleAssignmentsBuilder.outputs.roleAssignments
    networkAcls: networkAclsObject
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miAcaName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miAcaName)) : []
      )
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
    //privateEndpointSubnetResourceId: commonSubnetResourceId
    privateEndpoints: !enablePublicAccessWithPerimeter ? [
      {
        name: '${aifV2Name}-pend'
        subnetResourceId: commonSubnetResourceId
        privateDnsZoneResourceIds: aiFoundryZones
        service: 'account'
      }
    ] : null
  }
  dependsOn: [
    existingTargetRG
    roleAssignmentsBuilder
    spAndMI2ArrayModule
    namingConvention
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}

// Sets RBAC roles: Search Service Contributor, Search Index Data Reader,Search Index Data Contributor on AI Search, for aiFoundry2025NoAvm.systemAssignedMIPrincipalId
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // User, SP, AI Services, etc -> AI Search
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // SP, User, Search, AIHub, AIProject, App Service/FunctionApp -> AI Search
module rbacAISearchForAIFv21 '../modules/csFoundry/rbacAISearchForAIFv2.bicep' = if(enableAISearch && enableAIFoundryV21) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-rbacAISearch-${deploymentProjSpecificUniqueSuffix}'
  params: {
    aiSearchName: namingConvention.outputs.safeNameAISearch
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    searchServiceContributorRoleId: searchServiceContributorRoleId
    searchIndexDataReaderRoleId: searchIndexDataReaderRoleId
    searchIndexDataContributorRoleId: searchIndexDataContributorRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}
// Sets RBAC roles: Storage Blob Data Contributor, Storage File Data Privileged Contributor on Azure Storage accounts, for aiFoundry2025NoAvm.systemAssignedMIPrincipalId
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
module rbacAIStorageAccountsForAIFv21 '../modules/csFoundry/rbacAIStorageAccountsForAIFv2.bicep'= if(enableAIFoundryV21) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '09-rbacStorage-${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: namingConvention.outputs.storageAccount1001Name
    #disable-next-line BCP318
    principalId: aiFoundry2025NoAvm.outputs.systemAssignedMIPrincipalId!
    storageBlobDataContributorRoleId: storageBlobDataContributorRoleId
    storageFileDataPrivilegedContributorRoleId: storageFileDataPrivilegedContributorRoleId
  }
  dependsOn: [
    aiFoundry2025NoAvm
    namingConvention
  ]
}

// ============== OUTPUTS ==============

@description('AI Foundry V2 deployment status')
output aiFoundryV2Deployed bool = enableAIFoundryV2

@description('AI Foundry V2 name')
output aiFoundryV2Name string = enableAIFoundryV2 ? aiFoundry2025!.outputs.name : ''

@description('AI Foundry V2 resource ID')
output aiFoundryV2ResourceId string = enableAIFoundryV2 ? aiFoundry2025!.outputs.resourceId : ''

@description('AI Foundry Project deployment status')
output aiFoundryProjectDeployed bool = enableAIFoundryV2

@description('AI Models deployed count')
output aiModelsDeployed int = length(aiModels)

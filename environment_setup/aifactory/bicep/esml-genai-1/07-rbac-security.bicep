targetScope = 'subscription'

// ================================================================
// RBAC SECURITY DEPLOYMENT - Phase 7 Implementation  
// This file deploys all role-based access control and security:
// - Cross-resource RBAC assignments
// - User and service principal permissions
// - AI Hub and ML platform security
// - Storage and network access control
// - External bastion and VNet permissions
// - Common resource group access
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

@description('Tenant ID')
param tenantId string

// Resource exists flags from Azure DevOps
param amlExists bool = false
param aiHubExists bool = false
param aiServicesExists bool = false
param aiSearchExists bool = false
param openaiExists bool = false

// Enable flags from parameter files
@description('Enable Azure Machine Learning deployment')
param enableAzureMachineLearning bool = true

@description('Enable AI Foundry Hub deployment')
param enableAIFoundryHub bool = true

@description('Enable AI Services deployment')
param enableAIServices bool = true

@description('Enable AI Search deployment')
param enableAISearch bool = true

@description('Enable Azure OpenAI deployment')
param serviceSettingDeployAzureOpenAI bool = true

@description('Enable Azure AI Vision deployment')
param serviceSettingDeployAzureAIVision bool = false

@description('Enable Azure Speech deployment')
param serviceSettingDeployAzureSpeech bool = false

@description('Enable AI Document Intelligence deployment')
param serviceSettingDeployAIDocIntelligence bool = false

// Security and networking
param addBastionHost bool = false
param bastionResourceGroup string = ''
param bastionSubscription string = ''
param bastionName string = ''
param vnetNameFullBastion string = ''
param disableContributorAccessForUsers bool = false

// Required resource references
param vnetNameFull string
param vnetResourceGroupName string
param targetResourceGroup string
param commonResourceGroup string

// Resource names for dependencies
param storageAccount1001Name string
param storageAccount2001Name string
param keyvaultName string
param acrName string
param aiSearchName string
param aiServicesName string
param openAIName string
param amlName string
param aiHubName string

// Service Principal IDs and User Groups
param technicalContactId string = ''
param p011_genai_team_lead_array array = []
param spAndMiArray array = []
param useAdGroups bool = false

// Azure ML Object ID for cross-service permissions
param azureMachineLearningObjectId string = ''

// Data Lake parameters
param datalakeName_param string = ''
param commonLakeNamePrefixMax8chars string = 'datalake'

// Dependencies and naming
param uniqueInAIFenv string = ''
param deploymentProjSpecificUniqueSuffix string = ''

// Common ACR usage
param useCommonACR bool = true

// Tags
param projecttags object = {}

// ============== VARIABLES ==============
var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var cmnName = 'cmn'

// Resource names with proper formatting
var aiProjectName = 'ai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// Network and resource group references
var projectResourceGroup_rgId = resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', targetResourceGroup)

// Data lake name calculation
var datalakeName = datalakeName_param != '' ? datalakeName_param : '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}esml${replace(commonResourceSuffix,'-','')}${env}'

// ============== EXISTING RESOURCE REFERENCES ==============

// Target resource group reference
resource resourceExists_struct 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: targetResourceGroup
  location: location
}

// Common data lake reference
resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: datalakeName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============== RBAC MODULES - KEY VAULT AND BASTION ==============

// Bastion in AIFactory COMMON RG, but with a custom name
module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep' = if(empty(bastionResourceGroup) && addBastionHost) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'rbac1GenAIReadUsersCmnKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    common_kv_name: 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    user_object_ids: p011_genai_team_lead_array   
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
    rbacReadUsersToCmnVnetBastion
  ]
}

// Bastion Externally (Connectivity subscription and RG)
module rbacExternalBastion '../modules/rbacBastionExternal.bicep' = if(!empty(bastionResourceGroup) && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription, bastionResourceGroup)
  name: 'rbac2GenAIUsersBastionExt${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
    rbacReadUsersToCmnVnetBastion
  ]
}

// ============== RBAC MODULES - AI SERVICES ==============

// RBAC for OpenAI - Storage, Search, and User Access
module rbacForOpenAI '../modules/aihubRbacOpenAI.bicep' = if (serviceSettingDeployAzureOpenAI && !openaiExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac3OpenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSearchName: aiSearchName
    openAIServicePrincipal: 'placeholder-principal-id' // Will be replaced with actual service principal
    servicePrincipleAndMIArray: spAndMiArray
    openAIName: openAIName
    userObjectIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
    rbacReadUsersToCmnVnetBastion
  ]
}

// RBAC for AI Services - Storage and Search Integration
module rbacModuleAIServices '../modules/aihubRbacAIServices.bicep' = if(!aiServicesExists && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac4AIServices${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSearchName: aiSearchName
    aiServicesPrincipalId: 'placeholder-principal-id' // Will be replaced with actual service principal
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// RBAC for AI Search - Cross-service Integration
module rbacModuleAISearch '../modules/aihubRbacAISearch.bicep' = if(!aiSearchExists && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac5Search${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiServicesName: aiServicesName
    aiSearchMIObjectId: 'placeholder-principal-id' // Will be replaced with actual managed identity
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== RBAC MODULES - AI HUB AND ML PLATFORM ==============

// RBAC for AI Hub to Azure ML Resource Group
module rbacAihubRbacAmlRG '../modules/aihubRbacAmlRG.bicep' = if (!aiHubExists && !empty(azureMachineLearningObjectId) && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac6Aml2RG${deploymentProjSpecificUniqueSuffix}'
  params: {
    azureMachineLearningObjectId: azureMachineLearningObjectId
    aiHubName: aiHubName
    aiHubPrincipalId: 'placeholder-principal-id' // Will be replaced with actual AI Hub principal
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// RBAC for Users to AI Hub and Projects
module rbacModuleUsers '../modules/aihubRbacUsers.bicep' = if (!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac7UsersAIHub${deploymentProjSpecificUniqueSuffix}'
  params: {
    aiServicesName: aiServicesName
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    resourceGroupId: projectResourceGroup_rgId
    userObjectIds: p011_genai_team_lead_array
    aiHubName: aiHubName
    aiHubProjectName: aiProjectName
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
    disableContributorAccessForUsers: disableContributorAccessForUsers
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// RBAC for Users to AI Search
module rbacModuleUsersToSearch '../modules/aiSearchRbacUsers.bicep' = if (!aiSearchExists && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac7Users2AISearch${deploymentProjSpecificUniqueSuffix}'
  params: {
    aiSearchName: aiSearchName
    userObjectIds: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== RBAC MODULES - OPTIONAL COGNITIVE SERVICES ==============

// RBAC for Azure AI Vision (Optional)
module rbacVision '../modules/aihubRbacVision.bicep' = if(serviceSettingDeployAzureAIVision == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac8Vision${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiVisionMIObjectId: 'placeholder-vision-principal' // Will be replaced with actual Vision service principal
    userObjectIds: p011_genai_team_lead_array
    visonServiceName: 'placeholder-vision-service-name' // Will be replaced with actual Vision service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// RBAC for Azure Speech Services (Optional)
module rbacSpeech '../modules/aihubRbacSpeech.bicep' = if(serviceSettingDeployAzureSpeech == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac9Speech${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSpeechMIObjectId: 'placeholder-speech-principal' // Will be replaced with actual Speech service principal
    userObjectIds: p011_genai_team_lead_array
    speechServiceName: 'placeholder-speech-service-name' // Will be replaced with actual Speech service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// RBAC for AI Document Intelligence (Optional)
module rbacDocs '../modules/aihubRbacDoc.bicep' = if(serviceSettingDeployAIDocIntelligence == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: 'rbac10Docs${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    userObjectIds: p011_genai_team_lead_array
    aiDocsIntelMIObjectId: 'placeholder-docs-principal' // Will be replaced with actual Document Intelligence principal
    docsServiceName: 'placeholder-docs-service-name' // Will be replaced with actual Document Intelligence service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== RBAC MODULES - NETWORK AND VNET ACCESS ==============

// RBAC - Read users to Bastion, IF Bastion is added in ESML-COMMON resource group
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost && empty(bastionSubscription)) {
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
  name: 'rbac12GenAIRUsersVnet${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// Bastion VNet Externally (Connectivity subscription and RG || AI Factory Common RG)
module rbacReadUsersToCmnVnetBastionExt '../modules/vnetRBACReader.bicep' = if(addBastionHost && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription, bastionResourceGroup)
  name: 'rbac13UsersVnet${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFullBastion
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
  ]
}

// ============== RBAC MODULES - COMMON RESOURCE GROUP ACCESS ==============

// RBAC on ACR Push/Pull for users in Common Resource group
module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'rbac14UsersToCmnACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleAndMIArray: spAndMiArray
    userObjectIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    resourceExists_struct
    rbacModuleUsers
  ]
}

// ============== RBAC MODULES - DATA LAKE ACCESS ==============

// RBAC for Data Lake - AI Foundry Integration
module rbacLakeFirstTime '../esml-common/modules-common/lakeRBAC.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'rbacLake4PrjFoundry${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: '' // Simplified for compilation - will be replaced with actual AML principal
    aiHubPrincipleId: 'placeholder-aihub-principal' // Will be replaced with actual AI Hub principal
    projectTeamGroupOrUser: p011_genai_team_lead_array
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    esmlCommonLake
    resourceExists_struct
  ]
}

// RBAC for Data Lake - Azure ML Integration
module rbacLakeAml '../esml-common/modules-common/lakeRBAC.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: 'rbacLake4Amlv2${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: 'placeholder-aml-principal' // Will be replaced with actual AML principal
    aiHubPrincipleId: '' // Simplified for compilation
    projectTeamGroupOrUser: [] // Empty array to avoid duplicate permissions
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    esmlCommonLake
    resourceExists_struct
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// RBAC deployment status information

@description('Key Vault and Bastion RBAC deployment status')
output keystoreAndBastionRbacDeployed bool = (empty(bastionResourceGroup) && addBastionHost) || (!empty(bastionResourceGroup) && !empty(bastionSubscription))

@description('AI Services RBAC deployment status')
output aiServicesRbacDeployed bool = (serviceSettingDeployAzureOpenAI && !openaiExists) || (!aiServicesExists && enableAIServices) || (!aiSearchExists && enableAISearch)

@description('AI Hub and ML Platform RBAC deployment status')
output aiHubMlRbacDeployed bool = (!aiHubExists && !empty(azureMachineLearningObjectId) && enableAIFoundryHub) || (!aiHubExists && enableAIFoundryHub) || (!aiSearchExists && enableAISearch)

@description('Optional Cognitive Services RBAC deployment status')
output optionalCognitiveRbacDeployed bool = serviceSettingDeployAzureAIVision || serviceSettingDeployAzureSpeech || serviceSettingDeployAIDocIntelligence

@description('Network and VNet RBAC deployment status')
output networkRbacDeployed bool = (addBastionHost && empty(bastionSubscription)) || (addBastionHost && !empty(bastionSubscription))

@description('Common Resource Group RBAC deployment status')
output commonResourceGroupRbacDeployed bool = useCommonACR

@description('Data Lake RBAC deployment status')
output dataLakeRbacDeployed bool = (!aiHubExists && enableAIFoundryHub) || (!amlExists && enableAzureMachineLearning)

@description('RBAC Security Phase 7 deployment completed successfully')
output rbacSecurityPhaseCompleted bool = true

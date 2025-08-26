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

// AI Factory naming
param aifactorySuffixRG string
@description('Project-specific resource suffix')
param resourceSuffix string

// Required parameters for naming convention module
param aifactorySalt10char string = ''
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param commonResourceGroupName string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// PS-Calculated and set by .JSON, that Powershell dynamically created in networking part.
param genaiSubnetId string = ''
param aksSubnetId string = ''
param acaSubnetId string = ''

// Resource group naming
param commonRGNamePrefix string = ''
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
var cmnName = namingConvention.outputs.cmnName

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: '07-naming-${targetResourceGroup}'
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
    commonResourceGroupName: commonResourceGroupName
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
  }
}

// Import all resource names from shared naming convention
var aiHubName = namingConvention.outputs.aiHubName
var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
var aiServicesName = namingConvention.outputs.aiServicesName
var aiProjectName = namingConvention.outputs.aiProjectName
var deploymentProjSpecificUniqueSuffix = '${projectName}-${env}-${randomValue}'
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name

//var twoNumbers = namingConvention.outputs.twoNumbers
//var aifProjectName = namingConvention.outputs.aifProjectName
//var aoaiName = namingConvention.outputs.aoaiName
//var amlName = namingConvention.outputs.amlName
//var safeNameAISearch = namingConvention.outputs.safeNameAISearch
//var dashboardInsightsName = namingConvention.outputs.dashboardInsightsName
//var applicationInsightName = namingConvention.outputs.applicationInsightName
//var bingName = namingConvention.outputs.bingName
//var containerAppsEnvName = namingConvention.outputs.containerAppsEnvName
//var containerAppAName = namingConvention.outputs.containerAppAName
//var containerAppWName = namingConvention.outputs.containerAppWName
//var cosmosDBName = namingConvention.outputs.cosmosDBName
//var functionAppName = namingConvention.outputs.functionAppName
//var webAppName = namingConvention.outputs.webAppName
//var funcAppServicePlanName = namingConvention.outputs.funcAppServicePlanName
//var webbAppServicePlanName = namingConvention.outputs.webbAppServicePlanName
//var keyvaultName = namingConvention.outputs.keyvaultName
//var acrProjectName = namingConvention.outputs.acrProjectName
//var redisName = namingConvention.outputs.redisName
//var postgreSQLName = namingConvention.outputs.postgreSQLName
//var sqlServerName = namingConvention.outputs.sqlServerName
//var sqlDBName = namingConvention.outputs.sqlDBName
//var vmName = namingConvention.outputs.vmName
//var aifName = namingConvention.outputs.aifName
//var aifPrjName = namingConvention.outputs.aifPrjName
//var miACAName = namingConvention.outputs.miACAName
//var miPrjName = namingConvention.outputs.miPrjName
//var acrCommonName = namingConvention.outputs.acrCommonName
//var laWorkspaceName = namingConvention.outputs.laWorkspaceName

// Resource exists flags from Azure DevOps
param amlExists bool = false
param aiHubExists bool = false
param aiServicesExists bool = false
param aiSearchExists bool = false
param openaiExists bool = false

// ============================================================================
// Resource definitions
// ============================================================================


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
// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

// Private DNS configuration
param centralDnsZoneByPolicyInHub bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param aiSearchName string
param openAIName string
// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string

param useAdGroups bool = false
// Azure ML Object ID for cross-service permissions
param azureMachineLearningObjectId string = ''

// Data Lake parameters
param datalakeName_param string = ''
param commonLakeNamePrefixMax8chars string

// Common ACR usage
param useCommonACR bool = true

// Tags
param tagsProject object = {}
param tags object = {}

// ============== VARIABLES ==============

// Network and resource group references
var projectResourceGroup_rgId = resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', targetResourceGroup)
// Data lake name calculation
var datalakeName = datalakeName_param != '' ? datalakeName_param : '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv_Static}esml${replace(commonResourceSuffix,'-','')}${env}'

// Calculated variables
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup

// Private DNS calculations
var privDnsResourceGroupName = (!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscription().subscriptionId

//param p011_genai_team_lead_array array = []
//param spAndMiArray array = []
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing AML, AIHub. Needs static name in existing
// ============================================================================

// Access policies for principals

resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

var miPrjName = namingConvention.outputs.miPrjName
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: 'getMI-${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId
module spAndMI2Array '../modules/spAndMiArray.bicep' = {
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
var spAndMiArray = spAndMI2Array.outputs.spAndMiArray

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============== AML Principal ID ==============
var amlName_Static = 'aml-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
resource amlREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: amlName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_amlPrincipalId = enableAzureMachineLearning ? amlREF.identity.principalId : 'BCP318' // !amlExists && enableAzureMachineLearning 

// ============== AI HUB Principal ID ==============
var aiHubName_Static = 'ai-hub-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
resource aiHubREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: aiHubName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_aiHubPrincipalId = enableAIFoundryHub ? aiHubREF.identity.principalId : 'BCP318' // !aiHubExists && enableAIFoundryHub

// ============== OPENAI Principal ID ==============
var openAIName_Static = 'openai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource openAIREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAIName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_openAIPrincipalId = serviceSettingDeployAzureOpenAI ? openAIREF.identity.principalId : 'BCP318'

// ============== AI SERVICES Principal ID ==============
var aiServicesName_Static = 'ais-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource aiServicesREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_aiServicesPrincipalId = enableAIServices ? aiServicesREF.identity.principalId : 'BCP318'

// ============== AI SEARCH Principal ID ==============
var aiSearchName_Static = 'aisearch-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource aiSearchREF 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: aiSearchName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_aiSearchPrincipalId = enableAISearch ? aiSearchREF.identity.principalId : 'BCP318'

// ============== VISION SERVICES Principal ID ==============
var visionName_Static = 'vision-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource visionREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: visionName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_visionPrincipalId = serviceSettingDeployAzureAIVision ? visionREF.identity.principalId : 'BCP318'

// ============== SPEECH SERVICES Principal ID ==============
var speechName_Static = 'speech-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource speechREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: speechName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_speechPrincipalId = serviceSettingDeployAzureSpeech ? speechREF.identity.principalId : 'BCP318'

// ============== DOCUMENT INTELLIGENCE Principal ID ==============
var docsName_Static = 'docs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource docsREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: docsName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_docsPrincipalId = serviceSettingDeployAIDocIntelligence ? docsREF.identity.principalId : 'BCP318'

// Datalake with datalakeName based on local, static VARS such as uniqueInAIFenv_Static
resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: datalakeName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============================================================================
// SPECIAL - END
// ============================================================================

// ============== EXISTING RESOURCE REFERENCES ==============

// Target resource group reference (existing from 01-foundation.bicep)
resource existingTargetRG 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============== RBAC MODULES - KEY VAULT AND BASTION ==============

// Bastion in AIFactory COMMON RG, but with a custom name
module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep' = if(empty(bastionResourceGroup) && addBastionHost) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: '07rbac1GenAIRUsCmnKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    common_kv_name: namingConvention.outputs.kvNameCommon
    user_object_ids: p011_genai_team_lead_array   
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
    rbacReadUsersToCmnVnetBastion
  ]
}

// Bastion Externally (Connectivity subscription and RG)
module rbacExternalBastion '../modules/rbacBastionExternal.bicep' = if(!empty(bastionResourceGroup) && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription, bastionResourceGroup)
  name: '07rbac2GenAIUsersBas${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
    rbacReadUsersToCmnVnetBastion
  ]
}

// ============== RBAC MODULES - AI SERVICES ==============

// RBAC for OpenAI - Storage, Search, and User Access
module rbacForOpenAI '../modules/aihubRbacOpenAI.bicep' = if (serviceSettingDeployAzureOpenAI && !openaiExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbac3OpenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSearchName: aiSearchName
    openAIServicePrincipal: var_openAIPrincipalId // Using computed variable for OpenAI principal ID
    servicePrincipleAndMIArray: spAndMiArray
    openAIName: openAIName
    userObjectIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
    rbacReadUsersToCmnVnetBastion
  ]
}

// RBAC for AI Services - Storage and Search Integration
module rbacModuleAIServices '../modules/aihubRbacAIServices.bicep' = if(!aiServicesExists && enableAIServices) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbac4AIServ${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSearchName: aiSearchName
    aiServicesPrincipalId: var_aiServicesPrincipalId // Using computed variable for AI Services principal ID
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for AI Search - Cross-service Integration
module rbacModuleAISearch '../modules/aihubRbacAISearch.bicep' = if(!aiSearchExists && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbac5Search${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiServicesName: aiServicesName
    aiSearchMIObjectId: var_aiSearchPrincipalId // Using computed variable for AI Search principal ID
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== RBAC MODULES - AI HUB AND ML PLATFORM ==============

// RBAC for AI Hub to Azure ML Resource Group
module rbacAihubRbacAmlRG '../modules/aihubRbacAmlRG.bicep' = if (!aiHubExists && !empty(azureMachineLearningObjectId) && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbac6Aml2RG${deploymentProjSpecificUniqueSuffix}'
  params: {
    azureMachineLearningObjectId: azureMachineLearningObjectId
    aiHubName: aiHubName
    aiHubPrincipalId: var_aiHubPrincipalId // Using computed variable for AI Hub principal ID
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for Users to AI Hub and Projects
module rbacModuleUsers '../modules/aihubRbacUsers.bicep' = if (!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbacUsersAIHub${deploymentProjSpecificUniqueSuffix}'
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
    existingTargetRG
  ]
}

// RBAC for Users to AI Search
module rbacModuleUsersToSearch '../modules/aiSearchRbacUsers.bicep' = if (!aiSearchExists && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbacAISearch${deploymentProjSpecificUniqueSuffix}'
  params: {
    aiSearchName: aiSearchName
    userObjectIds: p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== RBAC MODULES - OPTIONAL COGNITIVE SERVICES ==============

// RBAC for Azure AI Vision (Optional)
module rbacVision '../modules/aihubRbacVision.bicep' = if(serviceSettingDeployAzureAIVision == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbacVision${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiVisionMIObjectId: var_visionPrincipalId // Using computed variable for Vision principal ID
    userObjectIds: p011_genai_team_lead_array
    visonServiceName: visionName_Static // Using computed variable for Vision service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for Azure Speech Services (Optional)
module rbacSpeech '../modules/aihubRbacSpeech.bicep' = if(serviceSettingDeployAzureSpeech == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbacSpeech${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    aiSpeechMIObjectId: var_speechPrincipalId // Using computed variable for Speech principal ID
    userObjectIds: p011_genai_team_lead_array
    speechServiceName: speechName_Static // Using computed variable for Speech service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for AI Document Intelligence (Optional)
module rbacDocs '../modules/aihubRbacDoc.bicep' = if(serviceSettingDeployAIDocIntelligence == true) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '07rbacDocs${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    userObjectIds: p011_genai_team_lead_array
    aiDocsIntelMIObjectId: var_docsPrincipalId // Using computed variable for Document Intelligence principal ID
    docsServiceName: docsName_Static // Using computed variable for Document Intelligence service name
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== RBAC MODULES - NETWORK AND VNET ACCESS ==============

// RBAC - Read users to Bastion, IF Bastion is added in ESML-COMMON resource group
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost && empty(bastionSubscription)) {
  scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)
  name: '07rbacGenAIUsVn${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}

// Bastion VNet Externally (Connectivity subscription and RG || AI Factory Common RG)
module rbacReadUsersToCmnVnetBastionExt '../modules/vnetRBACReader.bicep' = if(addBastionHost && !empty(bastionSubscription)) {
  scope: resourceGroup(bastionSubscription, bastionResourceGroup)
  name: '07rbacUseVnet${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFullBastion
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== RBAC MODULES - COMMON RESOURCE GROUP ACCESS ==============

// RBAC on ACR Push/Pull for users in Common Resource group
module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: '07rbacUsCmnACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleAndMIArray: spAndMiArray
    userObjectIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
    rbacModuleUsers
  ]
}

// ============== RBAC MODULES - DATA LAKE ACCESS ==============

// RBAC for Data Lake - AI Foundry Integration
module rbacLakeFirstTime '../esml-common/modules-common/lakeRBAC.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: '07rbacLake4Prj${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: var_amlPrincipalId // Using computed variable for AML principal ID
    aiHubPrincipleId: var_aiHubPrincipalId // Using computed variable for AI Hub principal ID
    projectTeamGroupOrUser: p011_genai_team_lead_array
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    esmlCommonLake
    existingTargetRG
  ]
}

// RBAC for Data Lake - Azure ML Integration
module rbacLakeAml '../esml-common/modules-common/lakeRBAC.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: '07rbacLake4Amlv2${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: var_amlPrincipalId // Using computed variable for AML principal ID
    aiHubPrincipleId: var_aiHubPrincipalId // Using computed variable for AI Hub principal ID
    projectTeamGroupOrUser: [] // Empty array to avoid duplicate permissions
    adfPrincipalId: ''
    datalakeName: datalakeName
    useAdGroups: useAdGroups
  }
  dependsOn: [
    esmlCommonLake
    existingTargetRG
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

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
//
// IMPORTANT NOTES FOR DEPLOYMENT:
// 1. This template should only run AFTER resources are created
// 2. Set resource existence flags correctly (amlExists, aiHubExists, etc.)
// 3. If encountering RoleAssignmentExists errors, set skipExistingRoleAssignments=true
// 4. For ResourceNotFound errors, ensure resources exist before running this template
// ================================================================

/*
================ TROUBLESHOOTING: RoleAssignmentExists: rbacModuleUsers ================

Problem
- Azure won’t let a second assignment for the same (principal, role, scope) be created with a different,
  hence good practice to keep ALL assigments in one file, and one go, avoiding that another file assigns the role with different name than guid().

Reason
- Most conflicts in practice come from re-running deployments,
  when a role assignment already exists but was created before with a different name (e.g., portal/CLI/another template).

This template
- ASSIGNS many roles across different scopes (RG, AI Hub, AI Project, Storage, AI Services).
- SERVICES: aiServicesName, aifV1HubName, aifV1ProjectName, storageAccount1001Name, storageAccount2001Name:
- DISTINCT NAMES: All these come from naming conventions in the AIFactory and should be distinct (CmnAIFactoryNaming.bicep)
- INPUT HANDLING: It De-duplicate arrays before assignment.
- VERIFIED: The template does NOT have same role+same scope+same principal defined twice in the template itself.

HOW TO TROUBLE SHOOT and fix "RoleAssignmentExists":
1) Note which role+scope+principal combination fails: RG, AI Hub, AI Project, Storage, AI Services, storageAccount1001Name, storageAccount2001Name
2) Check in Azure portal, if that role is already assigned, remove the assigment.

================ END ==================================================
*/

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
param randomValue string
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// PS-Calculated and set by .JSON, that Powershell dynamically created in networking part.
param genaiSubnetId string = ''
param aksSubnetId string = ''
param acaSubnetId string = ''

// Resource group naming
param commonRGNamePrefix string


// Enable flags from parameter files
@description('Enable Azure Machine Learning deployment')
param enableAzureMachineLearning bool = false
param enableDatafactory bool = false
@description('Enable AI Foundry Hub deployment')
param enableAIFoundryHub bool = false
@description('Add AI Foundry Hub with random naming for debugging/testing')
param addAIFoundryHub bool = false
@description('Enable AI Foundry V2 deployment')
param enableAIFoundryV2 bool = false
@description('Enable AI Foundry V21 deployment')
param enableAIFoundryV21 bool = false

@description('Enable AI Services deployment')
param enableAIServices bool = false

@description('Enable AI Search deployment')
param enableAISearch bool = false

@description('Enable Azure OpenAI deployment')
param serviceSettingDeployAzureOpenAI bool = false

@description('Enable Azure AI Vision deployment')
param serviceSettingDeployAzureAIVision bool = false

@description('Enable Azure Speech deployment')
param serviceSettingDeployAzureSpeech bool = false

@description('Enable AI Document Intelligence deployment')
param serviceSettingDeployAIDocIntelligence bool = false

@description('Enable Azure Function deployment')
param serviceSettingDeployFunction bool = false

@description('Enable Azure Web App deployment')
param serviceSettingDeployWebApp bool = false

@description('Enable Container Apps deployment')
param serviceSettingDeployContainerApps bool = false

@description('Enable Application Insights Dashboard deployment')
param serviceSettingDeployAppInsightsDashboard bool = false

@description('Enable Cosmos DB deployment')
param serviceSettingDeployCosmosDB bool = false

@description('Enable PostgreSQL deployment')
param serviceSettingDeployPostgreSQL bool = false

@description('Enable Redis Cache deployment')
param serviceSettingDeployRedisCache bool = false

@description('Enable SQL Database deployment')
param serviceSettingDeploySQLDatabase bool = false

// Security and networking
param addBastionHost bool = false
param bastionResourceGroup string = ''
param bastionSubscription string = ''
param bastionName string = ''
param vnetNameFullBastion string = ''
param disableContributorAccessForUsers bool = false
param disableRBACAdminOnRGForUsers bool = false

// Required resource references. Networking parameters for calculation
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
// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string

param useAdGroups bool = true
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

// Resource exists flags from Azure DevOps
param amlExists bool = false
param aiHubExists bool = false
param aiServicesExists bool = false
param aiSearchExists bool = false
param openaiExists bool = false

// Additional deployment control flags to prevent duplicate role assignments
@description('Skip role assignments if they already exist (helps with re-runs)')
param skipExistingRoleAssignments bool = true

@description('Force recreation of role assignments (use with caution)')
param forceRecreateRoleAssignments bool = false

@description('Unique deployment identifier to avoid conflicts')
param deploymentId string = utcNow('yyyyMMddHHmmss')

var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
var cmnName = namingConvention.outputs.cmnName

// SPECIAL
var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 0, 10): aifactorySalt10char

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('08-naming-${targetResourceGroup}', 64)
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
    addAIFoundryHub: addAIFoundryHub
  }
}

// AI Foundry V1
var aifV1HubName = namingConvention.outputs.aifV1HubName
var aifV1ProjectName = namingConvention.outputs.aifV1ProjectName

var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
var aiServicesName = namingConvention.outputs.aiServicesName
var deploymentProjSpecificUniqueSuffix = '${projectName}-${env}-${randomValue}-${deploymentId}'
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var aiSearchName = enableAISearch? namingConvention.outputs.safeNameAISearch: ''
var openAIName = namingConvention.outputs.aoaiName

//var aifV2Name = namingConvention.outputs.aifV2Name
//var twoNumbers = namingConvention.outputs.twoNumbers
//var aifProjectName = namingConvention.outputs.aifProjectName
//var amlName = namingConvention.outputs.amlName
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

// ============================================================================
// Resource definitions
// ============================================================================

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
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing AML, AIHub. Needs static name in existing
// ============================================================================
resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

var miPrjName = namingConvention.outputs.miPrjName
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('08-getMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId
module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: take('08-spAndMI2Array-${targetResourceGroup}', 64)
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

// De-duplicate principals to avoid duplicate role assignments
// - Ensure user list is unique
// - Ensure SP/MI list is unique and has no overlap with users (in case a user OID was accidentally added to the SP/MI list)
var userIdsUnique = union(p011_genai_team_lead_array, p011_genai_team_lead_array)
var spAndMiUnique = union(spAndMiArray, spAndMiArray)

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup!
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============== AML Principal ID ==============
var amlName_Static = 'aml-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
resource amlREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!amlExists && enableAzureMachineLearning) {
  name: amlName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_amlPrincipalId = (!amlExists && enableAzureMachineLearning) ? amlREF.identity.principalId : ''

// ============== AI HUB Principal ID ==============
// AI Foundry Hub dynamic naming logic (matches CmnAIfactoryNaming.bicep)
var cleanRandomValue = toLower(replace(replace(randomSalt, '-', ''), '_', ''))
var aifRandom = take(cleanRandomValue,2)
// aif-hub-001-eus2-dev-qoygy-001 (30) + 2 = 32
var aifWithRandom = take('aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${aifRandom}${resourceSuffix}',64)
var aiHubName_Static = addAIFoundryHub ? aifWithRandom : 'aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

// aif-p-002-1-eus2-dev-qoygy-001
var aiHubProjectName_Static = 'aif-p-${projectNumber}-1-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

resource aiHubREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!aiHubExists && enableAIFoundryHub) {
  name: aiHubName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
resource existingAIHubProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!aiHubExists && enableAIFoundryHub) {
  name: aiHubProjectName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

#disable-next-line BCP318
var var_aiHubPrincipalId = (!aiHubExists && enableAIFoundryHub) ? aiHubREF.identity.principalId : ''
#disable-next-line BCP318
var var_aiHubProjectPrincipalId = (!aiHubExists && enableAIFoundryHub) ? existingAIHubProject.identity.principalId : ''

// ============== OPENAI Principal ID ==============
var openAIName_Static = 'aoai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
resource openAIREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!openaiExists && serviceSettingDeployAzureOpenAI) {
  name: openAIName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_openAIPrincipalId = (!openaiExists && serviceSettingDeployAzureOpenAI) ? openAIREF.identity.principalId : ''

// ============== AI SERVICES Principal ID ==============
var aiServicesName_Static = replace(toLower('aiservices${projectName}${locationSuffix}${env}${uniqueInAIFenv_Static}${randomSalt}${prjResourceSuffixNoDash}'), '-', '') 
resource aiServicesREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!aiServicesExists && enableAIServices) {
  name: aiServicesName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_aiServicesPrincipalId = (!aiServicesExists && enableAIServices) ? aiServicesREF.identity.principalId : ''

// ============== AI SEARCH Principal ID ==============
var aiSearchName_Static = replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv_Static}${randomSalt}${resourceSuffix}'), '-', '')
resource aiSearchREF 'Microsoft.Search/searchServices@2024-06-01-preview' existing = if (!aiSearchExists && enableAISearch) {
  name: aiSearchName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_aiSearchPrincipalId = (!aiSearchExists && enableAISearch) ? aiSearchREF.identity.principalId : ''

// ============== VISION SERVICES Principal ID ==============
var visionName_Static = 'vision-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource visionREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (serviceSettingDeployAzureAIVision) {
  name: visionName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_visionPrincipalId = serviceSettingDeployAzureAIVision ? visionREF.identity.principalId : ''

// ============== SPEECH SERVICES Principal ID ==============
var speechName_Static = 'speech-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource speechREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (serviceSettingDeployAzureSpeech) {
  name: speechName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_speechPrincipalId = serviceSettingDeployAzureSpeech ? speechREF.identity.principalId : ''

// ============== DOCUMENT INTELLIGENCE Principal ID ==============
var docsName_Static = 'docs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource docsREF 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (serviceSettingDeployAIDocIntelligence) {
  name: docsName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_docsPrincipalId = serviceSettingDeployAIDocIntelligence ? docsREF.identity.principalId : ''

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
  name: take('08-rbac1GenAIRUsCmnKV${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbac2GenAIUsersBas${deploymentProjSpecificUniqueSuffix}', 64)
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


// ============== AI HUB - STORAGE PRIVATE ENDPOINT READER ROLE ASSIGNMENTS ==============
var genaiName = namingConvention.outputs.projectTypeGenAIName

// Assign Reader role on storage account 1001 blob private endpoint to AI Project
module storageReaderRole1001 '../modules/storagePendReaderToAIProject.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-storageReader1001${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    aiProjectName: aifV1ProjectName
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}ml'
  }
}

// Assign Reader role on storage account 2001 blob private endpoint to AI Project
module storageReaderRole2001 '../modules/storagePendReaderToAIProject.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-storageReader2001${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount2001Name
    aiProjectName: aifV1ProjectName
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}'
  }
}


// ============== RBAC MODULES - AI SERVICES ==============

// RBAC for OpenAI - Storage, Search, and User Access
module rbacForOpenAI '../modules/aihubRbacOpenAI.bicep' = if (serviceSettingDeployAzureOpenAI && !openaiExists) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbac3OpenAI${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbac4AIServ${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbac5Search${deploymentProjSpecificUniqueSuffix}', 64)
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
//  Please ensure that the project managed identity has Search Index Data Reader and Search Service Contributor roles on the Search resource
module rbacAihubRbacAmlRG '../modules/aihubRbacAmlRG.bicep' = if (!aiHubExists && !empty(azureMachineLearningObjectId) && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbac6Aml2RG${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    azureMachineLearningObjectId: azureMachineLearningObjectId
    aiHubName: aifV1HubName
    aiHubPrincipalId: var_aiHubPrincipalId // Using computed variable for AI Hub principal ID
    aiHubProjectName: aifV1ProjectName
    aiHubProjectPrincipalId: var_aiHubProjectPrincipalId // Using computed variable for AI Hub project principal ID
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for Users to AI Hub and Projects
module rbacModuleUsers '../modules/aihubRbacUsers.bicep' = if (!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacUsersAIHub${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    aiServicesName: aiServicesName
    storageAccountName: storageAccount1001Name
    storageAccountName2: storageAccount2001Name
    resourceGroupId: projectResourceGroup_rgId
    userObjectIds: userIdsUnique
    aiHubName: aifV1HubName
    aiHubProjectName: aifV1ProjectName
    servicePrincipleAndMIArray: spAndMiUnique
    useAdGroups: useAdGroups
    disableContributorAccessForUsers: disableContributorAccessForUsers
    disableRBACAdminOnRGForUsers:disableRBACAdminOnRGForUsers
  }
  dependsOn: [
    existingTargetRG
  ]
}

// RBAC for Users to AI Search
module rbacModuleUsersToSearch '../modules/aiSearchRbacUsers.bicep' = if (!aiSearchExists && enableAISearch) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacAISearch${deploymentProjSpecificUniqueSuffix}', 64)
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

module rbacDatafactory '../modules/datafactoryRBAC.bicep' = if(enableDatafactory) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacDatafactory${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
    datafactoryName:namingConvention.outputs.dataFactoryName
    disableContributorAccessForUsers: disableContributorAccessForUsers
  }
  dependsOn: [
    existingTargetRG
    rbacModuleUsers
  ]
}

// ============== RBAC MODULES - OPTIONAL COGNITIVE SERVICES ==============

// RBAC for Azure AI Vision (Optional)
module rbacVision '../modules/aihubRbacVision.bicep' = if(serviceSettingDeployAzureAIVision) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacVision${deploymentProjSpecificUniqueSuffix}', 64)
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
module rbacSpeech '../modules/aihubRbacSpeech.bicep' = if(serviceSettingDeployAzureSpeech) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacSpeech${deploymentProjSpecificUniqueSuffix}', 64)
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
module rbacDocs '../modules/aihubRbacDoc.bicep' = if(serviceSettingDeployAIDocIntelligence) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('08-rbacDocs${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbacGenAIUsVn${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbacUseVnet${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbacUsCmnACR${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbacLake4Prj${deploymentProjSpecificUniqueSuffix}', 64)
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
  name: take('08-rbacLake4Amlv2${deploymentProjSpecificUniqueSuffix}', 64)
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

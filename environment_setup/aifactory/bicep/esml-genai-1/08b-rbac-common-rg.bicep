targetScope = 'subscription'

// ================================================================
// RBAC COMMON RESOURCE GROUP DEPLOYMENT - Phase 8b
// This file deploys RBAC assignments specifically for the common resource group:
// - Common Key Vault and Bastion access
// - Azure Container Registry (ACR) push/pull permissions
// - Data Lake access for AI Foundry and Azure ML
// 
// This module is separated from main RBAC (08-rbac-security.bicep) for:
// - Better modularity and troubleshooting
// - Independent deployment/updates of common RG permissions
// - Clearer separation of project vs common resource permissions
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

// AI Factory naming
param aifactorySuffixRG string
param commonRGNamePrefix string
param aifactorySalt10char string = ''
param randomValue string
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

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
@description('App Service / Function VNet integration subnet (delegated to Microsoft.Web/serverFarms)')
param webappSubnetId string = ''
param dbxPubSubnetName string = ''
param dbxPrivSubnetName string = ''

// Resource group naming
param projectPrefix string = ''
param projectSuffix string = ''

// Networking
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

// Resource group configuration
param commonResourceGroup_param string = ''
@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

// Security and access control
param addBastionHost bool = false
param bastionResourceGroup string = ''
param bastionName string = ''
param useAdGroups bool = true

@description('Disable VNet subnet join action RBAC assignment (Network Contributor role)')
param disableSubnetJoinAction bool = false

// Common ACR usage
param useCommonACR bool = true

// Seeding Key Vault parameters
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string

// Data Lake parameters
param datalakeName_param string = ''
param commonLakeNamePrefixMax8chars string

// Enable flags
@description('Enable AI Foundry Hub deployment')
param enableAIFoundryHub bool = false
@description('Add AI Foundry Hub with random naming for debugging/testing')
param addAIFoundryHub bool = false

@description('Enable Azure Machine Learning deployment')
param enableAzureMachineLearning bool = false
@description('Add Azure Machine Learning with random naming for debugging/testing')
param addAzureMachineLearning bool = false

// Resource exists flags
param aiHubExists bool = false
param amlExists bool = false

@description('Comma-separated list of principal IDs that already have acrPush role (Users/Groups)')
param existingAcrPushUserPrincipals string = ''

@description('Comma-separated list of principal IDs that already have acrPush role (ServicePrincipals/MIs)')
param existingAcrPushSPPrincipals string = ''

@description('Unique deployment identifier to avoid conflicts')
param deploymentId string = utcNow('yyyyMMddHHmmss')

// ============== VARIABLES ==============
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Networking calculations
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

// Random salt for unique naming
var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 0, 10): aifactorySalt10char

var deploymentProjSpecificUniqueSuffix = '${projectName}-${env}-${randomValue}-${deploymentId}'

// Parse comma-separated principal ID strings into arrays for filtering
var existingUserPrincipalsArray = !empty(existingAcrPushUserPrincipals) ? split(existingAcrPushUserPrincipals, ',') : []
var existingSPPrincipalsArray = !empty(existingAcrPushSPPrincipals) ? split(existingAcrPushSPPrincipals, ',') : []

// ============================================================================
// AI Factory - naming convention (imported from shared module)
// ============================================================================
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('08b-naming-${commonResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
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
    addAzureMachineLearning: addAzureMachineLearning
  }
}

var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array
var cleanRandomValue = take(randomSalt, 2)

// ============================================================================
// GET PRINCIPAL IDs FROM KEYVAULT
// ============================================================================
resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

var miPrjName = namingConvention.outputs.miPrjName
module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('08b-getMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

var var_miPrj_PrincipalId = getProjectMIPrincipalId.outputs.principalId

module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: take('08b-spAndMI2Array-${targetResourceGroup}', 64)
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
var userIdsUnique = union(p011_genai_team_lead_array, p011_genai_team_lead_array)
var spAndMiUnique = union(spAndMiArray, spAndMiArray)

// Filter out principals that already have acrPush role at RG level (idempotency)
// This makes the deployment truly idempotent by skipping only specific assignments that exist
var userIdsFiltered = filter(userIdsUnique, userId => !contains(existingUserPrincipalsArray, userId))
var spAndMiFiltered = filter(spAndMiUnique, principalId => !contains(existingSPPrincipalsArray, principalId))

// ============================================================================
// GET STATIC UNIQUE VALUES FOR NAMING
// ============================================================================
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup!
  scope: subscription(subscriptionIdDevTestProd)
}

#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============================================================================
// GET PRINCIPAL IDs FROM EXISTING RESOURCES
// ============================================================================

// ============== AML Principal ID ==============
var amlWithRandom = take('aml-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${cleanRandomValue}${resourceSuffix}',64)
var amlName_Static = addAzureMachineLearning ? amlWithRandom : 'aml-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

resource amlREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!amlExists && enableAzureMachineLearning) {
  name: amlName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_amlPrincipalId = (!amlExists && enableAzureMachineLearning) ? amlREF.identity.principalId : ''

// ============== AI HUB Principal ID ==============
var aifWithRandom = take('aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${cleanRandomValue}${resourceSuffix}',64)
var aiHubName_Static = addAIFoundryHub ? aifWithRandom : 'aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

resource aiHubREF 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!aiHubExists && enableAIFoundryHub) {
  name: aiHubName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

#disable-next-line BCP318
var var_aiHubPrincipalId = (!aiHubExists && enableAIFoundryHub) ? aiHubREF.identity.principalId : ''

// ============================================================================
// DATA LAKE REFERENCE
// ============================================================================
var datalakeName = datalakeName_param != '' ? datalakeName_param : '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv_Static}esml${replace(commonResourceSuffix,'-','')}${env}'

resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: datalakeName
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ============================================================================
// EXISTING RESOURCE REFERENCES
// ============================================================================
resource existingTargetRG 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============================================================================
// RBAC MODULES - COMMON RESOURCE GROUP
// ============================================================================

// ============== COMMON KEY VAULT AND BASTION ==============
// Bastion in AIFactory COMMON RG, but with a custom name
module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep' = if(empty(bastionResourceGroup) && addBastionHost) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('08b-rbac1GenAIRUsCmnKV${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    common_kv_name: namingConvention.outputs.kvNameCommon
    user_object_ids: p011_genai_team_lead_array   
    bastion_service_name: empty(bastionName) ? 'bastion-${locationSuffix}-${env}${commonResourceSuffix}' : bastionName
    useAdGroups: useAdGroups
    servicePrincipleAndMIArray: spAndMiArray
    vNetName: vnetNameFull
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== ACR ACCESS ==============
// RBAC on Common Resource Group for ACR Push/Pull access
// Grants users, groups, service principals, and managed identities access to:
// - Azure Container Registry (ACR) Push/Pull roles
// - Allows publishing and consuming container images
// Uses filtered arrays to skip principals that already have the role (idempotent)
module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('08b-rbacUsCmnACR${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleAndMIArray: spAndMiFiltered
    userObjectIds: userIdsFiltered
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== VNET/SUBNET JOIN ACCESS ==============
// RBAC for VNet - Network Contributor role to allow subnet join actions
// Required for services like API Management, Container Apps, AKS to join subnets
// Grants users, service principals, and managed identities:
// - Microsoft.Network/virtualNetworks/subnets/join/action permission
// - Required for deploying services into subnets across resource groups
// Can be disabled with disableSubnetJoinAction=true if subnet join permissions
// are managed separately (e.g., via Azure Policy or external RBAC)
module cmnRbacVNet '../modules/vnetRBACReader.bicep' = if (!disableSubnetJoinAction) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('08b-rbacVNetSubnetJoin${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray: spAndMiArray
    user_object_ids: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    existingTargetRG
  ]
}

// ============== DATA LAKE ACCESS ==============
// RBAC for Data Lake - AI Foundry Integration
module rbacLakeFirstTime '../esml-common/modules-common/lakeRBAC.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: take('08b-rbacLake4Prj${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    amlPrincipalId: var_amlPrincipalId
    aiHubPrincipleId: var_aiHubPrincipalId
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
  name: take('08b-rbacLake4Amlv2${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    amlPrincipalId: var_amlPrincipalId
    aiHubPrincipleId: var_aiHubPrincipalId
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

// ============================================================================
// OUTPUTS
// ============================================================================
@description('Common Resource Group Key Vault and Bastion RBAC deployment status')
output commonKeyVaultBastionRbacDeployed bool = empty(bastionResourceGroup) && addBastionHost

@description('Common Resource Group ACR RBAC deployment status (with idempotent filtering)')
output commonAcrRbacDeployed bool = useCommonACR

@description('Common VNet Network Contributor RBAC deployment status (for subnet join permissions)')
output commonVNetRbacDeployed bool = !disableSubnetJoinAction

@description('Number of filtered user principals for ACR RBAC (after removing existing assignments)')
output acrUserPrincipalsFiltered int = length(userIdsFiltered)

@description('Number of filtered SP/MI principals for ACR RBAC (after removing existing assignments)')
output acrSPPrincipalsFiltered int = length(spAndMiFiltered)

@description('Common Resource Group Data Lake RBAC deployment status')
output commonDataLakeRbacDeployed bool = (!aiHubExists && enableAIFoundryHub) || (!amlExists && enableAzureMachineLearning)

@description('RBAC Common RG Phase 8b deployment completed successfully')
output rbacCommonRgPhaseCompleted bool = true

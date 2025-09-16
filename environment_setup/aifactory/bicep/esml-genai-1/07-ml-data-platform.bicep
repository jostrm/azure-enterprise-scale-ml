targetScope = 'subscription'

// ================================================================
// ML PLATFORM DEPLOYMENT - Phase 7 Implementation
// This file deploys ML and AI platform services including:
// - Azure Machine Learning Workspace (v1,v2)
// - Azure Kubernetes Service (AKS), private cluster, for ML workloads
// - Default CPU AML Cluster, Attached AKS to AML
// - Databricks
// - Azure Data Factory 
// - RBAC and permissions for ML platform, Data Factory, Databricks
// ================================================================

// ============== SKUs ==============
param mlWorkspaceSkuName string = 'basic'
param mlWorkspaceSkuTier string = 'basic'

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., "weu", "sdc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

@description('Random salt for unique naming')
param aifactorySalt10char string = ''
param randomValue string

@description('AI Factory suffix for resource groups')
param aifactorySuffixRG string

@description('Common resource group name')
param commonResourceGroupName string

@description('Subscription ID for dev/test/prod')
param subscriptionIdDevTestProd string

@description('GenAI subnet ID')
param genaiSubnetId string

@description('AKS subnet ID')
param aksSubnetId string

@description('ACA subnet ID')
param acaSubnetId string

@description('Technical admins object ID')
param technicalAdminsObjectID string = ''

@description('Technical admins email')
param technicalAdminsEmail string = ''

@description('Enable Data Factory deployment')
param enableDatafactory bool = false
param enableAzureMachineLearning bool = false

@description('Enable public access with perimeter for Data Factory')
param enablePublicAccessWithPerimeter bool = false

@description('Tags to apply to all resources')
param tags object

@description('Network environment (e.g., dev, test, prod)')
param network_env string = env

@description('VNet name with placeholder for network environment')
param vnetNameFull_param string = ''

@description('Base VNet name when no full name is provided')
param vnetNameBase string = 'vnet-cmn'

@description('VNet resource group name with placeholder for network environment')
param vnetResourceGroup_param string = ''

@description('Common resource group name for VNet')
param commonResourceGroup string = commonResourceGroupName

@description('Add AI Foundry Hub with random naming')
param addAIFoundryHub bool = false

@description('Common resource group name prefix')
param commonRGNamePrefix string = ''

@description('Project prefix for resource naming')
param projectPrefix string = ''

@description('Project name for resource group construction')
param projectName string = 'prj${projectNumber}'

@description('Project suffix for resource group naming')
param projectSuffix string = resourceSuffix

// ================= ADDITIONAL AZURE ML PARAMETERS (migrated from 06) =================
// Resource exists flags
@description('Indicates if AML workspace already exists (set by pipeline)')
param amlExists bool = false
param aksExists bool = false
param dataFactoryExists bool = false

// Networking / AKS settings needed for AML & attached AKS
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aks_dev_sku_override string = ''
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1

// Compute Instance overrides
param aml_ci_dev_sku_override string = ''
param aml_ci_test_prod_sku_override string = ''

// AML Compute Cluster overrides
param aml_cluster_dev_sku_override string = ''
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1

// Security / access
param AMLStudioUIPrivate bool = true
param centralDnsZoneByPolicyInHub bool = false
param useCommonACR bool = true
param useAdGroups bool = false

// Tags specific to project (separate from generic tags already present)
param tagsProject object = {}

// IP Whitelist (comma separated) for AML studio / scoring endpoints
param IPwhiteList string = ''

// Key Vault seeding / SP linking (needed for spAndMiArray)
@description('Existing Key Vault name containing SP secret for seeding')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
@description('Secret name in Key Vault that stores Service Principal ObjectId used for seeding')
param projectServicePrincipleOID_SeedingKeyvaultName string


// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing MI. Needs static name in existing
// ============================================================================
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============== VARS ==============
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup
var dataFactoryName = 'adf-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

// ============== MODULES ==============

// Import naming convention module
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('01-naming-${targetResourceGroup}', 64)
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
    commonResourceGroupName: commonResourceGroupName
    commonRGNamePrefix: commonRGNamePrefix
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    addAIFoundryHub: addAIFoundryHub
  }
}

// Private DNS zones (mirrors phase 06, needed for AML private endpoints)
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('07-getPrivDnsZ-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    // Using same RG/subscription as target (adjust if central DNS zone used)
    privDnsResourceGroupName: vnetResourceGroupName
    privDnsSubscription: subscriptionIdDevTestProd
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// ================== AZURE ML RELATED VARIABLES (exact copy style from 06) ==================
// Random salt for unique naming - using uniqueString for deterministic salt
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// Outputs from namingConvention
var miPrjName = namingConvention.outputs.miPrjName
var miACAName = namingConvention.outputs.miACAName
var amlName = namingConvention.outputs.amlName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
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

// Default subnet mapping
var defaultSubnet = genaiSubnetName

// Compute defaults
param aks_dev_defaults array = [
  'Standard_B4ms'
  'Standard_A4m_v2'
  'Standard_D3_v2'
]
param aks_testProd_defaults array = [
  'Standard_DS13-2_v2'
  'Standard_A8m_v2'
]
param aml_dev_defaults array = [
  'Standard_DS3_v2'
  'Standard_F8s_v2'
  'Standard_DS12_v2'
]
param aml_testProd_defaults array = [
  'Standard_D13_v2'
  'Standard_D4_v2'
  'Standard_F16s_v2'
]
param ci_dev_defaults array = [
  'Standard_DS11_v2'
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

// AKS default version from phase 06
var aksDefaultVersion = '1.30.3'

// Resolved compute parameters
var aks_dev_sku_param = !empty(aks_dev_sku_override) ? aks_dev_sku_override : aks_dev_defaults[0]
var aks_test_prod_sku_param = !empty(aks_test_prod_sku_override) ? aks_test_prod_sku_override : aks_testProd_defaults[0]
var aks_version_param = !empty(aks_version_override) ? aks_version_override : aksDefaultVersion
var aks_dev_nodes_param = aks_dev_nodes_override != -1 ? aks_dev_nodes_override : 1
var aks_test_prod_nodes_param = aks_test_prod_nodes_override != -1 ? aks_test_prod_nodes_override : 3
var aml_ci_dev_sku_param = !empty(aml_ci_dev_sku_override) ? aml_ci_dev_sku_override : ci_dev_defaults[0]
var aml_ci_test_prod_sku_param = !empty(aml_ci_test_prod_sku_override) ? aml_ci_test_prod_sku_override : ci_devTest_defaults[0]
var aml_cluster_dev_sku_param = !empty(aml_cluster_dev_sku_override) ? aml_cluster_dev_sku_override : aml_dev_defaults[0]
var aml_cluster_test_prod_sku_param = !empty(aml_cluster_test_prod_sku_override) ? aml_cluster_test_prod_sku_override : aml_testProd_defaults[1]
var aml_cluster_dev_nodes_param = aml_cluster_dev_nodes_override != -1 ? aml_cluster_dev_nodes_override : 3
var aml_cluster_test_prod_nodes_param = aml_cluster_test_prod_nodes_override != -1 ? aml_cluster_test_prod_nodes_override : 3

// IP whitelist processing (normalized)
// IP Rules processing (same as 06)
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: replace(ip, '/32', '')]
// Normalize IP addresses: add /32 to single IPs if not present
var ipWhitelist_normalized = [for ip in ipWhitelist_array: contains(trim(ip), '/') ? trim(ip) : '${trim(ip)}/32']
var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

// Existing target RG (for dependsOn, RBAC) (copied definition)
resource existingTargetRG 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// Log Analytics existing (needed for AML & RBAC modules)
var cmnName_Static = 'cmn'
var laWorkspaceName_Static = 'la-${cmnName_Static}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// ===== SPECIAL: Managed Identity principal & SP+MI array (copied from 06) =====
var randomSaltLogic = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? (empty(randomValue) ? substring(uniqueString(subscription().subscriptionId), 0, 10) : substring(randomValue, 0, 10)) : aifactorySalt10char
var miPrjName_Static = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${randomSaltLogic}${resourceSuffix}'
resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: miPrjName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_miPrj_PrincipalId = miPrjREF.properties.principalId

resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: take('07-spAndMI2Array-${targetResourceGroup}', 64)
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

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// Azure Data Factory deployment
module dataFactory '../modules/dataFactory.bicep' = if (!dataFactoryExists && enableDatafactory) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('06-Datafactory-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: dataFactoryName
    location: location
    tags: tags
    vnetId: vnet.id
    subnetName: namingConvention.outputs.defaultSubnet
    portalPrivateEndpointName: '${dataFactoryName}-portal-pend'
    runtimePrivateEndpointName: '${dataFactoryName}-dataFactory-pend'
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    managedIdentities: {
      systemAssigned: true
    }
  }
}


// ============== AZURE MACHINE LEARNING WORKSPACE ==============

module amlv2 '../modules/machineLearningv2.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('06-AzureMLDepl${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: amlName
    managedIdentities: {
      systemAssigned: true
      //userAssignedResourceIds: concat(
        //!empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        //!empty(miACAName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)) : []
      //)
    }
    uniqueDepl: deploymentProjSpecificUniqueSuffix
    uniqueSalt5char: namingConvention.outputs.uniqueInAIFenv
    projectName: projectName
    projectNumber: projectNumber
    location: location
    locationSuffix: locationSuffix
    aifactorySuffix: aifactorySuffixRG
    skuName: mlWorkspaceSkuName
    skuTier: mlWorkspaceSkuTier
    env: env
    aksSubnetId: aksSubnetId
    aksSubnetName: aksSubnetName
    aksDnsServiceIP: aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: tagsProject
    vnetId: vnet.id
    subnetName: defaultSubnet
    privateEndpointName: '${amlName}-pend'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID: privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet: (AMLStudioUIPrivate == true && empty(ipWhitelist_remove_ending_32)) ? false : true
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter // AMLStudioUIPrivate == false ? true : false
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    aksVmSku_dev: aks_dev_sku_param
    aksVmSku_testProd: aks_test_prod_sku_param
    aksNodes_dev: aks_dev_nodes_param
    aksNodes_testProd: aks_test_prod_nodes_param
    kubernetesVersionAndOrchestrator: aks_version_param
    amlComputeDefaultVmSize_dev: aml_cluster_dev_sku_param
    amlComputeDefaultVmSize_testProd: aml_cluster_test_prod_sku_param
    amlComputeMaxNodex_dev: aml_cluster_dev_nodes_param
    amlComputeMaxNodex_testProd: aml_cluster_test_prod_nodes_param
    ciVmSku_dev: aml_ci_dev_sku_param
    ciVmSku_testProd: aml_ci_test_prod_sku_param
    ipRules: empty(processedIpRulesAzureML) ? [] : processedIpRulesAzureML
    //ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32
    ipWhitelist_array: empty(ipWhitelist_normalized) ? [] : ipWhitelist_normalized
    saName: storageAccount2001Name
    kvName: keyvaultName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    appInsightsName: applicationInsightName
  }
  dependsOn: [
    existingTargetRG
    dataFactory
    // Dependencies handled through parameters - storage, keyvault, ACR should exist from previous phases
  ]
}


// ============== MACHINE LEARNING RBAC + AML to access STORAGE ==============
module rbacAmlv2Storage '../modules/rbacStorageAml.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('07-rbacAmlv2Storage${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount2001Name
    userObjectIds: p011_genai_team_lead_array
    azureMLworkspaceName: amlName
    servicePrincipleAndMIArray: spAndMiArray
    useAdGroups: useAdGroups
    user2Storage: true
  }
  dependsOn: [
    ...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])
    ...(!dataFactoryExists && enableDatafactory ? [dataFactory] : [])
  ]
}

// ============== MACHINE LEARNING RBAC + ADF to access AML ==============

module rbacAmlv2SPsAndADF '../modules/machinelearningRBAC.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('07-rbacAmlv2SPsAndADF${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    amlName: amlName
    servicePrincipleAndMIArray: spAndMiArray
    #disable-next-line BCP318
    adfSP: enableDatafactory? dataFactory.outputs.principalId: '' // ADF Service Principal - empty if not using ADF integration
    projectADuser: ''
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])
    logAnalyticsWorkspaceOpInsight
    ...(!dataFactoryExists && enableDatafactory ? [dataFactory] : [])
  ]
}


// ============== OUTPUTS ==============
output dataFactoryEnabled bool = enableDatafactory

// Conditional outputs for Data Factory - only when enabled
output dataFactoryId string = enableDatafactory ? dataFactory!.outputs.adfId : ''
output dataFactoryName string = enableDatafactory ? dataFactory!.outputs.adfName : ''
output dataFactoryPrincipalId string = enableDatafactory ? dataFactory!.outputs.principalId : ''

output azureMLDeployed bool = (!amlExists && enableAzureMachineLearning)

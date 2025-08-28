targetScope = 'subscription'

// ================================================================
// ML PLATFORM DEPLOYMENT - Phase 6 Implementation
// This file deploys ML and AI platform services including:
// - Azure Machine Learning Workspace (v2)
// - AI Foundry Hub and Project
// - Azure Kubernetes Service (AKS) for ML workloads
// - Compute Instances and Clusters
// - RBAC and permissions for ML platform
// ================================================================

// ============================================================================
// SKU for services
// ============================================================================
// Azure ML Workspace SKUs
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

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

// Resource exists flags from Azure DevOps
param amlExists bool = false
param aiHubExists bool = false
param aifProjectExists bool = false
param aiFoundryV2Exists bool = false
param aksExists bool = false
param miPrjExists bool = false

// Enable flags from parameter files
@description('Enable Azure Machine Learning deployment')
param enableAzureMachineLearning bool = false
param serviceSettingDeployCosmosDB bool = false
param enableAISearch bool = false

@description('Enable AI Foundry Hub deployment')
param enableAIFoundryHub bool = true

@description('Enable AI Foundry 2 features')
param enableAIFoundryV2 bool = false

// AI Models deployment parameters
@description('Whether to deploy GPT-4 model')
param deployModel_gpt_4 bool = false

@description('GPT-4 model name if deploying')
param modelGPT4Name string = 'gpt-4'

@description('GPT-4 model version if deploying')
param modelGPT4Version string = '1'

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
param default_gpt_4o_version string = '2024-08-06'
@description('Whether to deploy GPT-4o-mini model')
param deployModel_gpt_4o_mini bool = false
param default_gpt_4o_mini_version string = '2024-07-18' // All models works with Bing search, except gpt-4o-mini,version: 2024-07-18 

@description('Default SKU for models')
@allowed(['Standard', 'GlobalStandard'])
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
param AMLStudioUIPrivate bool = true

// PS-Calculated and set by .JSON, that Powershell dynamically created in networking part.
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

// Networking parameters for calculation
param vnetNameBase string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''

@description('Common default subnet')
param common_subnet_name string // TODO - 31-network.bicep for own subnet
param subnetCommon string = ''
param subnetCommonScoring string = ''

// Private DNS configuration
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Resource group configuration
param commonResourceGroup_param string = ''

// AKS Configuration
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'
param aksOutboundType string = 'loadBalancer'
var aksDefaultVersion = '1.30.3'

// AKS SKU overrides
param aks_dev_sku_override string = ''
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1

// Azure ML Compute Instance overrides
param aml_ci_dev_sku_override string = ''
param aml_ci_test_prod_sku_override string = ''

// Azure ML Compute Cluster overrides
param aml_cluster_dev_sku_override string = ''
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1

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
param randomValue string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param subscriptionIdDevTestProd string = subscription().subscriptionId

// Common ACR usage
param useCommonACR bool = true

// Technical contact and user groups
param useAdGroups bool = false
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'

// ============== VARIABLES ==============

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
  name: '06-naming-${targetResourceGroup}'
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

// AI Search
var aiSearchName = namingConvention.outputs.safeNameAISearch
var aiServicesName = namingConvention.outputs.aiServicesName

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

//var cmnName = namingConvention.outputs.cmnName
//var uniqueInAIFenv = namingConvention.outputs.uniqueInAIFenv
//var prjResourceSuffixNoDash = namingConvention.outputs.prjResourceSuffixNoDash

// IP Rules processing
var ipWhitelist_array = !empty(IPwhiteList) ? split(IPwhiteList, ',') : []
var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: replace(ip, '/32', '')]

var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRulesAIHub = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: trim(ip)
}]

// Network references using proper resource references
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, vnetResourceGroupName)
  name: vnetNameFull
}

resource externalKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

// Private DNS zones (simplified structure)
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: '06-getPrivDnsZ-${targetResourceGroup}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones
// ============== AKS AND ML COMPUTE DEFAULTS ==============

// AKS: Azure Kubernetes Service defaults
param aks_dev_defaults array = [
  'Standard_B4ms' // 4 cores, 16GB, 32GB storage: Burstable
  'Standard_A4m_v2' // 4cores, 32GB, 40GB storage
  'Standard_D3_v2' // 4 cores, 14GB RAM, 200GB storage
]

param aks_testProd_defaults array = [
  'Standard_DS13-2_v2' // 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' // 8 cores, 64GB RAM, 80GB storage
]

// Azure ML Compute defaults
param aml_dev_defaults array = [
  'Standard_DS3_v2' // 4 cores, 14GB ram, 28GB storage
  'Standard_F8s_v2' // 8,16,64
  'Standard_DS12_v2' // 4 cores, 28GB RAM, 56GB storage
]

param aml_testProd_defaults array = [
  'Standard_D13_v2' // 8 cores, 56GB, 400GB storage
  'Standard_D4_v2' // 8 cores, 28GB RAM, 400GB storage
  'Standard_F16s_v2' // 16 cores, 32GB RAM, 128GB storage
]

// Compute Instance defaults
param ci_dev_defaults array = [
  'Standard_DS11_v2' // 2 cores, 14GB RAM, 28GB storage
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

// Compute parameter resolution with overrides
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

resource existingTargetRG 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
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

// ============== AZURE MACHINE LEARNING WORKSPACE ==============

module amlv2 '../modules/machineLearningv2.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-AzureMLDepl${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: amlName
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miACAName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)) : []
      )
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
    privateEndpointName: 'pend-${projectName}-aml-to-vnt-mlcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID: privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet: (AMLStudioUIPrivate == true && empty(ipWhitelist_remove_ending_32)) ? false : true
    enablePublicAccessWithPerimeter: AMLStudioUIPrivate == false ? true : false
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
    ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32
    saName: storageAccount2001Name
    kvName: keyvaultName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    appInsightsName: applicationInsightName
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR should exist from previous phases
  ]
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
var miPrjName_Static = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${aifactorySalt10char}${resourceSuffix}'
resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: miPrjName_Static
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}
#disable-next-line BCP318
var var_miPrj_PrincipalId = miPrjREF.properties.principalId

module spAndMI2ArrayModule '../modules/spAndMiArray.bicep' = {
  name: '06-spAndMI2Array-${targetResourceGroup}'
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


// RBAC for Azure ML
module rbacAmlv2 '../modules/rbacStorageAml.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-rbacUsersAmlV2${deploymentProjSpecificUniqueSuffix}'
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
  ]
}

// ============== AI FOUNDRY V2 - 2025 ==============

// Dynamically build array of models to deploy based on parameters
var aiModels = concat(
  deployModel_gpt_4 ? [{
    modelName: modelGPT4Name
    version: modelGPT4Version
    capacity: default_gpt_capacity
    skuLocation: default_model_sku
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

//var privateDnsZonesResourceIds: networkIsolation ? [ 
  //cognitiveServicesPrivateDnsZone.outputs.resourceId
  //    openAiPrivateDnsZone.outputs.resourceId
//    ] : []


var aiFoundryZones = !enablePublicAccessWithPerimeter? [
  privateLinksDnsZones.openai.id
  privateLinksDnsZones.cognitiveservices.id
] : []

// Role assignments are now managed in 07-rbac-security.bicep
// We use deployment scripts to update permissions if needed after deployment
module aiFoundry2025 '../modules/csFoundry/aiFoundry2025.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-AifV2_${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV2Name
    defaultProjectName: aifV2ProjectName
    allowProjectManagement: true
    location:location
    // Provided subnet must be of the proper address space. Please provide a subnet which has address space in the range of 172 or 192
    agentSubnetResourceId: genaiSubnetId
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

// // Add the new FDP cognitive services module
module project '../modules/csFoundry/aiFoundry2025project.bicep' = if(enableAIFoundryV2) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-AifV2_Prj_${deploymentProjSpecificUniqueSuffix}'
  params: {
    cosmosDBname: serviceSettingDeployCosmosDB? namingConvention.outputs.cosmosDBName : ''
    name: aifV2ProjectName
    location: location
    storageName: namingConvention.outputs.storageAccount1001Name
    #disable-next-line BCP318
    aiFoundryV2Name: aiFoundry2025.outputs.name
    aiSearchName: enableAISearch ? namingConvention.outputs.safeNameAISearch : ''
    }
}
// ============== AI FOUNDRY HUB ==============

module aiHub '../modules/machineLearningAIHub.bicep' = if(!aiHubExists && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-aiHubModule${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: aifV1HubName
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: concat(
        !empty(miPrjName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)) : [],
        !empty(miACAName) ? array(resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miACAName)) : []
      )
    }
    defaultProjectName: aifV1ProjectName
    location: location
    tags: tagsProject
    aifactorySuffix: aifactorySuffixRG
    applicationInsightsName: applicationInsightName
    acrName: var_acr_cmn_or_prj
    acrRGName: useCommonACR ? commonResourceGroup : targetResourceGroup
    env: env
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
    ipRules: empty(processedIpRulesAIHub) ? [] : processedIpRulesAIHub
    ipWhitelist_array: empty(ipWhitelist_remove_ending_32) ? [] : ipWhitelist_remove_ending_32
  }
  dependsOn: [
    existingTargetRG
    // Dependencies handled through parameters - storage, keyvault, ACR, AI Search should exist from previous phases
  ]
}

// ============== RBAC FOR PROJECT-SPECIFIC ACR ==============

module rbacAcrProjectspecific '../modules/acrRbac.bicep' = if(useCommonACR == false && enableAIFoundryHub) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-rbacAcrProject${deploymentProjSpecificUniqueSuffix}'
  params: {
    acrName: var_acr_cmn_or_prj
    aiHubName: aifV1HubName
    aiHubRgName: targetResourceGroup
  }
  dependsOn: [
    ...(!aiHubExists && enableAIFoundryHub ? [aiHub] : [])
  ]
}

// ============== MACHINE LEARNING RBAC ==============

module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' = if(!amlExists && enableAzureMachineLearning) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: '06-rbacDBX2AMLGenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlName: amlName
    servicePrincipleAndMIArray: spAndMiArray
    adfSP: '' // ADF Service Principal - empty if not using ADF integration
    projectADuser: ''
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])
    logAnalyticsWorkspaceOpInsight
  ]
}

// ============== OUTPUTS - Simplified ==============
// Note: Outputs simplified to avoid conditional module reference issues
// Resource information should be retrieved through Azure CLI queries after deployment

@description('Azure ML Workspace deployment status')
output azureMLDeployed bool = (!amlExists && enableAzureMachineLearning)

@description('AI Foundry Hub deployment status')
output aiFoundryHubDeployed bool = (!aiHubExists && enableAIFoundryHub)

@description('AI Foundry Preview deployment status')
output aiFoundryv2Deployed bool = (!aifProjectExists && enableAIFoundryV2)

@description('Project-specific ACR RBAC deployment status')
output acrRbacDeployed bool = (useCommonACR == false && enableAIFoundryHub)

@description('ML Platform RBAC deployment status')
output mlPlatformRbacDeployed bool = (!amlExists && enableAzureMachineLearning)

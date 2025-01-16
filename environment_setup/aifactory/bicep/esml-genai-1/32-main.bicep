targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

param privateDnsAndVnetLinkAllGlobalLocation bool=true
param azureMachineLearningObjectId string =''
@description('If you want to use a common Azure Container Registry, in the AI Factory COMMON resourcegroup, set this to true')
param useCommonACR bool = false
param vmSKU string = 'standard_D2as_v5' // Kanske[standard_D2as_v5] - Ej ('Standard_DS3_v2')
// Cognitive Service types & settings
@allowed([
  'AIServices'
  'OpenAI'
  'ContentSafety'
])
param kindAOpenAI string = 'OpenAI'
param kindContentSafety string = 'ContentSafety'
param kindAIServices string = 'AIServices'
param apiVersionOpenAI string =  '2024-08-01-preview'
param modelVersionGPT4 string = 'turbo-2024-04-09' // GPT-4 Turbo with Vision https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models#o1-preview-and-o1-mini-models-limited-access
param modelVersionEmbedding string = 'text-embedding-3-large'
param modelVersionEmbeddingVersion string = '1'
param restore bool = false
param keyvaultEnablePurgeProtection bool = true // The property "enablePurgeProtection" cannot be set to false.

@allowed([
  'S0' // 'Free': Invalid SKU name
  'S1' // 'Basic': Invalid SKU name
  'standard'
  'standard2' // 0 out of 0 quota, is default, apply to get this.
])
param aiSearchSKUSharedPrivate string = 'standard' // Needed for shared Private Endpoints  https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity#shared-private-link-resource-limits
@allowed([
  'Free'
  'S0'
  'S1'
  'S2'
  'S3'
])
param csContentSafetySKU string = 'S0' // 'Basic' = S0
param csSpeechSKU string = 'S0'
param csVisionSKU string = 'S0'
param csDocIntelligenceSKU string = 'S0'
param csAIservicesSKU string = 'S0'
param csOpenAISKU string = 'S0'
@allowed([
  '1106-Preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
param modelGPT4Version string = '1106-Preview' // If your region doesn't support this version, please change it.


// ### FALSE as default - START ### 

// Standalone: Speech, Vision, DocIntelligence
@description('Service setting: Deploy Azure AI Document Intelligence for project')
param serviceSettingDeployAIDocIntelligence bool = false
@description('Service setting: Deploy Azure Speech for project')
param serviceSettingDeployAzureSpeech bool = false

// User access: standalone/Bastion
@description('Service setting: Deploy VM for project')
param serviceSettingDeployProjectVM bool = false
@description('Service setting:Deploy Azure Machine Learning - classic, not in hub mode')
param serviceSettingDeployAzureMLClassic bool = false

// UI and History in RAG
@description('Service setting:Deploy CosmosDB')
param serviceSettingDeployCosmosDB bool = false
@description('Service setting:Deploy Azure WebApp')
param serviceSettingDeployWebApp bool = false
@description('Service setting: Deploy Content Safety for project')
param serviceSettingDeployContentSafety bool = false
@description('Service setting: Deploy Azure OpenAI for project')
param serviceSettingDeployAzureOpenAI bool = false
// ### FALSE as default - END ### 

// ### TRUE as default - START ### 
@description('Service setting: Deploy Azure AI Vision for project')
param serviceSettingDeployAzureAIVision bool = true

// TODO: vnet in in other region, to create private endpoint, and then peer vNets
//p-prj001-aisearch-genai was not found. Please make sure that the referenced resource exists, and that both resources are in the same region.","
param serviceSettingOverrideRegionAzureAIVision string = ''
param serviceSettingOverrideRegionAzureAIVisionShort string = ''
param serviceSettingOverrideRegionAzureAISearch string = ''
param serviceSettingOverrideRegionAzureAISearchShort string = ''

@description('Service setting:Deploy Azure AI Search')
param serviceSettingDeployAzureAISearch bool = true
@description('Service setting:Deploy AIHub, e.g. Azure Machine Learning in AI hub mode, with AIServices and 1 project')
param serviceSettingDeployAIHub bool = true

// ### TRUE as default - END ###

@allowed([
  'disabled'
  'free'
  'standard'
])
param semanticSearchTier string = 'free' //   'disabled' 'free' 'standard'
@allowed([
  'S0' // 'Free': Invalid SKU name
  'S1' // 'Basic': Invalid SKU name
  'standard'
  'standard2' // 0 out of 0 quota, is default, apply to get this.
])
param aiSearchSKUName string = 'standard' // 'basic' gav error?  // 'basic' 'standard', 'standard2' if using sharedPrivateLinks ('S0,S1,standard,standard2')
param aiSearchEnableSharedPrivateLink bool = false
param aiSearchEnableSharedPrivateLink_DOCS string = 'https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity#shared-private-link-resource-limits'

@description('Default is false. May be needed if Azure OpenAI should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessForCognitive bool = true
@description('Default is false. May be needed if Azure AI Search, if it should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessForAISearch bool = false
@description('Default is false. May be needed if Azure Storage used by AI Search, if it should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessFoAIStorage bool = false
@description('Default is false. If true, it will flip all flags for GenAI RAG, such as Azure OpenAI, Azure AI Search, CosmosDB, WebApp, Azure Machine Learning')
param enablePublicGenAIAccess bool = false
@description('Default is true.')
param allowPublicAccessWhenBehindVnet bool = true

// Azure Machine Learning
param aks_dev_sku_override string = ''  // Override: AKS -  Azure Machine Learning
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1
param aml_ci_dev_sku_override string = '' // Override: AML Compute Instance -  Azure Machine Learning 
param aml_ci_test_prod_sku_override string = ''
param aml_cluster_dev_sku_override string = '' // Override: AML Compute Custer -  Azure Machine Learning 
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1
// Networking - AML

@description('Paramenter file dynamicNetworkParams.json contains this. Specifies the id of the AKS subnet that should be used by new AKS instance')
param aksSubnetId string
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'
// Azure Machine Learning - END

// Networking: GenAI 
@description('Paramenter file dynamicNetworkParams.json contains this. Written after dynamic IP calculation is done')
param genaiSubnetId string

// Seeding Keyvault & Bastion access
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvaultResourcegroup string
@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvaultSubscription string
@description('Private VM Bastion: saved to keyvault and used by local admin user on VM')
param adminPassword string
@description('Private VM Bastion:The username of the local admin that is created on VM')
param adminUsername string

// Metadata
@description('tags')
param tags object
param location string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string

// Metadata &  Dummy parameters, since same json parameterfile has more parameters than this bicep file
@description('Meta. Needed to calculate subnet: subnetCalc and genDynamicNetworkParamFile')
param vnetResourceGroupBase string // Meta
param addBastionHost bool= false // Dummy: Do not correspond to any parameters defined in the template: 'addBastionHost'

// Environment
@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string

// Performance
@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_ZRS'
  'Premium_LRS'
  'Premium_ZRS'
  'Standard_GZRS'
  'Standard_RAGRS'
  'Standard_RAGZRS'
])
@description('Specifies the SKU of the storage account')
param skuNameStorage string = 'Standard_ZRS'
@description('RBAC purposes:ObjectID to set Contributor on project resource group. ESML CoreTeam assigned to help project. Will be used for RBAC')

// RBAC
param technicalContactId string
@description('ESML CoreTeam assigned to help project. Specifies technical contact email and will be used for tagging')
param technicalContactEmail string
@description('RBAC: Specifies the tenant id')
param tenantId string

// RBAC: AzureDevops Variable Overrides
@description('Semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf". AzureDevops Variable Overrides')
param technicalAdminsObjectID string = 'null'
@description('Semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf". AzureDevops Variable Overrides.')
param technicalAdminsEmail string = 'null'
@description('Whitelist IP addresses from project members to see keyvault, and to connect via Bastion. AzureDevops Variable Overrides')
param IPwhiteList string = ''

@description('Name in keyvault for ObjectID of a user, service principal or security group in Microsoft EntraID. ') // OID: Get it by using Get-AzADUser or Get-AzADServicePrincipal cmdlet
param projectServicePrincipleOID_SeedingKeyvaultName string // Specifies the object ID of a user, service principal or security group in the Azure AD. The object ID must be unique for the list of access policies. 
@description('Project specific service principle KEYVAULT secret NAME to be added in kv for - Secret value ')
param projectServicePrincipleSecret_SeedingKeyvaultName string
@description('Project specific service principle KEYVAULT secret NAME for - App ID')
param projectServicePrincipleAppID_SeedingKeyvaultName string

// Networking
@description('Specifies the virtual network name')
param vnetNameBase string
@description('AI Factory suffix. If you have multiple instances example: -001')
param aifactorySuffixRG string
@description('Resources in common RG, the suffix on resources, example: -001')
param commonResourceSuffix string
@description('Resources in project RG, the suffix on resources, example: -001')
param resourceSuffix string
@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool

// Datalake
@description('Datalake GEN 2 storage account prefix. Max 8 chars.Example: If prefix is "marvel", then "marvelesml001[random5]dev",marvelesml001[random5]test,marvelesml001[random5]prod')
param commonLakeNamePrefixMax8chars string
@description('Datalake GEN 2 storage account')
param lakeContainerName string

// Metadata
@description('Specifies the tags2 that should be applied to newly created resources')
param projecttags object
@description('Specifies project owner email and will be used for tagging and RBAC')
param projectOwnerEmail string
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param projectOwnerId string
@description('not set in genai-1')
param databricksOID string = 'not set in genai-1'
@description('not set in genai-1')
param databricksPrivate bool = false
@description('not set in genai-1')
param AMLStudioUIPrivate bool = false

var subscriptionIdDevTestProd = subscription().subscriptionId
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('Common default subnet')
param common_subnet_name string // TODO - 31-network.bicep for own subnet
@description('True for centralized Private DNS Zones in HUB. False is default: that ESML run standalone/demo mode, which creates private DnsZones, DnsZoneGroups, and vNetLinks in own resource group. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false

// Networking & Overrides RG, vnet, datalakename, kvNameFromCOMMON
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''

// Parameters to variables
var vnetNameFull = vnetNameFull_param != '' ? vnetNameFull_param : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

// ESML convention (that you may override)
var projectName = 'prj${projectNumber}'
var cmnName = 'cmn'
var genaiName = 'genai'
var commonResourceGroup = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg'
var vnetResourceGroupName = vnetResourceGroup_param != '' ? vnetResourceGroup_param : commonResourceGroup
var subscriptions_subscriptionId = subscription().id
var vnetId = '${subscriptions_subscriptionId}/resourceGroups/${vnetResourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'

// Gen genaiSubnetName from genaiSubnetId which is resourceID
var segments = split(genaiSubnetId, '/')
var genaiSubnetName = segments[length(segments) - 1] // Get the last segment, which is the subnet name
var defaultSubnet = genaiSubnetName //common_subnet_name

// RBAC
var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var ipWhitelist_array = array(split(replace(IPwhiteList, '\\s+', ''), ','))
var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsObjectID_array_safe = (empty(technicalAdminsObjectID) || technicalAdminsObjectID == 'null') ? [] : technicalAdminsObjectID_array
var technicalAdminsEmail_array_safe = (empty(technicalAdminsEmail) || technicalAdminsEmail == 'null') ? [] : technicalAdminsEmail_array

// Other - uniquness, Keyvault name
var deploymentProjSpecificUniqueSuffix = '${projectName}${genaiName}${locationSuffix}${env}${aifactorySuffixRG}'

// Networking - Private DNS
var privDnsResourceGroupName = privDnsResourceGroup_param != '' ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = privDnsSubscription_param != '' ? privDnsSubscription_param : subscriptionIdDevTestProd

// 2024-09-15: 25 entries, and special keyes
var privateDnsZoneName =  {
  azureusgovernment: 'privatelink.api.ml.azure.us'
  azurechinacloud: 'privatelink.api.ml.azure.cn'
  azurecloud: 'privatelink.api.azureml.ms'
}

var privateAznbDnsZoneName = {
    azureusgovernment: 'privatelink.notebooks.usgovcloudapi.net'
    azurechinacloud: 'privatelink.notebooks.chinacloudapi.cn'
    azurecloud: 'privatelink.notebooks.azure.net'
}

// 2024-09-15: 25 entries
var privateLinksDnsZones = {
  blob: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.${environment().suffixes.storage}'
    name:'privatelink.blob.${environment().suffixes.storage}'
  }
  file: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.file.${environment().suffixes.storage}'
    name:'privatelink.file.${environment().suffixes.storage}'
  }
  dfs: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.dfs.${environment().suffixes.storage}'
    name:'privatelink.dfs.${environment().suffixes.storage}'
  }
  queue: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.queue.${environment().suffixes.storage}'
    name:'privatelink.queue.${environment().suffixes.storage}'
  }
  table: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.table.${environment().suffixes.storage}'
    name:'privatelink.table.${environment().suffixes.storage}'
  }
  registry: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azurecr.io' // privatelink.${environment().suffixes.acrLoginServer}' // # E
    name:'privatelink.azurecr.io'
  }
  registryregion: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${location}.data.privatelink.azurecr.io' // privatelink.${environment().suffixes.acrLoginServer}' // # E
    name:'${location}.data.privatelink.azurecr.io'
  }
  vault: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
    name:'privatelink.vaultcore.azure.net'
  }
  amlworkspace: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateDnsZoneName[toLower(environment().name)]}' //# E
    name: privateDnsZoneName[toLower(environment().name)]
  }
  notebooks: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateAznbDnsZoneName[toLower(environment().name)]}' 
    name:privateAznbDnsZoneName[toLower(environment().name)]
  }
  dataFactory: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.datafactory.azure.net' // # E
    name:'privatelink.datafactory.azure.net'
  }
  portal: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.adf.azure.com' 
    name:'privatelink.adf.azure.com'
  }
  openai: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com'
    name:'privatelink.openai.azure.com'
  }
  searchService: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.search.windows.net'
    name:'privatelink.search.windows.net'
  }
  azurewebapps: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net'
    name:'privatelink.azurewebsites.net'
  }
  cosmosdbnosql: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.documents.azure.com'
    name:'privatelink.documents.azure.com'
  }
  cognitiveservices: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.cognitiveservices.azure.com'
    name:'privatelink.cognitiveservices.azure.com'
  }
  azurewebappsscm: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/scm.privatelink.azurewebsites.net'
    name:'scm.privatelink.azurewebsites.net'
  }
  azuredatabricks: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.azuredatabricks.net'
    name:'privatelink.azuredatabricks.net'
  }
  namespace: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.servicebus.windows.net'
    name:'privatelink.servicebus.windows.net'
  }
  azureeventgrid: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.eventgrid.azure.net'
    name:'privatelink.eventgrid.azure.net'
  }
  azuremonitor: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com'
    name:'privatelink.monitor.azure.com'
  }
  azuremonitoroms: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com'
    name:'privatelink.oms.opinsights.azure.com'
  }
  azuremonitorods: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com'
    name:'privatelink.ods.opinsights.azure.com'
  }
  azuremonitoragentsvc: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net'
    name:'privatelink.agentsvc.azure-automation.net'
  }
}

var privateLinksDnsZonesArray = [
  {
    name: privateLinksDnsZones.blob.name
    id: privateLinksDnsZones.blob.id
  }
  {
    name: privateLinksDnsZones.file.name
    id: privateLinksDnsZones.file.id
  }
  {
    name: privateLinksDnsZones.dfs.name
    id: privateLinksDnsZones.dfs.id
  }
  {
    name: privateLinksDnsZones.queue.name
    id: privateLinksDnsZones.queue.id
  }
  {
    name: privateLinksDnsZones.table.name
    id: privateLinksDnsZones.table.id
  }
  {
    name: privateLinksDnsZones.registry.name
    id: privateLinksDnsZones.registry.id
  }
  {
    name: privateLinksDnsZones.registryregion.name
    id: privateLinksDnsZones.registryregion.id
  }
  {
    name: privateLinksDnsZones.vault.name
    id: privateLinksDnsZones.vault.id
  }
  {
    name: privateLinksDnsZones.amlworkspace.name
    id: privateLinksDnsZones.amlworkspace.id
  }
  {
    name: privateLinksDnsZones.notebooks.name
    id: privateLinksDnsZones.notebooks.id
  }
  {
    name: privateLinksDnsZones.dataFactory.name
    id: privateLinksDnsZones.dataFactory.id
  }
  {
    name: privateLinksDnsZones.portal.name
    id: privateLinksDnsZones.portal.id
  }
  {
    name: privateLinksDnsZones.openai.name
    id: privateLinksDnsZones.openai.id
  }
  {
    name: privateLinksDnsZones.searchService.name
    id: privateLinksDnsZones.searchService.id
  }
  {
    name: privateLinksDnsZones.azurewebapps.name
    id: privateLinksDnsZones.azurewebapps.id
  }
  {
    name: privateLinksDnsZones.cosmosdbnosql.name
    id: privateLinksDnsZones.cosmosdbnosql.id
  }
  {
    name: privateLinksDnsZones.cognitiveservices.name
    id: privateLinksDnsZones.cognitiveservices.id
  }
  {
    name: privateLinksDnsZones.azurewebappsscm.name
    id: privateLinksDnsZones.azurewebappsscm.id
  }
  {
    name: privateLinksDnsZones.azuredatabricks.name
    id: privateLinksDnsZones.azuredatabricks.id
  }
  {
    name: privateLinksDnsZones.namespace.name
    id: privateLinksDnsZones.namespace.id
  }
  {
    name: privateLinksDnsZones.azureeventgrid.name
    id: privateLinksDnsZones.azureeventgrid.id
  }
  {
    name: privateLinksDnsZones.azuremonitor.name
    id: privateLinksDnsZones.azuremonitor.id
  }
  {
    name: privateLinksDnsZones.azuremonitoroms.name
    id: privateLinksDnsZones.azuremonitoroms.id
  }
  {
    name: privateLinksDnsZones.azuremonitorods.name
    id: privateLinksDnsZones.azuremonitorods.id
  }
  {
    name: privateLinksDnsZones.azuremonitoragentsvc.name
    id: privateLinksDnsZones.azuremonitoragentsvc.id
  }
]

output privateLinksDnsZones object = privateLinksDnsZones

module createPrivateDnsZones '../modules/createPrivateDnsZones.bicep' = if(centralDnsZoneByPolicyInHub==false) {
  scope: resourceGroup(subscriptionIdDevTestProd,privDnsResourceGroupName)
  name: 'createPrivateDnsZones${deploymentProjSpecificUniqueSuffix}'
  params: {
    privateLinksDnsZones: privateLinksDnsZonesArray
    privDnsSubscription: privDnsSubscription
    privDnsResourceGroup: privDnsResourceGroupName
    vNetName: vnetNameFull
    vNetResourceGroup: vnetResourceGroupName
    location: location
    allGlobal:privateDnsAndVnetLinkAllGlobalLocation
  }
}


// Resource Groups
module projectResourceGroup '../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'prjRG${deploymentProjSpecificUniqueSuffix}'
  params: {
    rgName: targetResourceGroup
    location: location
    tags: tags
  }
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'

// ------------------------------ RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

module vmAdminLoginPermissions '../modules/vmAdminLoginRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'VMAdminLogin4${deploymentProjSpecificUniqueSuffix}'
  params: {
    userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserEmails: technicalAdminsEmail_array_safe
    additionalUserIds:technicalAdminsObjectID_array_safe
  }
  dependsOn:[
    projectResourceGroup
    rbacModuleUsers
  ]
}

// ------------------------------ END:RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

// ----DATALAKE
// ------------------------------ SERVICES - AI Studio, Azure OpenAI, Azure AI Search, Storage for Azure AI Search, Azure Content Safety ------------------------------//

module csContentSafety '../modules/csContentSafety.bicep' = if(serviceSettingDeployContentSafety==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'ContentSafety4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csContentSafetySKU
    location: location
    restore:restore
    vnetResourceGroupName: vnetResourceGroupName
    contentsafetyName: 'cs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: kindContentSafety
    pendCogSerName: 'p-${projectName}-contentsafety-${genaiName}'
    subnetName:genaiSubnetName
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsContentSafety '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployContentSafety == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkContentSafety${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csContentSafety.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module csVision '../modules/csVision.bicep' = if(serviceSettingDeployAzureAIVision==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Vision4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csVisionSKU
    location: (!empty(serviceSettingOverrideRegionAzureAIVision)) ? serviceSettingOverrideRegionAzureAIVision : location
    restore:restore
    keyvaultName: keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: (!empty(serviceSettingOverrideRegionAzureAIVisionShort))? 'vision-${projectName}-${serviceSettingOverrideRegionAzureAIVisionShort}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    :'vision-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'ComputerVision'
    pendCogSerName: 'p-${projectName}-vision-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsVision '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureAIVision == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsVision ${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csVision.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module csSpeech '../modules/csSpeech.bicep' = if(serviceSettingDeployAzureSpeech==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AISpeech4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csSpeechSKU
    location: location
    restore:restore
    keyvaultName: kv1.outputs.keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: 'speech-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'SpeechServices'
    pendCogSerName: 'p-${projectName}-speech-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsSpeech '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAzureSpeech == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsLinkSpeech${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csSpeech.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}


module csDocIntelligence '../modules/csDocIntelligence.bicep' = if(serviceSettingDeployAIDocIntelligence==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AIDocIntelligence4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csDocIntelligenceSKU
    location: location
    restore:restore
    keyvaultName: kv1.outputs.keyvaultName
    vnetResourceGroupName: vnetResourceGroupName
    name: 'docs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    kind: 'FormRecognizer'
    pendCogSerName: 'p-${projectName}-docs-${genaiName}'
    subnetName:defaultSubnet
    vnetName: vnetNameFull
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
    kv1
  ]
}

module privateDnsDocInt '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && serviceSettingDeployAIDocIntelligence == true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsDocInt${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csDocIntelligence.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}


// """"" Azure AI Services """"""
module aiServices '../modules/csAIServices.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AIServices4${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    sku: csAIservicesSKU
    tags: tags
    vnetResourceGroupName: vnetResourceGroupName
    cognitiveName: 'ai-services-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${prjResourceSuffixNoDash}'
    pendCogSerName: 'p-${projectName}-aiservices-${genaiName}'
    restore: restore
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    keyvaultName: kv1.outputs.keyvaultName
    modelGPT4Version:modelGPT4Version
    kind: kindAIServices
    acrNameDummy: useCommonACR? acrCommon2.name:acr.name // Workaround for conditional "dependsOn"
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
      //'${vnetId}/subnets/snt-${projectName}-aks'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    disableLocalAuth: false
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    projectResourceGroup
    sacc
    kv1
    //acr
    //acrCommon2
  ]
}

// cog-prj003-sdc-dev-3pmpb-001
module csAzureOpenAI '../modules/csOpenAI.bicep' = if(serviceSettingDeployAzureOpenAI==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AzureOpenAI4${deploymentProjSpecificUniqueSuffix}'
  params: {
    cognitiveName:'aoai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    tags: tags
    laWorkspaceName:laName
    restore:restore
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    sku: csOpenAISKU
    vnetName: vnetNameFull
    subnetName: genaiSubnetName
    keyvaultName: kv1.outputs.keyvaultName
    modelGPT4Version:modelGPT4Version
    aiSearchPrincipalId: aiSearchService.outputs.principalId
    kind: kindAOpenAI
    pendCogSerName: 'p-${projectName}-openai-${genaiName}'
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive
    disableLocalAuth:true
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
    kv1
  ]
}


module privateDnsAzureOpenAI '../modules/privateDns.bicep' = if(serviceSettingDeployAzureOpenAI==true && centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLinkAOAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: csAzureOpenAI.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module diagnosticSettingOpenAI '../modules/diagnosticSettingCognitive.bicep' = if(serviceSettingDeployAzureOpenAI==true && centralDnsZoneByPolicyInHub==false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'diagOpenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: csAzureOpenAI.outputs.cognitiveName
    logAnalyticsWorkspaceOpInsightResourceId: logAnalyticsWorkspaceOpInsight.id
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// LogAnalytics
var laName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
//resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
//resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {

resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laName
  scope:commonResourceGroupRef
}

// Azure OpenAI - END
// Azure AI Search

 //Deploys AI Search with private endpoints and shared private link connections
 var sharedPrivateLinkResources = [
  // First storage account with 'blob' groupId
  {
    groupId: 'blob'
    status: 'Approved'
    provisioningState: 'Succeeded'
    requestMessage: 'created using the Bicep template'
    privateLinkResourceId: sa4AIsearch.outputs.storageAccountId
  }
  // Second storage account with 'blob' groupId
  {
    groupId: 'blob'
    status: 'Approved'
    provisioningState: 'Succeeded'
    requestMessage:  'created using the Bicep template'
    privateLinkResourceId: sacc.outputs.storageAccountId
  }
  /* First OpenAI resource with 'openai' groupId
  {
    groupId: 'openai_account'
    status: 'Approved'
    provisioningState: 'Succeeded'
    requestMessage: 'created using the Bicep template'
    privateLinkResourceId: csAzureOpenAI.outputs.cognitiveId
  }
    */
  // Second OpenAI resource with 'openai' groupId
  {
    groupId: 'cognitiveservices_account'
    status: 'Approved'
    provisioningState: 'Succeeded'
    requestMessage:  'created using the Bicep template'
    privateLinkResourceId: aiServices.outputs.resourceId
  }
]

var safeNameAISearch = replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}') ,'-','')

module aiSearchService '../modules/aiSearch.bicep' = if (serviceSettingDeployAzureAISearch==true) {
  name: 'AzureAISearch4${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    aiSearchName: (!empty(serviceSettingOverrideRegionAzureAISearchShort)) ? replace(toLower('aisearch${projectName}${serviceSettingOverrideRegionAzureAISearchShort}${env}${uniqueInAIFenv}${resourceSuffix}') ,'-','')
    : replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}') ,'-','')
    location: (!empty(serviceSettingOverrideRegionAzureAISearch)) ? serviceSettingOverrideRegionAzureAISearch : location
    replicaCount: 1
    partitionCount: 1
    privateEndpointName: 'p-${projectName}-aisearch-${genaiName}'
    vnetId: vnetId
    subnetName: defaultSubnet
    tags: tags
    semanticSearchTier: (location != 'swedencentral')? semanticSearchTier: 'disabled'
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForAISearch
    skuName: aiSearchSKUName //enablePublicGenAIAccess? aiSearchSKUName: aiSearchSKUSharedPrivate
    enableSharedPrivateLink:aiSearchEnableSharedPrivateLink
    sharedPrivateLinks:sharedPrivateLinkResources
    acrNameDummy: useCommonACR? acrCommon2.name:acr.name // Workaround for conditional "dependsOn"
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsAiSearchService '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false && serviceSettingDeployAzureAISearch==true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA1${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: aiSearchService.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// Azure AI Search - END

// Storage for Azure AI Search

module sa4AIsearch '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'GenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}2${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}'
    tags: tags
    networkAcls: networkAcls
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.swedencentral.instances.azureml.ms'
          'https://*.instances.azureml.ms'
          'https://*.azureml.ms'
        ]
        allowedMethods: [
          'GET'
          'HEAD'
          'POST'
          'PUT'
          'DELETE'
          'OPTIONS'
          'PATCH'
        ]
        maxAgeInSeconds: 1800
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsStorageGenAI '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA2${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sa4AIsearch.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// Storage for Azure AI Search - END

// ------------------------------ Azure ML dependency- Keyvault, VM, Azure container registry, Loganalytics, AppInsights ------------------------------//

// Related to Azure Machine Learning: Cointainer Registry, Storage Account, KeyVault, LogAnalytics, ApplicationInsights
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
module acr '../modules/containerRegistry.bicep' = if (useCommonACR == false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: 'acr${projectName}${genaiName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
    skuName: 'Premium'
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}${locationSuffix}-containerreg-to-vnt-mlcmn'
    tags: tags
    location:location
  }

  dependsOn: [
    projectResourceGroup
  ]
}

var acrCommonName = 'acrcommon${uniqueInAIFenv}${locationSuffix}${commonResourceSuffix}${env}'
var acrCommonNameSafe = replace(acrCommonName,'-','')

resource acrCommon 'Microsoft.ContainerRegistry/registries@2021-09-01' existing = if (useCommonACR == true) {
  name: acrCommonNameSafe
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
}

// Update simulation - since: "ACR sku cannot be retrieved because of internal error."
// pend-acr-cmnsdc-containerreg-to-vnt-mlcmn
module acrCommon2 '../modules/containerRegistry.bicep' = if (useCommonACR == true){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'AMLGenaIContReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: acrCommonNameSafe
    skuName: 'Premium'
    vnetId: vnetId
    subnetName: common_subnet_name // snet-esml-cmn-001
    privateEndpointName: 'pend-acr-cmn${locationSuffix}-containerreg-to-vnt-mlcmn' // snet-esml-cmn-001
    tags: acrCommon.tags
    location:acrCommon.location
  }

  dependsOn: [
    acrCommon
  ]
}

param networkAcls object = {
  bypass: 'AzureServices'
  defaultAction: 'Allow'
}

module sacc '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLGenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}1${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}ml'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}ml'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}ml'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}ml'
    tags: tags
    networkAcls: networkAcls
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    vnetRules: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    ipRules: [for ip in ipWhitelist_array: {
      value: ip
    }] // https://mlworkspace.azure.ai,https://ml.azure.com,https://*.ml.azure.com,https://ai.azure.com,https://*.ai.azure.com,https://mlworkspacecanary.azure.ai,https://mlworkspace.azureml-test.net,https://*.azureml.ms,https://42.swedencentral.instances.azureml.ms,https://*.instances.azureml.ms
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
          'https://42.swedencentral.instances.azureml.ms'
          'https://*.instances.azureml.ms'
          'https://*.azureml.ms'
        ]
        allowedMethods: [
          'GET'
          'HEAD'
          'POST'
          'PUT'
          'DELETE'
          'OPTIONS'
          'PATCH'
        ]
        maxAgeInSeconds: 1800
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module kv1 '../modules/keyVault.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMGenAILKeyV4${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: tags
    enablePurgeProtection:keyvaultEnablePurgeProtection
    tenantIdentity: tenantId
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    accessPolicies: [] 
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
  }
  dependsOn: [
    projectResourceGroup
  ]
}


module applicationInsightSWC '../modules/applicationInsightsRGmode.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
    logWorkspaceName: laName
    logWorkspaceNameRG: commonResourceGroup
    //logAnalyticsWorkspaceID:logAnalyticsWorkspaceOpInsight.id
    tags: tags
    location: location
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module vmPrivate '../modules/virtualMachinePrivate.bicep' = if(serviceSettingDeployProjectVM == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: vmSKU
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: tags
    keyvaultName: kv1.outputs.keyvaultName
  }

  dependsOn: [
    projectResourceGroup
    csContentSafety
    aiServices
  ]
}

// ------------------------------ SERVICES (GenaI) - Azure OpenAI, AI Search, CosmosDB, WebApp ------------------------------//


// ------------------------------ END - SERVICES (GenaI) - Azure OpenAI, AI Search, CosmosDB, WebApp ------------------------------//



// Seeding Keyvault - Copy secrets to project keyvault
resource externalKv 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription,inputKeyvaultResourcegroup)
}

module addSecret '../modules/kvSecretsPrj.bicep' = {
  name: '${keyvaultName}Secrect2Proj${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    spAppIDValue:externalKv.getSecret(projectServicePrincipleAppID_SeedingKeyvaultName) //projectServicePrincipleAppID_SeedingKeyvaultName 
    spOIDValue: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)  // projectServicePrincipleOID_SeedingKeyvaultName

    spSecretValue: externalKv.getSecret(projectServicePrincipleSecret_SeedingKeyvaultName)
    keyvaultName: kv1.outputs.keyvaultName
  }
  dependsOn: [
    aiServices
  ]
}

// Access Policies and fetching secrets to project keyvault
var secretGetListSet = {
  secrets: [ 
    'get'
    'list'
    'set'
  ]
}
var secretGetList = {
  secrets: [ 
    'get'
    'list'
  ]
}
var secretGet = {
  secrets: [ 
    'get'
  ]
}

// PROJECT Keyvault where technicalContactId GET,LIST, SET
module kvCmnAccessPolicyTechnicalContactAll '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: '${keyvaultName}AccessPol${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetListSet
    keyVaultResourceName: kv1.outputs.keyvaultName
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    addSecret
    aiServices
  ]
}

// COMMON Keyvault where technicalContactId GET,LIST
var kvNameCommon = kvNameFromCOMMON_param != '' ? kvNameFromCOMMON_param : 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource commonKv 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: kvNameCommon
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
}

module kvCommonAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: '${kvNameCommon}GetList${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kvNameCommon
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    commonKv
    aiServices
  ]
}

module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'spGetList${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: commonKv.name
    policyName: 'add'
    principalId: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds:[]
  }
  dependsOn: [
    commonKv
    kv1
    aiServices
    aiHub // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

// Configure Private DNS Zones, if standalone AIFactory. (othwerwise the HUB DNS Zones will be used, and via policy auomatically create A-records in HUB DNS Zones)

module privateDnsStorage '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA3${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sacc.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}
module privateDnsKeyVault '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDnZoneKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: kv1.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}
module privateDnsContainerRegistry '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false && useCommonACR == false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDnsZACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: acr.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// ------------------------------ SERVICES (Azure Machine Learning)  ------------------------------//
var amlName ='aml-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var aksSubnetName  = 'snt-prj${projectNumber}-aks'

// AKS: NB! Standard_D12 is not allowed in WE for agentpool   [standard_a4_v2]
param aks_dev_defaults array = [
  'Standard_B4ms' // 4 cores, 16GB, 32GB storage: Burstable (2022-11 this was the default in Azure portal)
  'Standard_A4m_v2' // 4cores, 32GB, 40GB storage (quota:100)
  'Standard_D3_v2' // 4 cores, 14GB RAM, 200GB storage
] 

param aks_testProd_defaults array = [
  'Standard_DS13-2_v2' // 8 cores, 14GB, 112GB storage
  'Standard_A8m_v2' // 8 cores, 64GB RAM, 80GB storage (quota:100)
]

param aml_dev_defaults array = [
  'Standard_DS3_v2' // 	4 cores, 14GB ram, 28GB storage = 0.27$ [Classical ML model training on small datasets]
  'Standard_F8s_v2' //  (8,16,64) 0.39$
  'Standard_DS12_v2' // 4 cores, 28GB RAM, 56GB storage = 0.38 [Data manipulation and training on medium-sized datasets (1-10GB)
]

param aml_testProd_defaults array = [
  'Standard_D13_v2' // 	(8 cores, 56GB, 400GB storage) = 0.76$ [Data manipulation and training on large datasets (>10 GB)]
  'Standard_D4_v2' // (8 cores, 28GB RAM, 400GB storage) = 0.54$
  'Standard_F16s_v2' //  (16 cores, 32GB RAM, 128GB storage) = 0.78$
]

param ci_dev_defaults array = [
  'Standard_DS11_v2' // 2 cores, 14GB RAM, 28GB storage
]
param ci_devTest_defaults array = [
  'Standard_D11_v2'
]

// AML AKS Cluster: defaults & overrides
var aks_dev_sku_param = aks_dev_sku_override != '' ? aks_dev_sku_override : aks_dev_defaults[0]
var aks_test_prod_sku_param = aks_test_prod_sku_override != '' ? aks_test_prod_sku_override : aks_testProd_defaults[0]

var aks_version_param = aks_version_override != '' ? aks_version_override :'1.30.3' //2024-09-05 did not work in SDC: '1.27.9' // 2024-03-14 LTS Earlier: (1.27.3 | 2024-01-25 to 2024-03-14) az aks get-versions --location westeurope --output table). Supported >='1.23.5'
var aks_dev_nodes_param = aks_dev_nodes_override != -1 ? aks_dev_nodes_override : 1
var aks_test_prod_nodes_param = aks_test_prod_nodes_override != -1 ? aks_test_prod_nodes_override : 3

// AML Compute Instance: defaults & overrides
var aml_ci_dev_sku_param = aml_ci_dev_sku_override != '' ? aml_ci_dev_sku_override : ci_dev_defaults[0]
var aml_ci_test_prod_sku_param = aml_ci_test_prod_sku_override != '' ? aml_ci_test_prod_sku_override : ci_devTest_defaults[0]

// AML cluster: defaults & overrides
var aml_cluster_dev_sku_param = aml_cluster_dev_sku_override != '' ? aml_cluster_dev_sku_override : aml_dev_defaults[0]
var aml_cluster_test_prod_sku_param = aml_cluster_test_prod_sku_override != '' ? aml_cluster_test_prod_sku_override : aml_testProd_defaults[1]
var aml_cluster_dev_nodes_param = aml_cluster_dev_nodes_override != -1 ? aml_cluster_dev_nodes_override : 3
var aml_cluster_test_prod_nodes_param = aml_cluster_test_prod_nodes_override != -1 ? aml_cluster_test_prod_nodes_override : 3

module aml '../modules/machineLearning.bicep'= if(serviceSettingDeployAzureMLClassic == true)  {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'MLClassic4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: amlName
    uniqueDepl: deploymentProjSpecificUniqueSuffix
    uniqueSalt5char: uniqueInAIFenv
    projectName:projectName
    projectNumber:projectNumber
    location: location
    locationSuffix:locationSuffix
    aifactorySuffix: aifactorySuffixRG
    skuName: 'basic'
    skuTier: 'basic'
    env:env
    saName : sacc.outputs.storageAccountName
    acrName:useCommonACR? acrCommon2.outputs.containerRegistryName:acr.outputs.containerRegistryName
    acrRGName: useCommonACR? commonResourceGroup: targetResourceGroup
    kvName: kv1.outputs.keyvaultName
    appInsightsName: applicationInsightSWC.outputs.name
    aksSubnetId: aksSubnetId
    aksSubnetName:aksSubnetName
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: tags
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml${genaiName}-to-vntcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID:privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet:allowPublicAccessWhenBehindVnet
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
    aksVmSku_dev: aks_dev_sku_param
    aksVmSku_testProd: aks_test_prod_sku_param
    aksNodes_dev:aks_dev_nodes_param
    aksNodes_testProd:aks_test_prod_nodes_param
    kubernetesVersionAndOrchestrator:aks_version_param
    amlComputeDefaultVmSize_dev: aml_cluster_dev_sku_param
    amlComputeDefaultVmSize_testProd: aml_cluster_test_prod_sku_param
    amlComputeMaxNodex_dev: aml_cluster_dev_nodes_param
    amlComputeMaxNodex_testProd: aml_cluster_test_prod_nodes_param
    ciVmSku_dev: aml_ci_dev_sku_param
    ciVmSku_testProd: aml_ci_test_prod_sku_param
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]

  }

  dependsOn: [
    projectResourceGroup
  ]
  
}

var aiHubName ='ai-hub-${projectName}-${locationSuffix}-${env}${resourceSuffix}'

module aiHub '../modules/machineLearningAIHub.bicep' = if(serviceSettingDeployAIHub == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: aiHubName
  params: {
    name: aiHubName
    location: location
    tags: tags
    aifactorySuffix: aifactorySuffixRG
    applicationInsightsName: applicationInsightSWC.outputs.name
    containerRegistry: useCommonACR? acrCommon2.outputs.containerRegistryId:acr.outputs.containerRegistryId
    env: env
    keyVaultName: kv1.outputs.keyvaultName
    privateEndpointName:'p-aihub-${projectName}${locationSuffix}${env}${genaiName}amlworkspace'
    aifactoryProjectNumber: projectNumber
    //skuName: 'basic'
    //skuTier: 'basic'
    storageAccount: sacc.outputs.storageAccountId
    subnetName: defaultSubnet
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess:enablePublicGenAIAccess
    aiSearchName: aiSearchService.outputs.aiSearchName
    privateLinksDnsZones: privateLinksDnsZones
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    kindAIHub:'Hub'
    //openAiResourceName:csAzureOpenAI.outputs.cognitiveName
    aiServicesName: aiServices.outputs.name
    logWorkspaceName:logAnalyticsWorkspaceOpInsight.name
    logWorkspaceResoureGroupName:commonResourceGroup
    locationSuffix:locationSuffix
    resourceSuffix:resourceSuffix
    ipRules: [for ip in ipWhitelist_array: {
      action: 'Allow'
      value: ip
    }]
    ipWhitelist_array: ipWhitelist_array
  }
  dependsOn: [
    projectResourceGroup
    aiServices
    aiSearchService
  ]
}

/* // RoleAssignmentUpdateNotPermitted
module rbacAcrCommonRG '../modules/acrRbac.bicep' = if(useCommonACR == true) {
  scope:commonResourceGroupRef
  name: 'rbacAcrCommon${deploymentProjSpecificUniqueSuffix}'
  params: {
    acrName: acrCommon2.outputs.containerRegistryName
    aiHubName: aiHub.outputs.name
    aiHubRgName: targetResourceGroup
  }
}

*/
module rbacAcrProjectspecific '../modules/acrRbac.bicep' = if(useCommonACR == false) {
  scope:resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacAcrProject${deploymentProjSpecificUniqueSuffix}'
  params: {
    acrName: acr.outputs.containerRegistryName
    aiHubName: aiHub.outputs.name
    aiHubRgName: targetResourceGroup
  }
}

module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' = if(serviceSettingDeployAzureMLClassic == true)  {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX2AMLGenAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlName:amlName
    projectSP:externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    adfSP:'null' // this duplicate will be ignored
    projectADuser:technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    kv1
    aiHub
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    //aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

// ------------------------------ END - SERVICES (Azure Machine Learning)  ------------------------------//

module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacGenAIReadUsersToCmnKeyvault${projectNumber}${locationSuffix}${env}'
  params: {
    common_kv_name:'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    user_object_ids: technicalAdminsObjectID_array_safe
    bastion_service_name: 'bastion-${locationSuffix}-${env}${commonResourceSuffix}'  // bastion-uks-dev-001
  }
  dependsOn: [
    csAzureOpenAI
    kv1
    rbacReadUsersToCmnVnetBastion
  ]
}

// ------------------- RBAC for AI Studio (AIServices) service pricipal, to services ---------------//
// -- DOCS: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/use-your-data-securely#create-shared-private-link --//

var targetResourceGroupId = resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', targetResourceGroup)

module rbacForOpenAI'../modules/aihubRbacOpenAI.bicep' = if (serviceSettingDeployAzureAISearch==true && serviceSettingDeployAzureOpenAI==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacOpenAIDeployESMLAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiSearchName: aiSearchService.outputs.aiSearchName
    openAIServicePrincipal:csAzureOpenAI.outputs.principalId
    servicePrincipleObjecId:externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    openAIName:csAzureOpenAI.outputs.cognitiveName
    userObjectIds:technicalAdminsObjectID_array_safe
  }
}
// 6 assignments: OK
module rbacModuleAIServices '../modules/aihubRbacAIServices.bicep' = if(serviceSettingDeployAzureAISearch==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacAIServices_DeployAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiSearchName: aiSearchService.outputs.aiSearchName
    aiServicesPrincipalId:aiServices.outputs.aiServicesPrincipalId
  }
}

// 5 assignments: OK
module rbacModuleAISearch '../modules/aihubRbacAISearch.bicep' = if(serviceSettingDeployAzureAISearch==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacSearch_DeployAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiServicesName:aiServices.outputs.name
    aiSearchMIObjectId: aiSearchService.outputs.principalId
  }
  dependsOn: [
    aiHub
    rbacModuleAIServices
  ]
}

module rbacAihubRbacAmlRG '../modules/aihubRbacAmlRG.bicep'= if (!empty(azureMachineLearningObjectId)) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacAml2RG_DeployAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    azureMachineLearningObjectId: azureMachineLearningObjectId
  }
  dependsOn: [
    aiHub
  ]
}

module rbacModuleUsers '../modules/aihubRbacUsers.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacUsersAIHub_DeployAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiSearchName: aiSearchService.outputs.aiSearchName
    resourceGroupId: targetResourceGroupId
    userObjectIds: technicalAdminsObjectID_array_safe
    aiServicesName:aiServices.outputs.name
    aiHubName:aiHub.outputs.name
    aiHubProjectName:aiHub.outputs.aiProjectName
    servicePrincipleObjectId:externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    aiHub
    rbacModuleAISearch
  ]
}


// #### OPTIONAL ####

module rbacVision '../modules/aihubRbacVision.bicep' = if(serviceSettingDeployAzureAIVision==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacVisionDeployESMLAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiVisionMIObjectId: csVision.outputs.principalId
    userObjectIds: technicalAdminsObjectID_array_safe
    visonServiceName: csVision.outputs.name
  }
}

module rbacSpeech '../modules/aihubRbacSpeech.bicep' = if(serviceSettingDeployAzureSpeech==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacSpeechDeployESMLAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiSpeechMIObjectId: csSpeech.outputs.principalId
    userObjectIds: technicalAdminsObjectID_array_safe
    speechServiceName: csSpeech.outputs.name
  }
}
module rbacDocs '../modules/aihubRbacDoc.bicep' = if(serviceSettingDeployAIDocIntelligence==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacSpeechDeployESMLAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    userObjectIds: technicalAdminsObjectID_array_safe
    aiDocsIntelMIObjectId: csDocIntelligence.outputs.principalId
    docsServiceName: csDocIntelligence.outputs.name
  }
}

/*
module rbacModuleWebApp'../modules/aihubRbacAIWebApp.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDeployESMLAIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    storageAccountName2: sa4AIsearch.outputs.storageAccountName
    aiSearchName: aiSearchService.outputs.aiSearchName
    resourceGroupId: targetResourceGroupId
    aiServicesName: csAzureOpenAI.outputs.cognitiveName
    aiServicesPrincipalId:csAzureOpenAI.outputs.principalId
  }
  dependsOn: [
    csAzureOpenAI
    csAIstudio
    rbacReadUsersToCmnVnetBastion
  ]
}
  */


// RBAC - Read users to Bastion, IF Bastion is added in ESML-COMMON resource group. If Bastion is in HUB, an admin need to do this manually
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,vnetResourceGroupName)
  name: 'rbacGenAIRUsersToCmnVnetBas${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: technicalAdminsObjectID_array_safe
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    project_service_principle: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    rbacModuleUsers
    rbacModuleAIServices
    vmPrivate
    sacc
    kv1
    aiHub
  ]
}

// RBAC on ACR Push/Pull for users in Common Resource group

module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacUsersToCommonACR${projectNumber}${locationSuffix}${env}'
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleObjectId:externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    userObjectIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    rbacReadUsersToCmnVnetBastion
    rbacKeyvaultCommon4Users
    aiHub
    acrCommon2
  ]
}


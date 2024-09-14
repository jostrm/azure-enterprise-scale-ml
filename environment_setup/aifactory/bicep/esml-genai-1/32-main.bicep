targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

@description('Service setting: Deploy VM for project')
param serviceSettingDeployProjectVM bool = true
@description('Service setting:Deploy Azure AI Search')
param serviceSettingDeployAzureAISearch bool = true
@description('Service setting:Deploy AIHub, e.g. Azure Machine Learning in hub mode')
param serviceSettingDeployAIHub bool = true

@description('Service setting:Deploy Azure Machine Learning')
param serviceSettingDeployAzureML bool = false
@description('Service setting:Deploy CosmosDB')
param serviceSettingDeployCosmosDB bool = false
@description('Service setting:Deploy Azure WebApp')
param serviceSettingDeployWebApp bool = false

param semanticSearchTier string = 'free' //   'disabled' 'free' 'standard'
param aiSearchSKUName string = 'basic' // 'basic' 'standard'

@description('Default is false. May be needed if Azure OpenAI should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessForCognitive bool = false
@description('Default is false. May be needed if Azure AI Search, if it should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessForAISearch bool = false
@description('Default is false. May be needed if Azure Storage used by AI Search, if it should be public, which is neeed for some features, such as Azure AI Studio on your data feature.')
param enablePublicNetworkAccessFoAIStorage bool = false
@description('Default is false. If tru, it will flip all flags for GenAI RAG, such as Azure OpenAI, Azure AI Search, CosmosDB, WebApp, Azure Machine Learning')
param enablePublicGenAIAccess bool = false

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
param allowPublicAccessWhenBehindVnet bool = true
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
@description('Datalake GEN 2 storage account prefix. Max 8 chars.Example: If prefix is "marvel", then "marvelesml001[random5]dev",marvelesml001[random5]test,marvelesml001[random5]prod')
param commonLakeNamePrefixMax8chars string
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
var defaultSubnet = common_subnet_name

// RBAC
var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,' ',''),','))
var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var technicalAdminsEmail_array_safe = technicalAdminsEmail == 'null'? []: technicalAdminsEmail_array

// Other - uniquness, Keyvault name
var deploymentProjSpecificUniqueSuffix = '${projectName}${genaiName}${locationSuffix}${env}${aifactorySuffixRG}'
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'

// Networking - Private DNS
var privDnsResourceGroup = privDnsResourceGroup_param != '' ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = privDnsSubscription_param != '' ? privDnsSubscription_param : subscriptionIdDevTestProd

var privateLinksDnsZones = {
  blob: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.${environment().suffixes.storage}'
  }
  file: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.file.${environment().suffixes.storage}'
  }
  dfs: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.dfs.${environment().suffixes.storage}'
  }
  queue: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.queue.${environment().suffixes.storage}'
  }
  table: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.table.${environment().suffixes.storage}'
  }
  registry: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.azurecr.io' // ${environment().suffixes.acrLoginServer}'
  }
  registryregion: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/${location}.data.privatelink.azurecr.io'
    name:'${location}.data.privatelink.azurecr.io'
  }
  vault: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
  }
  amlworkspace: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.api.azureml.ms'
  }
  notebooks: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.notebooks.azure.net' 
  }
  dataFactory: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.datafactory.azure.net'
  }
  portal: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.adf.azure.com'
  }
  azuredatabricks: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.azuredatabricks.net'
  }
  azureeventhubs: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.servicebus.windows.net'
  }
  azureeventgrid: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.eventgrid.azure.net'
  }
  azuremonitor: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com'
  }
  azuremonitoroms: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com'
  }
  azuremonitorods: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com'
  }
  azuremonitoragentsvc: {
    id: '${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net'
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

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

// ------------------------------ RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

module ownerPermissions '../modules/contributorRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Owner4TechContact${deploymentProjSpecificUniqueSuffix}'
  params: {
    userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserEmails: technicalAdminsEmail_array_safe
    additionalUserIds:technicalAdminsObjectID_array_safe
  }
  dependsOn:[
    projectResourceGroup
  ]
}
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
  ]
}

// RBAC - Read users to Bastion, IF Bastion is added in ESML-COMMON resource group. If Bastion is in HUB, an admin need to do this manually
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacRUsersToCmnVnetBas${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: technicalAdminsObjectID_array_safe
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    bastion_service_name: 'bastion-${locationSuffix}-${env}${commonResourceSuffix}'  // bastion-uks-dev-001
    common_kv_name:'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    project_service_principle: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
  dependsOn: [
    aml
    vmPrivate
  ]
}

// ------------------------------ END:RBAC ResourceGroups, Bastion,vNet, VMAdminLogin  ------------------------------//

// ------------------------------ SERVICES - Azure OpenAI, Azure AI Search, Storage for Azure AI Search, Azure Content Safety ------------------------------//

param csSKU string = 'S0'
module contentSafety '../modules/contentSafety.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'ContentSafety4${deploymentProjSpecificUniqueSuffix}'
  params: {
    csSKU: csSKU
    location: location
    contentsafetyName: 'cs-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
  }
}
// Azure OpenAI
param gptDeploymentName string= 'gpt-4'
var searchIndexName= 'idx-${projectName}${env}${uniqueInAIFenv}'
param chatGptModelVersion string = 'turbo-2024-04-09' // GPT-4 Turbo with Vision https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models#o1-preview-and-o1-mini-models-limited-access
param chatGptDeploymentCapacity int = 5
param embeddingDeploymentName  string=  'text-embedding-3-large' // 'text-embedding-ada-002'
param embeddingModelName string = 'text-embedding-3-large' // 'text-embedding-ada-002'
param embeddingDeploymentCapacity int = 5

var defaultOpenAiDeployments = [
  {
    name: gptDeploymentName
    model: {
      format: 'OpenAI'
      name: gptDeploymentName
      version: chatGptModelVersion
    }
    sku: {
      name: 'Standard'
      capacity: chatGptDeploymentCapacity
      tier: 'Standard'
    }
    scaleSettings: {
      scaleType: 'Standard'
      capacity: chatGptDeploymentCapacity
    }
    raiPolicyName: 'Microsoft.Default'
  }
  {
    name: embeddingDeploymentName
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      //version: '2'
    }
    sku: {
      name: 'Standard'
      capacity: embeddingDeploymentCapacity
      tier: 'Standard'
    }
    scaleSettings: {
      scaleType: 'Standard'
      capacity: chatGptDeploymentCapacity
    }
    raiPolicyName: 'Microsoft.Default'
  }
]

module azureOpenAI '../modules/cognitiveServices.bicep' = if(enablePublicNetworkAccessForCognitive == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AzureOpenAI4${deploymentProjSpecificUniqueSuffix}'
  params: {
    cognitiveName: 'cog-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    tags: tags
    location: location
    sku: 'S0'
    vnetId: vnetId
    subnetName: defaultSubnet
    kind: 'TextAnalytics'
    pendCogSerName: 'p-${projectName}-openai-${genaiName}'
    deployments:defaultOpenAiDeployments
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForCognitive

  }
  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsAzureOpenAI '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLinkAOAI${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: azureOpenAI.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
    azureOpenAI
  ]
}
// Azure OpenAI - END

// Azure AI Search

module aiSearchService '../modules/aiSearch.bicep' = if(centralDnsZoneByPolicyInHub==false){
  name: 'AzureAISearch4${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    aiSearchName: 'aiSearch${deploymentProjSpecificUniqueSuffix}'
    location: location
    skuName: aiSearchSKUName
    replicaCount: 1
    partitionCount: 1
    privateEndpointName: 'p-${projectName}-aisearch-${genaiName}'
    vnetId: vnetId
    subnetName: defaultSubnet
    tags: tags
    semanticSearchTier: semanticSearchTier
    publicNetworkAccess: enablePublicGenAIAccess? true: enablePublicNetworkAccessForAISearch
    ipRules: [
      {
        value: IPwhiteList // 'your.public.ip.address' If using IP-whitelist from ADO
      }
    ]
  }
}

module privateDnsaiSearchService '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: aiSearchService.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
    aiSearchService
  ]
}

// Azure AI Search - END

// Storage for Azure AI Search

module sa4AIsearch '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'GenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}'
    tags: tags
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module privateDnsStorageGenAI '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA${genaiName}${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sa4AIsearch.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
    sa4AIsearch
  ]
}

// Storage for Azure AI Search - END

// ------------------------------ SERVICES(Common) - Keyvault, VM, Loganalytics, AppInsights ------------------------------//

// Related to Azure Machine Learning: Cointainer Registry, Storage Account, KeyVault, LogAnalytics, ApplicationInsights
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
module acr '../modules/containerRegistry.bicep' = {
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

module sacc '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLGenAIStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-blob-${genaiName}ml'
    filePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-file-${genaiName}ml'
    queuePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-queue-${genaiName}ml'
    tablePrivateEndpointName: 'p-sa-${projectName}${locationSuffix}${env}-table-${genaiName}ml'
    tags: tags
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
    enablePurgeProtection:true
    tenantIdentity: tenantId
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
    ]
    accessPolicies: [] 
    ipRules: [
      {
        value: IPwhiteList // 'your.public.ip.address' If using IP-whitelist from ADO
      }
    ]
  }
  dependsOn: [
    projectResourceGroup
  ]
}

// LogAnalytics
var laName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2020-08-01' existing = {
  name: laName
  scope:commonResourceGroupRef
}

module applicationInsight '../modules/applicationInsights.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppIns4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}' // max 255 chars
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
    vmSize: 'Standard_DS3_v2'
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: tags
    keyvaultName: kv1.outputs.keyvaultName
  }

  dependsOn: [
    kv1
    projectResourceGroup
    
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
    kv1
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
    kv1
    addSecret
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
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

// Configure Private DNS Zones, if standalone AIFactory. (othwerwise the HUB DNS Zones will be used, and via policy auomatically create A-records in HUB DNS Zones)

module privateDnsStorage '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'priDZoneSA${deploymentProjSpecificUniqueSuffix}'
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
module privateDnsContainerRegistry '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
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

module aml '../modules/machineLearning.bicep'= if(serviceSettingDeployAzureML == true)  {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AAMLGenAI4${deploymentProjSpecificUniqueSuffix}'
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
    storageAccount: sacc.outputs.storageAccountId
    containerRegistry: acr.outputs.containerRegistryId
    keyVault: kv1.outputs.keyvaultId
    applicationInsights: applicationInsight.outputs.ainsId
    aksSubnetId: aksSubnetId
    aksSubnetName:aksSubnetName
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: tags
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml${genaiName}-to-vntcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones['amlworkspace'].id
    notebookPrivateDnsZoneID:privateLinksDnsZones['notebooks'].id
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
  }

  dependsOn: [
    projectResourceGroup
    privateDnsContainerRegistry
    privateDnsKeyVault
    privateDnsStorage
  ]
  
}

var aiHubName ='aihub-${projectName}-${locationSuffix}-${env}${resourceSuffix}'

module aiHub '../modules/machineLearningAIHub.bicep' = if(serviceSettingDeployAIHub == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: aiHubName
  params: {
    name: aiHubName
    location: location
    tags: tags
    aifactorySuffix: aifactorySuffixRG
    amlPrivateDnsZoneID: privateLinksDnsZones['amlworkspace'].id
    applicationInsights: applicationInsight.outputs.ainsId
    containerRegistry: acr.outputs.containerRegistryId
    env: env
    keyVault: kv1.outputs.keyvaultId
    notebookPrivateDnsZoneID: privateLinksDnsZones['notebooks'].id
    privateEndpointName:'pend-${projectName}-aihub${genaiName}-to-vntcmn'
    projectName: projectName
    skuName: 'basic'
    skuTier: 'basic'
    storageAccount: sacc.outputs.storageAccountId
    subnetName: defaultSubnet
    uniqueDepl: deploymentProjSpecificUniqueSuffix
    vnetId: vnetId
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enablePublicGenAIAccess:enablePublicGenAIAccess
  }
}

module aiHubConnection '../modules/aihubConnection.bicep' = if(serviceSettingDeployAIHub == true) {
  name: 'aiHubConnection4${deploymentProjSpecificUniqueSuffix}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params:{
    aiHubName: aiHubName
    targetOpenAIServiceEndpointId: azureOpenAI.outputs.azureOpenAIEndpoint
    targetOpenAIServiceResourceId: azureOpenAI.outputs.cognitiveId
    parentAIHubResourceId: aiHub.outputs.amlId
  }
  dependsOn: [
    aiHub
    azureOpenAI
  ]
}

module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' ={
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
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

// ------------------------------ END - SERVICES (Azure Machine Learning)  ------------------------------//


targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

param useAdGroups bool = false

// Optional override
param bastionName string = ''
param bastionResourceGroup string = ''
param bastionSubscription string = ''
param vnetNameFullBastion string = ''

param privateDnsAndVnetLinkAllGlobalLocation bool=false
// User access: standalone/Bastion
@description('Service setting: Deploy VM for project')
param serviceSettingDeployProjectVM bool = false

@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param keyvaultEnablePurgeProtection bool = true
param vmSKUSelectedArrayIndex int = 2
param vmSKU array = [
  'Standard_E2s_v3'
  'Standard_D4s_v3'
  'standard_D2as_v5'
]

@description('Allow Azure ML Studio UI or not. Dataplane is always private, private endpoint - Azure backbone ')
param AMLStudioUIPrivate bool = true
@description('Databricks with PRIVATE endpoint or with SERVICE endpoint. Either way controlplane is on Azure backbone network ')
param databricksPrivate bool = false
@secure()
@description('The password that is saved to keyvault and used by local admin user on VM')
param adminPassword string
@description('The username of the local admin that is created on VM')
param adminUsername string
@description('Specifies the name of the public databricks subnet that should be used by new databricks instance')
param dbxPubSubnetName string
@description('Specifies the name of the private databricks subnet that should be used by new databricks instance')
param dbxPrivSubnetName string

@description('Specifies the id of the AKS subnet that should be used by new AKS instance')
param aksSubnetId string
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'

@description('Common default subnet')
param common_subnet_name string

@description('tags for common resources')
param tags object
@description('Specifies the project specific tags that should be applied to newly created resources')
param projecttags object
@description('Deployment location.')
param location string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string

@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
var projectName = 'prj${projectNumber}'

@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string

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
@description('Specifies the SKU of the storage account, for Azure ML Studio')
param skuNameStorage string = 'Standard_LRS' //  Cannot be changed after creation.

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
@description('Specifies the SKU of the storage account, for AIFactory ESML Datalake')
param skuNameStorageLake string = 'Standard_ZRS' // Must be the same as ESML Datalke in commmon RG. Cannot be changed after creation
param keyvaultSoftDeleteDays int=90

// RBAC - Optionally add a super-admin in core team: UserObjectId
@description('ESML CoreTeam assigned to help project. Specifies technical contact email and will be used for tagging and RBAC')
param technicalContactEmail string=''
@description('ESML CoreTeam assigned to help project.Specifies technical contact objectId and will be used for tagging and RBAC')
param technicalContactId string=''
@description('Specifies project owner email and will be used for tagging and RBAC')
param projectOwnerEmail string=''
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param projectOwnerId string=''
@description('Specifies the tenant id')
param tenantId string

@description('Project specific service principle  KEYVAULT secret NAME for RBAC purpose - Object ID') // OID: Get it by using Get-AzADUser or Get-AzADServicePrincipal cmdlet
param projectServicePrincipleOID_SeedingKeyvaultName string // Specifies the object ID of a user, service principal or security group in the Azure AD. The object ID must be unique for the list of access policies. 
@description('Project specific service principle KEYVAULT secret NAME to be added in kv for - Secret value ')
param projectServicePrincipleSecret_SeedingKeyvaultName string
@description('Project specific service principle KEYVAULT secret NAME for - App ID')
param projectServicePrincipleAppID_SeedingKeyvaultName string

@description('AzureDatabricks enterprise application')
param databricksOID string

// ESML START
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

//Override RG, vnet, datalakename, kvNameFromCOMMON
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
@description('If you want to use a common Azure Container Registry, in the AI Factory COMMON resourcegroup, set this to true')
param useCommonACR bool = true

// Override: AML: AKS cluster
param aks_dev_sku_override string = ''
param aks_test_prod_sku_override string = ''
param aks_version_override string = ''
param aks_dev_nodes_override int = -1
param aks_test_prod_nodes_override int = -1

// Override: AML Compute Instance
param aml_ci_dev_sku_override string = ''
param aml_ci_test_prod_sku_override string = ''

// Override: AML Compute Custer
param aml_cluster_dev_sku_override string = ''
param aml_cluster_test_prod_sku_override string = ''
param aml_cluster_dev_nodes_override int = -1
param aml_cluster_test_prod_nodes_override int = -1

// ENABLE/DISABLE: Optional exclusions in deployment
@description('Azure ML workspace can only be called once from BICEP, otherwise COMPUTE name will give error 2nd time. ')
param enableAML bool = true
@description('if Eventhubs, Streaming use cases to be enabled and provisioned by default, or added.')
param enableEventhubs bool = true

// BYOsubnet
param DOCS_byovnet_example string = ''
param DOCS_byosnet_common_example string = ''
param DOCS_byosnet_project_example string = ''
param BYO_subnets bool = false
param network_env string =''
param subnetCommon string = ''
param subnetCommonScoring string = ''
param subnetCommonPowerbiGw string = ''
param subnetProjGenAI string = ''
param subnetProjAKS string = ''
param subnetProjACA string = ''
param subnetProjDatabricksPublic string = ''
param subnetProjDatabricksPrivate string = ''
param randomValue string = newGuid()

var vnetNameFull = vnetNameFull_param != '' ?  replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

@description('Meta. Needed to calculate subnet: subnetCalc and genDynamicNetworkParamFile')
param vnetResourceGroupBase string
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string

// ESML-VANLILA #######################################  You May want to change this template / naming convention ################################
var commonResourceGroup = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg' // esml-project001-weu-dev-002-rg
var vnetResourceGroupName = vnetResourceGroup_param != '' ? vnetResourceGroup_param : commonResourceGroup
var subscriptions_subscriptionId = subscription().id
var vnetId = '${subscriptions_subscriptionId}/resourceGroups/${vnetResourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'
var defaultSubnet = common_subnet_name //'snet-esmlcmn-001'
// ESML-VANLILA #######################################  You May want to change this template / naming convention ################################

// BYOSubnet: common_subnet_name,common_subnet_scoring_name,common_pbi_subnet_name,common_bastion_subnet_name
var common_subnet_name_local = subnetCommon != '' ? replace(subnetCommon, '<network_env>', network_env) : common_subnet_name

var segmentsAKS = split(aksSubnetId, '/')
var aksSubnetName = segmentsAKS[length(segmentsAKS) - 1] // Get the last segment, which is the subnet name

// ADO comma separated VARIABLE to ARRAY
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsObjectID string = 'null'
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsEmail string = 'null'
@description('Optional:Whitelist IP addresses from project members to see keyvault, and to connect via Bastion')
param IPwhiteList string = ''
@description('since esml-common needs this, and since we need to see if users in this file, should have RBAC acecss')
param addBastionHost bool // Dummy: do not correspond to any parameters defined in the template: 'addBastionHost'
param alsoManagedMLStudio bool = true

// RBAC
var ipWhitelist_array_1 = array(split(replace(IPwhiteList, '\\s+', ''), ','))
var ipWhitelist_array = (empty(IPwhiteList) || IPwhiteList == 'null') ? [] : ipWhitelist_array_1

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var p011_genai_team_lead_array = (empty(technicalAdminsObjectID) || technicalAdminsObjectID == 'null') ? [] : technicalAdminsObjectID_array

var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var p011_genai_team_lead_email = (empty(technicalAdminsEmail) || technicalAdminsEmail == 'null') ? [] : technicalAdminsEmail_array

// Salt: Project/env specific
resource targetResourceGroupRefSalt 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: targetResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}
var projectSalt = substring(uniqueString(targetResourceGroupRefSalt.id), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${projectSalt}'

// Salt: AIFactory instance/env specific
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

var sweden_central_adf_missing =  false // (location == 'swedencentral')?true:false
var sweden_central_appInsight_classic_missing = (location == 'swedencentral')?true:false

@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jå HUB

// Networking - Private DNS: Centralized or Standalone
var privDnsResourceGroupName = (privDnsResourceGroup_param != '' && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName
var privDnsSubscription = (privDnsSubscription_param != ''&& centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd

// Storage + AI Services: Do not allow /32
var processedIpRulesSa = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip
}]

// Kv+AIHuv -> Do allow and prefer /32
var processedIpRulesKv = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]

var processedIpRulesAzureML = [for ip in ipWhitelist_array: {
  action: 'Allow'
  value: contains(ip, '/') ? ip : '${ip}/32'
}]
var ipWhitelist_remove_ending_32 = [for ip in ipWhitelist_array: endsWith(ip, '/32') ? substring(ip, 0, length(ip) - 3) : ip]
//var ipWhitelist_remove_ending_slash_something = [for ip in ipWhitelist_array: (contains(ip, '/') ? substring(ip, 0, indexOf(ip, '/')) : ip)]

var cmnName = 'cmn'
var kvNameCommon = kvNameFromCOMMON_param != '' ? kvNameFromCOMMON_param : 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// 2024-09-15: 25 entries
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
  azurecontainerapps: {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroupName}/providers/Microsoft.Network/privateDnsZones/privatelink.${location}.azurecontainerapps.io'
    name:'privatelink.${location}.azurecontainerapps.io'
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
  {
    name: privateLinksDnsZones.azurecontainerapps.name
    id: privateLinksDnsZones.azurecontainerapps.id
  }
]

output privateLinksDnsZones object = privateLinksDnsZones

/*Is already created in esml-common/main/13-rgLevel.bicep  */
/*
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
*/

var randomSalt = substring(randomValue, 6, 10)
module miForPrj '../modules/mi.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'miForPrj${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
    location: location
    tags: projecttags
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module spAndMI2Array '../modules/spAndMiArray.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    managedIdentityOID: miForPrj.outputs.managedIdentityPrincipalId
    servicePrincipleOIDFromSecret: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
  }
}
var spAndMiArray = spAndMI2Array.outputs.spAndMiArray

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet_default_ref 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: defaultSubnet
  parent: vnet
}
resource subnet_aks_ref 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: aksSubnetName
  parent: vnet
}
resource subnet_dbx_pub_ref 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: dbxPubSubnetName
  parent: vnet
}

// Verify that at least 1 Private DNS zones exists in privDnsResourceGroupName and privDnsSubscription  before continuing
resource createPrivateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.cognitiveservices.azure.com'
  scope:resourceGroup(privDnsSubscription,privDnsResourceGroupName)
}

module projectResourceGroup '../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'prjResourceGroup${deploymentProjSpecificUniqueSuffix}'
  params: {
    rgName: targetResourceGroup
    location: location
    tags: projecttags
  }
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'
var keyvaultName2 = 'kv-2${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'

module ownerPermissions '../modules/contributorRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Owner4TechContact${deploymentProjSpecificUniqueSuffix}'
  params: {
    userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserEmails: p011_genai_team_lead_email
    additionalUserIds:p011_genai_team_lead_array
    useAdGroups: useAdGroups
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
    additionalUserEmails: p011_genai_team_lead_email
    additionalUserIds:p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn:[
    projectResourceGroup
  ]
}

var laName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2020-08-01' existing = {
  name: laName
  scope:commonResourceGroupRef
}

module applicationInsightSWC '../modules/applicationInsightsRGmode.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
    logWorkspaceName: laName
    logWorkspaceNameRG: commonResourceGroup
    tags: projecttags
    location: location
  }

  dependsOn: [
    projectResourceGroup
  ]
}

var adfName = 'adf-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
module adf '../modules/dataFactory.bicep' = if(sweden_central_adf_missing== false)  {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'DataFactory4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: adfName
    location: location
    vnetId: vnetId
    subnetName: defaultSubnet
    portalPrivateEndpointName: 'pend-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}-adfportal-to-vnt-mlcmn'
    runtimePrivateEndpointName: 'pend-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}-adfruntime-to-vnt-mlcmn'
    tags: projecttags
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module vmPrivate '../modules/virtualMachinePrivate.bicep'  = if(serviceSettingDeployProjectVM == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: vmSKU[vmSKUSelectedArrayIndex]
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: projecttags
    keyvaultName: kv1.outputs.keyvaultName
  }
  dependsOn: [

    projectResourceGroup
    aml
    adf
  ]
}

var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
module acr '../modules/containerRegistry.bicep' = if (useCommonACR == false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLContainerReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: 'acr${projectName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
    skuName: 'Premium'
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}${locationSuffix}-containerreg-to-vnt-mlcmn'
    tags: projecttags
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
    vnetName:vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: common_subnet_name_local // snet-esml-cmn-001
    privateEndpointName: 'pend-acr-cmn${locationSuffix}-containerreg-to-vnt-mlcmn' // snet-esml-cmn-001
    tags: acrCommon.tags
    location:acrCommon.location
  }

  dependsOn: [
    acrCommon
  ]
}

var saccName = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}${prjResourceSuffixNoDash}${env}','-','')

module sacc '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: saccName
    skuName: skuNameStorage
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    blobPrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-blob-to-vnt-mlcmn'
    filePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-file-to-vnt-mlcmn'
    queuePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-queue-to-vnt-mlcmn'
    tablePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-table-to-vnt-mlcmn'
    tags: projecttags
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
      subnet_default_ref.id
      subnet_aks_ref.id
      //'${vnetId}/subnets/${defaultSubnet}'
      //'${vnetId}/subnets/${aksSubnetName}'
    ]
    ipRules: empty(processedIpRulesSa)? []: processedIpRulesSa
    enablePublicGenAIAccess:!empty(processedIpRulesSa)
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
          'https://42.${location}.instances.azureml.ms'
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


var sacc2Name = replace('sa2${projectName}${locationSuffix}${uniqueInAIFenv}${prjResourceSuffixNoDash}${env}','-','')
/*
resource existingSacc2 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: sacc2Name
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
}

module sacc2 '../modules/storageAccount.bicep' = if(existingSacc2.id == null && alsoManagedMLStudio == true) {
*/

module sacc2 '../modules/storageAccount.bicep' = if(alsoManagedMLStudio == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLStorage2${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: sacc2Name
    skuName: skuNameStorage
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    location: location
    blobPrivateEndpointName: 'pend-sa2-${projectName}${locationSuffix}${env}-blob-to-vnt-mlcmn'
    filePrivateEndpointName: 'pend-sa2-${projectName}${locationSuffix}${env}-file-to-vnt-mlcmn'
    queuePrivateEndpointName: 'pend-sa2-${projectName}${locationSuffix}${env}-queue-to-vnt-mlcmn'
    tablePrivateEndpointName: 'pend-sa2-${projectName}${locationSuffix}${env}-table-to-vnt-mlcmn'
    tags: projecttags
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
      subnet_default_ref.id
      subnet_aks_ref.id
    ]
    enablePublicGenAIAccess:!empty(processedIpRulesSa)
    ipRules:empty(processedIpRulesSa)? []: processedIpRulesSa
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
          'https://42.${location}.instances.azureml.ms'
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

/*
# TODO:it is only private endpoints I want to avoid, if they already exists.
resource existingKv1cors 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
}

//'${vnetId}/subnets/${defaultSubnet}'
      //'${vnetId}/subnets/${aksSubnetName}'
      //'${vnetId}/subnets/${dbxPubSubnetName}'

module kv1 '../modules/keyVault.bicep' = if(existingKv1.id == null) {
*/

module kv1 '../modules/keyVault.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLKeyVault4${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: projecttags
    enablePurgeProtection:keyvaultEnablePurgeProtection
    soft_delete_days:keyvaultSoftDeleteDays
    tenantIdentity: tenantId
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      subnet_default_ref.id
      subnet_aks_ref.id
      subnet_dbx_pub_ref.id
    ]
    accessPolicies: [] 
    ipRules: empty(processedIpRulesKv)?[]:processedIpRulesKv
    enablePublicGenAIAccess: !empty(processedIpRulesKv)
  }
  dependsOn: [
    projectResourceGroup
  ]
}

/* error: deployment could not be found. 
# TODO:it is only private endpoints I want to avoid, if they already exists.
resource existingKv2 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName2
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
}

module kv2 '../modules/keyVault.bicep' = if(existingKv2.id == null && alsoManagedMLStudio == true) {
*/
module kv2 '../modules/keyVault.bicep' = if(alsoManagedMLStudio == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLKeyVault42${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName2
    location: location
    tags: projecttags
    enablePurgeProtection:keyvaultEnablePurgeProtection
    soft_delete_days:keyvaultSoftDeleteDays
    enablePublicGenAIAccess: !empty(processedIpRulesKv)
    tenantIdentity: tenantId
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv2-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      subnet_default_ref.id
      subnet_aks_ref.id
      subnet_dbx_pub_ref.id
    ]
    accessPolicies: [] 
    ipRules: empty(processedIpRulesKv)?[]:processedIpRulesKv
  }
  dependsOn: [
    projectResourceGroup
    kv1
  ]
}

// Note: az keyvault update  --name msft-weu-dev-cmnai-kv --enabled-for-template-deployment true
resource externalKv 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription,inputKeyvaultResourcegroup)
}

module addSecret '../modules/kvSecretsPrj.bicep' = {
  name: '${keyvaultName}addSecrect2ProjectKV${projectNumber}${locationSuffix}${env}'
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  params: {
    spAppIDValue:externalKv.getSecret(projectServicePrincipleAppID_SeedingKeyvaultName) //projectServicePrincipleAppID_SeedingKeyvaultName 
    spOIDValue: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)  // projectServicePrincipleOID_SeedingKeyvaultName

    spSecretValue: externalKv.getSecret(projectServicePrincipleSecret_SeedingKeyvaultName)
    keyvaultName: kv1.outputs.keyvaultName
  }
  dependsOn: [
  ]
}

var secretGetListSet = {
  secrets: [ 
    'get'
    'list'
    'set'
  ]
}
module kvCmnAccessPolicyTechnicalContactAll '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: '${keyvaultName}APTechContact${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetListSet
    keyVaultResourceName: kv1.outputs.keyvaultName
    policyName: 'add'
    principalId: technicalContactId
    additionalPrincipalIds:p011_genai_team_lead_array
  }
  dependsOn: [
    addSecret
  ]
}


resource commonKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
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
    additionalPrincipalIds:p011_genai_team_lead_array
  }
  dependsOn: [
    commonKv
  ]
}


module privateDnsStorage '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLStorageSacc${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sacc.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}
module privateDnsStorage2 '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLStorageSacc2${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: sacc2.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}
module privateDnsKeyVault '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLKeyVault${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: kv1.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}
module privateDnsContainerRegistry '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false && useCommonACR == false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: acr.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

var amlName ='aml-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var amlManagedName ='aml2-${projectName}-${locationSuffix}-${env}${resourceSuffix}'

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
var aml_cluster_dev_sku_param = aml_cluster_dev_sku_override != '' ? aml_cluster_dev_sku_override : aml_dev_defaults[1]
var aml_cluster_test_prod_sku_param = aml_cluster_test_prod_sku_override != '' ? aml_cluster_test_prod_sku_override : aml_testProd_defaults[1]
var aml_cluster_dev_nodes_param = aml_cluster_dev_nodes_override != -1 ? aml_cluster_dev_nodes_override : 3
var aml_cluster_test_prod_nodes_param = aml_cluster_test_prod_nodes_override != -1 ? aml_cluster_test_prod_nodes_override : 3

module aml '../modules/machineLearning.bicep'= if(enableAML) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AML1classic${deploymentProjSpecificUniqueSuffix}'
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
    aksSubnetId: aksSubnetId
    aksSubnetName:aksSubnetName
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: projecttags
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml-to-vnt-mlcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones.amlworkspace.id
    notebookPrivateDnsZoneID:privateLinksDnsZones.notebooks.id
    allowPublicAccessWhenBehindVnet:(AMLStudioUIPrivate == true && empty(ipWhitelist_remove_ending_32))? false:true
    enablePublicAccessWithPerimeter: AMLStudioUIPrivate == false ? true: false
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
    ipRules: empty(processedIpRulesAzureML) ? [] : processedIpRulesAzureML
    ipWhitelist_array:empty(ipWhitelist_remove_ending_32)?[]:ipWhitelist_remove_ending_32
    alsoManagedMLStudio:alsoManagedMLStudio
    managedMLStudioName:amlManagedName
    privateEndpointName2: alsoManagedMLStudio? 'pend-${projectName}-aml2-to-vnt-mlcmn': ''
    saName:sacc.outputs.storageAccountName
    saName2:alsoManagedMLStudio? sacc2.outputs.storageAccountName: ''
    kvName:kv1.outputs.keyvaultName
    kvName2:alsoManagedMLStudio? kv2.outputs.keyvaultName: ''
    acrName: useCommonACR? acrCommon2.outputs.containerRegistryName: acr.outputs.containerRegistryName
    acrRGName: useCommonACR? commonResourceGroup: targetResourceGroup
    appInsightsName:applicationInsightSWC.outputs.name
  }

  dependsOn: [
    projectResourceGroup
    privateDnsContainerRegistry
    privateDnsKeyVault
    privateDnsStorage
    sacc2
    kv2
  ]
}

var evenhubNameSpaceAndWsName = 'ev-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
module eventHubLogging '../modules/eventhub.bicep' = if(enableEventhubs) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'EventHub4${deploymentProjSpecificUniqueSuffix}'
  params: {
    namespaceName: evenhubNameSpaceAndWsName
    location:location
    privateEndpointName:'pend-${projectName}-ev-to-vnt-mlcmn'
    tags: projecttags
    vnetId: vnetId
    subnetName: defaultSubnet
    keyvaultName: kv1.outputs.keyvaultName
  }
  dependsOn: [
    projectResourceGroup
  ]
      
}

var databricksName = 'dbx-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var databricksNameP = 'dbxp-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var databricksManagedRG = '${targetResourceGroup}${resourceSuffix}-dbxmgmt'
var databricksManagedRGId = '${subscription().id}/resourceGroups/${databricksManagedRG}'

//var managedResourceGroupName = 'databricks-rg-${workspaceName}-${uniqueString(workspaceName, resourceGroup().id)}'
//var trimmedMRGName = substring(managedResourceGroupName, 0, min(length(managedResourceGroupName), 90))
//var managedResourceGroupId = '${subscription().id}/resourceGroups/${trimmedMRGName}'

module dbx '../modules/dataBricks.bicep'  = if(databricksPrivate == false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'Dbx4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: databricksName
    amlWorkspaceId:aml.outputs.amlId
    location: location
    skuName: 'standard'
    managedResourceGroupId:databricksManagedRGId
    databricksPrivateSubnet: dbxPrivSubnetName
    databricksPublicSubnet: dbxPubSubnetName
    vnetId: vnetId
    tags: projecttags
  }
  dependsOn: [
    projectResourceGroup
  ]
}

module dbxPrivate '../modules/databricksPrivate.bicep' = if(databricksPrivate == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'DbxPriv4${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlWorkspaceId: aml.outputs.amlId
    databricksPrivateSubnet: dbxPrivSubnetName
    databricksPublicSubnet: dbxPubSubnetName
    location: location
    managedResourceGroupId: databricksManagedRGId
    name: databricksNameP
    skuName: 'standard'
    tags: projecttags
    vnetId: vnetId
    privateEndpointName: 'pend-${databricksNameP}-to-vnt-mlcmn'
    subnetName: dbxPubSubnetName
    requiredNsgRules:'NoAzureDatabricksRules'
  }
  dependsOn: [
    projectResourceGroup
  ]
}

var mangedIdentityName = 'esml${projectName}${env}DbxMI'

module dbxMIPriv '../modules/databricksManagedIdentityRBAC.bicep' = if(databricksPrivate == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'dbxMIOwnerPriv${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    managedIdentityName: mangedIdentityName
    databricksName: databricksNameP
  }
  dependsOn:[
    dbxPrivate
  ]
}
module dbxMI '../modules/databricksManagedIdentityRBAC.bicep' = if(databricksPrivate == false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'dbxMIOwner${deploymentProjSpecificUniqueSuffix}'
  params: {
    location: location
    managedIdentityName: mangedIdentityName
    databricksName: databricksName
  }
  dependsOn:[
    dbx
  ]
}

var datalakeName = datalakeName_param != '' ? datalakeName_param : '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}esml${replace(commonResourceSuffix,'-','')}${env}'
resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2021-04-01' existing = {
  name: datalakeName
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
 
}
var existingRules = esmlCommonLake.properties.networkAcls.virtualNetworkRules
var existingIps = esmlCommonLake.properties.networkAcls.ipRules
var keepSku = esmlCommonLake.sku.name
var keepLocation = esmlCommonLake.location
var keepTags = esmlCommonLake.tags
var dbxPublicSubnetResourceID = '${vnetId}/subnets/${dbxPubSubnetName}'

var virtualNetworkRules2Add = [
  {
    id: dbxPublicSubnetResourceID
    action: 'Allow'
    state: 'succeeded'
  }
]
var mergeVirtualNetworkRulesMerged = union(existingRules, virtualNetworkRules2Add) // union, avoid dups 

// https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/bicep-functions-lambda
var idsArrayExisting = map(existingRules, r => r.id) // var idsArrayExisting = [for rule in existingRules: rule.id]
var newIdArray = [
  dbxPublicSubnetResourceID
]
var virtualNetworkRules_array_noDups = union(idsArrayExisting,newIdArray)

param lakeContainerName string
module dataLake '../modules/dataLake.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'saUpdateVnetLake${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: datalakeName
    containerName: lakeContainerName
    skuName: skuNameStorageLake
    location: keepLocation
    vnetName: vnetNameFull
    vnetResourceGroupName: vnetResourceGroupName
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'pend-${datalakeName}-blob-to-vnt-esmlcmn'
    filePrivateEndpointName: 'pend-${datalakeName}-file-to-vnt-esmlcmn'
    dfsPrivateEndpointName: 'pend-${datalakeName}-dfs-to-vnt-esmlcmn'
    queuePrivateEndpointName: 'pend-${datalakeName}-queue-to-vnt-esmlcmn'
    tablePrivateEndpointName: 'pend-${datalakeName}-table-to-vnt-esmlcmn'
    tags: keepTags
    virtualNetworkRules: mergeVirtualNetworkRulesMerged
    virtualNetworkRules_array: virtualNetworkRules_array_noDups
    ipWhitelist_array: ipWhitelist_array
  }
  dependsOn: [
    commonResourceGroupRef
    aml // optional, but convenient: aml success, optherwise virtualNetworkRules needs to be removed manually if aml fails..and rerun
  ]
}

module privateDnsAzureDatafactory '../modules/privateDns.bicep' = if((centralDnsZoneByPolicyInHub==false)){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsZoneLinkADF${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: adf.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module privateDnsEventhubs '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope:resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneAndLinkEV1${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: eventHubLogging.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

module privateDnsAzureDatabricks '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub == false && databricksPrivate == true){
  scope:resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privDnsZoneLDBX2${deploymentProjSpecificUniqueSuffix}'
  params: {
    dnsConfig: dbxPrivate.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    createPrivateDnsZones
    projectResourceGroup
  ]
}

// RBAC
var secretGet = {
  secrets: [ 
    'get'
  ]
}
var secretGetList = {
  secrets: [ 
    'get'
    'list'
  ]
}

// AzureDatabricks - if set, and if this EnterpriseApplication already exists (can be that a project needs to be provisoned first..)
module spProjectSPAccessPolicyGet '../modules/kvCmnAccessPolicys.bicep' = if(databricksOID != null) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'spPRJSP${deploymentProjSpecificUniqueSuffix}' //'${keyvaultName}/add'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kv1.outputs.keyvaultName
    policyName: 'add'
    principalId: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kv1
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

module adfAccessPolicyGet '../modules/kvCmnAccessPolicys.bicep' = if((databricksOID != null) && (sweden_central_adf_missing==false)) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'adfAP1Get${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kv1.outputs.keyvaultName
    policyName: 'add'
    principalId: adf.outputs.principalId
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kv1
    aml
    spProjectSPAccessPolicyGet
  ]
}


module spDatabricksAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if(databricksOID != null) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'spDBXAPGetList${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: kv1.outputs.keyvaultName
    policyName: 'add'
    principalId: databricksOID
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kv1
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    adfAccessPolicyGet
  ]
}

module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if(databricksOID != null) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'spCmnKVGetList${deploymentProjSpecificUniqueSuffix}'
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

//
// ############################################################################################### RBAC ###############################
//

/* TODO-1

module rbacLake '../esml-common/modules-common/lakeRBAC.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacLake4Prj${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlPrincipalId: aml.outputs.principalId
    projectTeamGroupOrUser: p011_genai_team_lead_array
    adfPrincipalId: adf.outputs.principalId
    datalakeName: datalakeName
    useAdGroups:useAdGroups
  }
  dependsOn: [
    dataLake
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    adf
    logAnalyticsWorkspaceOpInsight
  ]
}

*/

/* TODO-2

module rbackDatabricks '../modules/databricksRBAC.bicep' = if(databricksPrivate == false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX4Prj${deploymentProjSpecificUniqueSuffix}'
  params: {
    databricksName: databricksName
    userPrincipalId: technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    dbx
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

*/


module rbackDatabricksPriv '../modules/databricksRBAC.bicep' = if(databricksPrivate == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBXP4Prj${deploymentProjSpecificUniqueSuffix}'
  params: {
    databricksName: databricksNameP
    userPrincipalId: technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    dbxPrivate
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}


// Needed if connnecting from Databricks to Azure ML workspace
// Note: SP OID: it must be the OBJECT ID of a service principal, not the OBJECT ID of an Application, different thing, and I have to agree it is very confusing.

/* TODO-3
module rbackSPfromDBX2AML '../modules/machinelearningRBAC.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX2AMLPrjSP${deploymentProjSpecificUniqueSuffix}'
  params: {
    amlName:amlName
    servicePrincipleAndMIArray: spAndMiArray
    adfSP:adf.outputs.principalId
    projectADuser:technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    adf
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}
*/

/* TODO-4

module rbacADFfromUser '../modules/datafactoryRBAC.bicep'= {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacADFAMProjSP${deploymentProjSpecificUniqueSuffix}'
  params: {
    datafactoryName:adfName
    userPrincipalId:technicalContactId
    additionalUserIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    adf
    rbackSPfromDBX2AML
  ]
}

*/

/* TODO-5
module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost==true && empty(bastionSubscription)==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,vnetResourceGroupName)
  name: 'rbacUsersToCmnVnetBastion${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray:spAndMiArray
    useAdGroups:useAdGroups
  }
  dependsOn: [
    aml
    rbackSPfromDBX2AML
    vmPrivate
  ]
}

*/

/* TODO-6
module rbacReadUsersToCmnVnetBastionExt '../modules/vnetRBACReader.bicep' = if(addBastionHost==true && empty(bastionSubscription)==false) {
  scope: resourceGroup(bastionSubscription,bastionResourceGroup)
  name: 'rbacUsersToCmnVnetExtBast2${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    vNetName: vnetNameFullBastion
    common_bastion_subnet_name: 'AzureBastionSubnet'
    servicePrincipleAndMIArray:spAndMiArray
    useAdGroups:useAdGroups
  }
  dependsOn: [
    aml
    rbackSPfromDBX2AML
    vmPrivate
  ]
}

*/

/* TODO-7

module rbacKeyvaultCommon4Users '../modules/kvRbacReaderOnCommon.bicep'= if(empty(bastionResourceGroup)==true){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacUsersToCmnKV${deploymentProjSpecificUniqueSuffix}'
  params: {
    common_kv_name:'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
    user_object_ids: p011_genai_team_lead_array
    addBastion: addBastionHost
    bastion_service_name: (empty(bastionName) != false)?bastionName: 'bastion-${locationSuffix}-${env}${commonResourceSuffix}'  // bastion-uks-dev-001 or custom name
    useAdGroups:useAdGroups
  }
  dependsOn: [
    aml
    rbackSPfromDBX2AML
    vmPrivate
    rbacReadUsersToCmnVnetBastion
  ]
}

*/

/* TODO-8
module rbacExternalBastion '../modules/rbacBastionExternal.bicep' = if(empty(bastionResourceGroup)==false && empty(bastionSubscription)==false && addBastionHost==true) {
  scope: resourceGroup(bastionSubscription,bastionResourceGroup)
  name: 'rbacGenAIReadBastion${deploymentProjSpecificUniqueSuffix}'
  params: {
    user_object_ids: p011_genai_team_lead_array
    bastion_service_name: (empty(bastionName) != false)?bastionName: 'bastion-${locationSuffix}-${env}${commonResourceSuffix}'  //custom resource group, subscription
    useAdGroups:useAdGroups
  }
  dependsOn: [
    aml
    rbackSPfromDBX2AML
    vmPrivate
    rbacReadUsersToCmnVnetBastionExt
  ]
}

*/

var targetResourceGroupId = resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', targetResourceGroup)
module rbacAml1 '../modules/rbacStorageAml.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacUsersAmlClassic${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    resourceGroupId: targetResourceGroupId
    userObjectIds: p011_genai_team_lead_array
    azureMLworkspaceName:aml.outputs.amlName
    servicePrincipleAndMIArray:spAndMiArray
    useAdGroups:useAdGroups
    user2Storage:true
  }
  dependsOn: [
    aml
  ]
}

module rbacAml2 '../modules/rbacStorageAml.bicep' = if(alsoManagedMLStudio) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacUsersAML_AIFactory${deploymentProjSpecificUniqueSuffix}'
  params:{
    storageAccountName: sacc.outputs.storageAccountName
    resourceGroupId: targetResourceGroupId
    userObjectIds: p011_genai_team_lead_array
    azureMLworkspaceName:aml.outputs.amlManagedName
    servicePrincipleAndMIArray:spAndMiArray
    useAdGroups:useAdGroups
    user2Storage:false
  }
  dependsOn: [
    aml
    rbacAml1
  ]
}

module rbacAmlRGLevel '../modules/rbacRGlevelAml.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacUsersAMLRG${deploymentProjSpecificUniqueSuffix}'
  params: {
    resourceGroupId: targetResourceGroupId
    servicePrincipleAndMIArray: spAndMiArray
    userObjectIds: p011_genai_team_lead_array
    useAdGroups:useAdGroups
  }
  dependsOn: [
    aml
    rbacAml1
  ]
}

// RBAC on ACR Push/Pull for users in Common Resource group

module cmnRbacACR '../modules/commonRGRbac.bicep' = if(useCommonACR) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacUsersToCmnACR${deploymentProjSpecificUniqueSuffix}'
  params: {
    commonRGId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', commonResourceGroup)
    servicePrincipleAndMIArray:spAndMiArray
    userObjectIds: p011_genai_team_lead_array
    useAdGroups: useAdGroups
  }
  dependsOn: [
    /*TODO 8 rbacKeyvaultCommon4Users */
    rbacAml1
    rbacAmlRGLevel
    aml
    acrCommon2
  ]
}

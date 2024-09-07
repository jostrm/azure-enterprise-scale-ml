targetScope = 'subscription' // We dont know PROJECT RG yet. This is what we are to create.

@description('Input Keyvault, where ADMIN for AD adds service principals to be copied to 3 common env, and SP per project')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string

@description('Allow Azure ML Studio UI or not. Dataplane is always private, private endpoint - Azure backbone ')
param AMLStudioUIPrivate bool = true
@description('Databricks with PRIVATE endpoint or with SERVICE endpoint. Either way controlplane is on Azure backbone network ')
param databricksPrivate bool = false
@secure()
//@minLength(8)
//@maxLength(128)
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

@description('tags')
param tags object
@description('Specifies the tags2 that should be applied to newly created resources')
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
@description('Specifies the SKU of the storage account')
param skuNameStorage string = 'Standard_ZRS'

// RBAC START
@description('Specifies project owner email and will be used for tagging and RBAC')
param projectOwnerEmail string
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param projectOwnerId string
@description('ESML CoreTeam assigned to help project. Specifies technical contact email and will be used for tagging and RBAC')
param technicalContactEmail string
@description('ESML CoreTeam assigned to help project.Specifies technical contact objectId and will be used for tagging and RBAC')
param technicalContactId string
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
@description('Specifies wether or not the virtual machine should have a public IP address or not')
param enableVmPubIp bool = false

// ENABLE/DISABLE end

var vnetNameFull = vnetNameFull_param != '' ? vnetNameFull_param : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

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

// ADO comma separated VARIABLE to ARRAY
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsObjectID string = 'null'
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsEmail string = 'null'
@description('Optional:Whitelist IP addresses from project members to see keyvault, and to connect via Bastion')
param IPwhiteList string = ''
@description('since esml-common needs this, and since we need to see if users in this file, should have RBAC acecss')
param addBastionHost bool // Dummy: do not correspond to any parameters defined in the template: 'addBastionHost'

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,' ',''),','))
var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var technicalAdminsEmail_array_safe = technicalAdminsEmail == 'null'? []: technicalAdminsEmail_array

var tags2 = projecttags
/*
var tags2 = {
  CostCenter: tags.CostCenter
  UnitCode: tags.UnitCode
  Project: tags.Project
  Owner: tags.Owner
  TechnicalContact: tags.TechnicalContact
  Description: tags.Description
  DatabricksUIPrivate:databricksPrivate
  AMLStudioUIPrivate: AMLStudioUIPrivate
}
*/

var deploymentProjSpecificUniqueSuffix = '${projectName}${locationSuffix}${env}${aifactorySuffixRG}'
var sweden_central_adf_missing =  false // (location == 'swedencentral')?true:false
var sweden_central_dbx_missing = false // (location == 'swedencentral')?true:false
var sweden_central_appInsight_classic_missing = (location == 'swedencentral')?true:false

@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj HUB
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

module projectResourceGroup '../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'prjResourceGroup${deploymentProjSpecificUniqueSuffix}'
  params: {
    rgName: targetResourceGroup
    location: location
    tags: tags2
  }
}

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}


var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'

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

var laName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource logAnalyticsWorkspaceOpInsight 'Microsoft.OperationalInsights/workspaces@2020-08-01' existing = {
  name: laName
  scope:commonResourceGroupRef
}

module applicationInsight '../modules/applicationInsights.bicep'= if(sweden_central_appInsight_classic_missing== false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsights4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}' // max 255 chars
    tags: tags2
    location: location
  }

  dependsOn: [
    projectResourceGroup
    
  ]
}

module applicationInsightSWC '../modules/applicationInsightsRGmode.bicep'= if(sweden_central_appInsight_classic_missing== true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AppInsightsSWC4${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
    logAnalyticsWorkspaceID:logAnalyticsWorkspaceOpInsight.id
    tags: tags2
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
    tags: tags2
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module vmPrivate '../modules/virtualMachinePrivate.bicep' = if(enableVmPubIp == false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: 'Standard_DS3_v2'
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: tags2
    keyvaultName: kv1.outputs.keyvaultName
  }
  dependsOn: [
    kv1
    projectResourceGroup
    
  ]
}

module vmPublic '../modules/virtualMachinePublic.bicep' = if(enableVmPubIp == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'publicVM${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: 'Standard_DS3_v2'
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
    subnetName: defaultSubnet
    vnetId: vnetId
    tags: tags2
    keyvaultName: kv1.outputs.keyvaultName
  }

  dependsOn: [
    kv1
    projectResourceGroup
  ]
}

var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
module acr '../modules/containerRegistry.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLContainerReg4${deploymentProjSpecificUniqueSuffix}'
  params: {
    containerRegistryName: 'acr${projectName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
    skuName: 'Premium'
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}${locationSuffix}-containerreg-to-vnt-mlcmn'
    tags: tags2
    location:location
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module sacc '../modules/storageAccount.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLStorageAcc4${deploymentProjSpecificUniqueSuffix}'
  params: {
    storageAccountName: replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}${prjResourceSuffixNoDash}${env}','-','')
    skuName: 'Standard_LRS'
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-blob-to-vnt-mlcmn'
    filePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-file-to-vnt-mlcmn'
    queuePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-queue-to-vnt-mlcmn'
    tablePrivateEndpointName: 'pend-sa-${projectName}${locationSuffix}${env}-table-to-vnt-mlcmn'
    tags: tags2
  }

  dependsOn: [
    projectResourceGroup
  ]
}

module kv1 '../modules/keyVault.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AMLKeyVault4${deploymentProjSpecificUniqueSuffix}'
  params: {
    keyvaultName: keyvaultName
    location: location
    tags: tags2
    enablePurgeProtection:true
    tenantIdentity: tenantId
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-kv1-to-vnt-mlcmn'
    keyvaultNetworkPolicySubnets: [
      '${vnetId}/subnets/${defaultSubnet}'
      '${vnetId}/subnets/snt-${projectName}-aks'
      '${vnetId}/subnets/snt-${projectName}-dbxpub'
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
    kv1
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
  name: '${keyvaultName}APTechContact${projectNumber}${locationSuffix}${env}'
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

var kvNameCommon = kvNameFromCOMMON_param != '' ? kvNameFromCOMMON_param : 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
resource commonKv 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: kvNameCommon
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
}

module kvCommonAccessPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: '${kvNameCommon}GetList${projectNumber}${locationSuffix}${env}'
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


module privateDnsStorage '../modules/privateDns.bicep' = if(centralDnsZoneByPolicyInHub==false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsZoneLinkStorage${projectNumber}${locationSuffix}${env}'
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
  name: 'privateDnsZoneLinkKeyVault${projectNumber}${locationSuffix}${env}'
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
  name: 'privateDnsZoneLinkACR${projectNumber}${locationSuffix}${env}'
  params: {
    dnsConfig: acr.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
  ]
}

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

module aml '../modules/machineLearning.bicep'= if(enableAML) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'AzureMachineLearning4${deploymentProjSpecificUniqueSuffix}'
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
    applicationInsights: (sweden_central_appInsight_classic_missing == true)? applicationInsightSWC.outputs.ainsId: applicationInsight.outputs.ainsId 
    aksSubnetId: aksSubnetId
    aksSubnetName:aksSubnetName
    aksDnsServiceIP:aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    tags: tags2
    vnetId: vnetId
    subnetName: defaultSubnet
    privateEndpointName: 'pend-${projectName}-aml-to-vnt-mlcmn'
    amlPrivateDnsZoneID: privateLinksDnsZones['amlworkspace'].id
    notebookPrivateDnsZoneID:privateLinksDnsZones['notebooks'].id
    allowPublicAccessWhenBehindVnet:(AMLStudioUIPrivate == true)? false:true
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

var evenhubNameSpaceAndWsName = 'ev-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
module eventHubLogging '../modules/eventhub.bicep' = if(enableEventhubs) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'EventHub4${deploymentProjSpecificUniqueSuffix}'
  params: {
    namespaceName: evenhubNameSpaceAndWsName
    location:location
    privateEndpointName:'pend-${projectName}-ev-to-vnt-mlcmn'
    tags: tags2
    vnetId: vnetId
    subnetName: defaultSubnet
  }
  dependsOn: [
    projectResourceGroup
  ]
      
}

var databricksName = 'dbx-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var databricksNameP = 'dbxp-${projectName}-${locationSuffix}-${env}${resourceSuffix}'
var databricksManagedRG = '${targetResourceGroup}${resourceSuffix}-dbxmgmt'
var databricksManagedRGId = '${subscription().id}/resourceGroups/${databricksManagedRG}'

resource amlResource 'Microsoft.MachineLearningServices/workspaces@2021-04-01' existing = {
  name: amlName
  scope:resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

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
    tags: tags2
  }
  dependsOn: [
    projectResourceGroup
    aml
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
    tags: tags2
    vnetId: vnetId
  }
  dependsOn: [
    projectResourceGroup
    aml
  ]
}

var mangedIdentityName = 'esml${projectName}${env}DbxMI'

module dbxMIPriv '../modules/databricksManagedIdentityRBAC.bicep' = if(databricksPrivate == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'dbxMIOwnerPriv${projectNumber}${locationSuffix}${env}'
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
  name: 'dbxMIOwner${projectNumber}${locationSuffix}${env}'
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
var mergeVirtualNetworkRulesMerged = union(existingRules, virtualNetworkRules2Add)

param lakeContainerName string
module dataLake '../modules/dataLake.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'saUpdateVnetLake${projectNumber}${locationSuffix}${env}'
  params: {
    storageAccountName: datalakeName
    containerName: lakeContainerName
    skuName: skuNameStorage
    location: keepLocation
    vnetId: vnetId
    subnetName: defaultSubnet
    blobPrivateEndpointName: 'pend-${datalakeName}-blob-to-vnt-esmlcmn'
    filePrivateEndpointName: 'pend-${datalakeName}-file-to-vnt-esmlcmn'
    dfsPrivateEndpointName: 'pend-${datalakeName}-dfs-to-vnt-esmlcmn'
    queuePrivateEndpointName: 'pend-${datalakeName}-queue-to-vnt-esmlcmn'
    tablePrivateEndpointName: 'pend-${datalakeName}-table-to-vnt-esmlcmn'
    tags: keepTags
    virtualNetworkRules: mergeVirtualNetworkRulesMerged
  }
  dependsOn: [
    commonResourceGroupRef
    aml // optional, but convenient: aml success, optherwise virtualNetworkRules needs to be removed manually if aml fails..and rerun
  ]
}

module privateDnsAzureDatafactory '../modules/privateDns.bicep' = if((centralDnsZoneByPolicyInHub==false) && (sweden_central_adf_missing==false)){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateDnsZoneLinkADF${projectNumber}${locationSuffix}${env}'
  params: {
    dnsConfig: adf.outputs.dnsConfig
    privateLinksDnsZones: privateLinksDnsZones
  }
  dependsOn: [
    projectResourceGroup
    adf
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
  name: 'spProjectSPAccessGet${projectNumber}${locationSuffix}${env}' //'${keyvaultName}/add'
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
  name: 'adfAccessPolicyGet${projectNumber}${locationSuffix}${env}'
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
  name: 'spDBXAccessPolicyGetList${projectNumber}${locationSuffix}${env}'
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

var cmnName = 'cmn'
var kvNameFromCOMMON = kvNameFromCOMMON_param != '' ? kvNameFromCOMMON_param : 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'

resource kvFromCommon 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)
  name: kvNameFromCOMMON
}

module spCommonKeyvaultPolicyGetList '../modules/kvCmnAccessPolicys.bicep' = if(databricksOID != null) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'spCmnKVPolicyGetList${projectNumber}${locationSuffix}${env}'
  params: {
    keyVaultPermissions: secretGet
    keyVaultResourceName: kvFromCommon.name
    policyName: 'add'
    principalId: externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    additionalPrincipalIds:[]
  }
  dependsOn: [
    kvFromCommon
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}

module rbacLake '../esml-common/modules-common/lakeRBAC.bicep' = if(sweden_central_adf_missing== false){
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacLake4Project${projectNumber}${locationSuffix}${env}'
  params: {
    amlPrincipalId: aml.outputs.principalId
    userPrincipalId: technicalContactId
    adfPrincipalId: adf.outputs.principalId
    datalakeName: datalakeName
  }
  dependsOn: [
    dataLake
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    adf
    logAnalyticsWorkspaceOpInsight
  ]
}

module rbackDatabricks '../modules/databricksRBAC.bicep' = if(databricksPrivate == false) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX4Project${projectNumber}${locationSuffix}${env}'
  params: {
    databricksName: databricksName
    userPrincipalId: technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    dbx
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}
module rbackDatabricksPriv '../modules/databricksRBAC.bicep' = if(databricksPrivate == true) {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBXP4Project${projectNumber}${locationSuffix}${env}'
  params: {
    databricksName: databricksNameP
    userPrincipalId: technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    dbxPrivate
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}


// Needed if connnecting from Databricks to Azure ML workspace
// Note: SP OID: it must be the OBJECT ID of a service principal, not the OBJECT ID of an Application, different thing, and I have to agree it is very confusing.
module rbackSPfromDBX2AML '../modules/machinelearningRBAC.bicep' = if(sweden_central_adf_missing== false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX2AazureMLwithProjectSP${projectNumber}${locationSuffix}${env}'
  params: {
    amlName:amlName
    projectSP:externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)
    adfSP:adf.outputs.principalId
    projectADuser:technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    adf
    aml // aml success, optherwise this needs to be removed manually if aml fails..and rerun
    logAnalyticsWorkspaceOpInsight // aml success, optherwise this needs to be removed manually if aml fails..and rerun
  ]
}
module rbackSPfromDBX2AMLSWC '../modules/machinelearningRBAC.bicep' = if(sweden_central_adf_missing==true){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacDBX2AMLProjectSPSWC${projectNumber}${locationSuffix}${env}'
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

module rbacADFfromUser '../modules/datafactoryRBAC.bicep' = if(sweden_central_adf_missing== false){
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'rbacADFFromAMLorProjSP${projectNumber}${locationSuffix}${env}'
  params: {
    datafactoryName:adfName
    userPrincipalId:technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [
    adf
    rbackSPfromDBX2AML
  ]
}

module rbacReadUsersToCmnVnetBastion '../modules/vnetRBACReader.bicep' = if(addBastionHost==true) {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacReadUsersToCmnVnetBastion${projectNumber}${locationSuffix}${env}'
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
    rbackSPfromDBX2AML
    vmPrivate
  ]
}

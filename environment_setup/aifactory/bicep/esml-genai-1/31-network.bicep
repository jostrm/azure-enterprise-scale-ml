@description('Specifies cidr notation for genai subnet')
param genaiSubnetCidr string
@description('Specifies cidr notation for aks subnet')
param aksSubnetCidr string
param aks2SubnetCidr string = ''
@description('Specifies cidr notation for Azure Container Apps subnet')
param acaSubnetCidr string = ''
param aca2SubnetCidr string = ''
@description('Specifies cidr notation for databricks subnets')
param dbxPrivSubnetCidr string = ''
param dbxPubSubnetCidr string = ''

@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string
@description('Specifies the short location notation, such as "weu". This name is reflected in resource group and sub-resources')
param locationSuffix string
@description('Specifies virtual network name')
param vnetNameBase string
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
var projectName = 'prj${projectNumber}'
@description('Deployment location')
param location string
param commonResourceSuffix string
@description('Meta. Needed from ADO. To be grep from ADO in the az deployement call')
param vnetResourceGroup string 
@description('If BYO vNet is overriden, in parameter file: 10-esml-globals-override.json')
param vnetResourceGroup_param string = ''
@description('If BYO vNet is overriden, in parameter file: 10-esml-globals-override.json')
param vnetNameFull_param string = ''
@description('If Common resource group name is overriden, in parameter file: 10-esml-globals-override.json')
param commonResourceGroup_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''
param useCommonACR bool = true
param BYO_subnets bool = false
param network_env string =''
param subnetCommon string = ''
param subnetCommonScoring string = ''
param subnetCommonPowerbiGw string = ''
param subnetProjGenAI string = ''
param subnetProjAKS string = ''
param subnetProjDatabricksPublic string = ''
param subnetProjDatabricksPrivate string = ''
param subnetProjACA string = ''

// Subnet existence flags
@description('Specifies whether GenAI subnet already exists')
param sntGenaiExists bool = false
@description('Specifies whether ACA subnet already exists')
param sntAcaExists bool = false
@description('Specifies whether ACA002 subnet already exists')
param sntAca002Exists bool = false
@description('Specifies whether AKS subnet already exists')
param sntAksExists bool = false
@description('Specifies whether AKS002 subnet already exists')
param sntAks002Exists bool = false
@description('Specifies whether Databricks Private subnet already exists')
param sntDatabricksPrivExists bool = false
@description('Specifies whether Databricks Public subnet already exists')
param sntDatabricksPubExists bool = false

param DOCS_byovnet_example string = ''
param DOCS_byosnet_common_example string = ''
param DOCS_byosnet_project_example string = ''
param byoASEv3 bool = false
param byoAseFullResourceId string = ''
param byoAseAppServicePlanResourceId string = ''

// To get TAGS from file: 10-esml-globals-1.json
param tags object
param aifactorySuffixRG string = '' // dummy
param commonRGNamePrefix string = '' // dummy

var vnetNameFull = vnetNameFull_param  != '' ? vnetNameFull_param  : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

var vNetSalt = substring(uniqueString(resourceGroup().id), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${vNetSalt}${locationSuffix}-${env}${commonResourceSuffix}'

@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false 

var aksSubnetSettings =   {
  cidr: aksSubnetCidr
  name: 'aks'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
  ]
}
var aks2SubnetSettings =  {
  cidr: aks2SubnetCidr
  name: 'aks'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
  ]
}

module nsgAKS '../modules/aksNsg.bicep' = if(!sntAksExists){
  name: 'aksNsgAKS-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aks-nsg-${projectName}-${locationSuffix}-${env}' // AKS-NSG-PRJ001-EUS2-DEV in 'aks-nsg-prj001-eus2-dev'
    location: location
    tags:tags
  }
}
module nsgAKS2 '../modules/aksNsg.bicep' = if (!empty(aks2SubnetCidr) && !sntAks002Exists) {
  name: 'aks2Nsg-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aks2-nsg-${projectName}-${locationSuffix}-${env}' // AKS-NSG-PRJ001-EUS2-DEV in 'aks-nsg-prj001-eus2-dev'
    location: location
    tags:tags
  }
}


module aksSnt '../modules/subnetWithNsg.bicep' = if(!sntAksExists){
  name: 'aks-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-aks'
    virtualNetworkName: vnetNameFull
    addressPrefix: aksSubnetSettings.cidr
    location: location
    serviceEndpoints: aksSubnetSettings.serviceEndpoints
    delegations: aksSubnetSettings.delegations
    nsgId:nsgAKS.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    nsgAKS
  ]
}
module aks2Snt '../modules/subnetWithNsg.bicep' = if (!empty(aks2SubnetCidr) && !sntAks002Exists) {
  name: 'aks2-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-aks-002'
    virtualNetworkName: vnetNameFull
    addressPrefix: aks2SubnetSettings.cidr
    location: location
    serviceEndpoints: aks2SubnetSettings.serviceEndpoints
    delegations: aks2SubnetSettings.delegations
    nsgId: !empty(aks2SubnetCidr) ? nsgAKS2!.outputs.nsgId : ''
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    aksSnt
    ...((!empty(aks2SubnetCidr)) ? [nsgAKS2] : [])
  ]
}

// GenAI

var genaiSubnetSettings =   {
  cidr: genaiSubnetCidr
  name: 'genaiSubnetSettings'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
  ]
}

module nsgGenAI '../modules/nsgGenAI.bicep' = if(!sntGenaiExists){
  name: 'nsgGenAI-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'genai-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}

module genaiSnt '../modules/subnetWithNsg.bicep' = if(!sntGenaiExists){
  name: 'genai-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-genai'
    virtualNetworkName: vnetNameFull
    addressPrefix: genaiSubnetSettings.cidr
    location: location
    serviceEndpoints: genaiSubnetSettings.serviceEndpoints
    delegations: genaiSubnetSettings.delegations
    nsgId:nsgGenAI.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    ...((!empty(aks2SubnetCidr)) ? [aks2Snt] : [aksSnt])
    nsgGenAI
    aksSnt
  ]
}

// Azure Container Apps
var acaSubnetSettings =   {
  cidr: acaSubnetCidr
  name: 'acaSubnetSettings'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
    'Microsoft.ContainerRegistry'
    'Microsoft.AzureCosmosDB'
    'Microsoft.Web'
  ]
}
var aca2SubnetSettings =   {
  cidr: aca2SubnetCidr
  name: 'aca2SubnetSettings'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
    'Microsoft.ContainerRegistry'
    'Microsoft.AzureCosmosDB'
    'Microsoft.Web'
  ]
}

module nsgAca '../modules/nsgGenAI.bicep' = if(!sntAcaExists){
  name: 'nsgAca-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aca-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}
module nsg2Aca '../modules/nsgGenAI.bicep' = if (!empty(aca2SubnetCidr) && !sntAca002Exists) {
  name: 'nsgAca2-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aca2-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}
module acaSnt '../modules/subnetWithNsg.bicep' = if(!sntAcaExists){
  name: 'acaSnet-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-aca'
    virtualNetworkName: vnetNameFull
    addressPrefix: acaSubnetSettings.cidr
    location: location
    serviceEndpoints: acaSubnetSettings.serviceEndpoints
    delegations: []
    nsgId:nsgAca.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    ...((!empty(aks2SubnetCidr)) ? [aks2Snt] : [aksSnt])
    nsgGenAI
    genaiSnt
  ]
}
module acaSnt2 '../modules/subnetWithNsg.bicep' = if (!empty(aca2SubnetCidr) && !sntAca002Exists) {
  name: 'acaSnet2-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-aca-002'
    virtualNetworkName: vnetNameFull
    addressPrefix: aca2SubnetSettings.cidr
    location: location
    serviceEndpoints: aca2SubnetSettings.serviceEndpoints
    delegations: []
    nsgId: !empty(aca2SubnetCidr) ? nsg2Aca!.outputs.nsgId : ''
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    ...((!empty(aks2SubnetCidr)) ? [aks2Snt] : [aksSnt])
    nsgGenAI
    genaiSnt
    acaSnt
    ...((!empty(aca2SubnetCidr)) ? [nsg2Aca] : [])
  ]
}

// Subnet settings
var dataBricksPrivateSubnetSettings = {
  cidr: dbxPrivSubnetCidr
  name: 'dbxpriv'
  delegations: [
    'Microsoft.Databricks/workspaces'
  ]
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
  ]
}

var dataBricksPublicSubnetSettings =   {
  cidr: dbxPubSubnetCidr
  name: 'dbxpub'
  delegations: [
    'Microsoft.Databricks/workspaces'
  ]
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
  ]
}

module nsgDbx '../modules/databricksNsg.bicep' = if(!empty(dbxPubSubnetCidr) && !sntDatabricksPubExists){
  name: 'dbxNsg-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'dbx-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}

module dbxPubSnt '../modules/subnetWithNsg.bicep' = if(!empty(dbxPubSubnetCidr) && !sntDatabricksPubExists){
  name: 'dbxpub-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-dbxpub'
    virtualNetworkName: vnetNameFull
    addressPrefix: dataBricksPublicSubnetSettings.cidr
    location: location
    serviceEndpoints: dataBricksPublicSubnetSettings.serviceEndpoints
    delegations: dataBricksPublicSubnetSettings.delegations
    nsgId: nsgDbx.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  dependsOn: [
    nsgDbx
    ...((!empty(aca2SubnetCidr)) ? [acaSnt2] : [acaSnt])
    acaSnt
    aksSnt
    genaiSnt
  ]
}

module dbxPrivSnt '../modules/subnetWithNsg.bicep' = if(!empty(dbxPrivSubnetCidr) && !sntDatabricksPrivExists){
  name: 'dbxpriv-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'snt-${projectName}-dbxpriv'
    virtualNetworkName: vnetNameFull
    addressPrefix: dataBricksPrivateSubnetSettings.cidr
    location: location
    serviceEndpoints: dataBricksPrivateSubnetSettings.serviceEndpoints
    delegations: dataBricksPrivateSubnetSettings.delegations
    nsgId: nsgDbx.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  // Make sure that no overlapping processes are created
  // On some cases AzureRm will return an error if paralell
  // subnet creation processes are started
  dependsOn: [
    nsgDbx
    dbxPubSnt
    acaSnt
    aksSnt
    genaiSnt
  ]
}
// The following outputs are used for network_parameters.json
// that is generated by generateNetworkParameters.ps1 script
output aksSubnetId string = aksSnt.outputs.subnetId
output aks2SubnetId string = empty(aks2SubnetCidr) ? '' : aks2Snt!.outputs.subnetId
output genaiSubnetId string = genaiSnt.outputs.subnetId
output acaSubnetId string = acaSnt.outputs.subnetId
output aca2SubnetId string = empty(aca2SubnetCidr) ? '' : acaSnt2!.outputs.subnetId
output dbxPubSubnetName string = empty(dbxPubSubnetCidr) ? '' : 'snt-${projectName}-dbxpub'
output dbxPrivSubnetName string = empty(dbxPrivSubnetCidr) ? '' : 'snt-${projectName}-dbxpriv'

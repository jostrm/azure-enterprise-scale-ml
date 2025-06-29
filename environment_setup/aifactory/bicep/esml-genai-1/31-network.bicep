@description('Specifies cidr notation for genai subnet')
param genaiSubnetCidr string
@description('Specifies cidr notation for aks subnet')
param aksSubnetCidr string
@description('Specifies cidr notation for Azure Container Apps subnet')
param acaSubnetCidr string = ''

//@description('Specifies cidr notation for private databricks subnet')
//param dbxPrivSubnetCidr string = ''

//@description('Specifies cidr notation for public databricks subnet')
//param dbxPubSubnetCidr string = ''

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

module nsgAKS '../modules/aksNsg.bicep' = {
  name: 'aksNsgAKS-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aks-nsg-${projectName}-${locationSuffix}-${env}' // AKS-NSG-PRJ001-EUS2-DEV in 'aks-nsg-prj001-eus2-dev'
    location: location
    tags:tags
  }
}

module aksSnt '../modules/subnetWithNsg.bicep' = {
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

module nsgGenAI '../modules/nsgGenAI.bicep' = {
  name: 'nsgGenAI-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'genai-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}

module genaiSnt '../modules/subnetWithNsg.bicep' = {
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
    aksSnt
    nsgGenAI
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

module nsgAca '../modules/nsgGenAI.bicep' = {
  name: 'nsgAca-${deploymentProjSpecificUniqueSuffix}'
  params: {
    name: 'aca-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags:tags
  }
}
module acaSnt '../modules/subnetWithNsg.bicep' = {
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
    aksSnt
    nsgGenAI
    genaiSnt
  ]
}


// The following outputs are used for network_parameters.json
// that is generated by generateNetworkParameters.ps1 script
output aksSubnetId string = aksSnt.outputs.subnetId
output genaiSubnetId string = genaiSnt.outputs.subnetId
output acaSubnetId string = acaSnt.outputs.subnetId
output dbxPubSubnetName string = ''
output dbxPrivSubnetName string = ''

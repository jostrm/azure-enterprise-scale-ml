@description('Specifies cidr notation for genai subnet')
param genaiSubnetCidr string
@description('Specifies cidr notation for aks subnet')
param aksSubnetCidr string

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
param location string = resourceGroup().location
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

var vnetNameFull = vnetNameFull_param  != '' ? vnetNameFull_param  : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false 

var aksSubnetSettings =   {
  cidr: aksSubnetCidr
  name: 'aks'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
  ]
}
module nsgAKS '../modules/aksNsg.bicep' = {
  name: 'aksNsgAKS'
  params: {
    name: 'aks-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags: {
      Description: 'AKS Nsg'
    }
  }
}

module aksSnt '../modules/subnetWithNsg.bicep' = {
  name: '${projectName}-aks'
  params: {
    name: 'snt-${projectName}-aks'
    virtualNetworkName: vnetNameFull
    addressPrefix: aksSubnetSettings['cidr']
    location: location
    serviceEndpoints: aksSubnetSettings['serviceEndpoints']
    delegations: aksSubnetSettings['delegations']
    nsgId:nsgAKS.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  // Make sure that no overlapping processes are created
  // On some cases AzureRm will return an error if paralell
  // subnet creation processes are started
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
  ]
}

module nsgGenAI '../modules/aksNsg.bicep' = {
  name: 'nsgGenAI'
  params: {
    name: 'aks-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags: {
      Description: 'AKS Nsg'
    }
  }
}

module genaiSnt '../modules/subnetWithNsg.bicep' = {
  name: '${projectName}-genai'
  params: {
    name: 'snt-${projectName}-genai'
    virtualNetworkName: vnetNameFull
    addressPrefix: genaiSubnetSettings['cidr']
    location: location
    serviceEndpoints: genaiSubnetSettings['serviceEndpoints']
    delegations: genaiSubnetSettings['delegations']
    nsgId:nsgGenAI.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  dependsOn: [
    aksSnt
    nsgGenAI
  ]
}


// The following outputs are used for network_parameters.json
// that is generated by generateNetworkParameters.ps1 script
output aksSubnetId string = aksSnt.outputs.subnetId
output genaiSubnetId string = genaiSnt.outputs.subnetId
output dbxPubSubnetName string = ''
output dbxPrivSubnetName string = ''

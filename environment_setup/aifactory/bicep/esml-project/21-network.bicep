// ESML-COMMON Resource group is known, and where we add subnets, from ADO  --resource-group "$(cat subnetParameters.json | grep vnetResourceGroup -A1 | tail -n1 | cut -d: -f2 | tr -d " \"")" \
@description('Specifies cidr notation for aks subnet')
param aksSubnetCidr string

@description('Specifies cidr notation for private databricks subnet')
param dbxPrivSubnetCidr string

@description('Specifies cidr notation for public databricks subnet')
param dbxPubSubnetCidr string

@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string
@description('Specifies the short location notation, such as "weu". This name is reflected in resource group and sub-resources')
param locationSuffix string
// virtual network related parameters
// make sure that subnets used for private endpoints do NOT have PrivateEndpointNetworkPolicies set to "enabled"
// https://docs.microsoft.com/sv-se/azure/private-link/disable-private-endpoint-network-policy
@description('Specifies virtual network name')
param vnetNameBase string

// General parameters
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
var projectName = 'prj${projectNumber}'

@description('Deployment location')
param location string = resourceGroup().location // from ESML-COMMON RG
param commonResourceSuffix string

@description('Meta. Needed from ADO. To be grep from ADO in the az deployement call')
param vnetResourceGroup string

param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param commonResourceGroup_param string = ''
param datalakeName_param string = ''
param kvNameFromCOMMON_param string = ''

var vnetNameFull = vnetNameFull_param  != '' ? vnetNameFull_param  : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj HUB

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

var aksSubnetSettings =   {
  cidr: aksSubnetCidr
  name: 'aks'
  delegations: []
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
  ]
}

module nsg '../modules/databricksNsg.bicep' = {
  name: 'dbxNsg'
  params: {
    name: 'dbx-nsg-${projectName}-${locationSuffix}-${env}'
    location: location
    tags: {
      Description: 'databricks Nsg'
    }
  }
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

module dbxPubSnt '../modules/subnetWithNsg.bicep' = {
  name: '${projectName}-dbxpub'
  params: {
    name: 'snt-${projectName}-dbxpub'
    virtualNetworkName: vnetNameFull
    addressPrefix: dataBricksPublicSubnetSettings['cidr']
    location: location
    serviceEndpoints: dataBricksPublicSubnetSettings['serviceEndpoints']
    delegations: dataBricksPublicSubnetSettings['delegations']
    nsgId: nsg.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  dependsOn: [
    nsg
  ]
}

module dbxPrivSnt '../modules/subnetWithNsg.bicep' = {
  name: '${projectName}-dbxpriv'
  params: {
    name: 'snt-${projectName}-dbxpriv'
    virtualNetworkName: vnetNameFull
    addressPrefix: dataBricksPrivateSubnetSettings['cidr']
    location: location
    serviceEndpoints: dataBricksPrivateSubnetSettings['serviceEndpoints']
    delegations: dataBricksPrivateSubnetSettings['delegations']
    nsgId: nsg.outputs.nsgId
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }

  // Make sure that no overlapping processes are created
  // On some cases AzureRm will return an error if paralell
  // subnet creation processes are started
  dependsOn: [
    nsg
    dbxPubSnt
  ]
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
    nsg
    dbxPubSnt
    dbxPrivSnt
    nsgAKS
  ]
}

// The following outputs are used for network_parameters.json
// that is generated by generateNetworkParameters.ps1 script 
output dbxPubSubnetName string = 'snt-${dbxPubSnt.name}'
output dbxPrivSubnetName string = 'snt-${dbxPrivSnt.name}'
output aksSubnetId string = aksSnt.outputs.subnetId

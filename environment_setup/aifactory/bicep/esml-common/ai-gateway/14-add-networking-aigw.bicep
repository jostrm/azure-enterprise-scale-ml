/*
Docs: https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator/blob/main/guides/bring-your-own-network.md
*/
param name string = 'ai-gateway'
param tags object
param location string
param locationSuffix string
param env string
param aifactorySuffixRG string
param commonRGNamePrefix string
param vnetName string
param commonResourceSuffix string
param subscriptionIdDevTestProd string
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param vnetNameBase string = 'vnt-esmlcmn'
param centralDnsZoneByPolicyInHub bool = false // If true, use the DNS zone in the hub for the private endpoint. If false, use the DNS zone in the same resource group as the private endpoint.

// CIDR
param CIDRApim string
param CIDRFunctionApp string

var commonResourceGroupName = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' 
var vnetResourceGroupName = vnetResourceGroup_param != '' ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroupName
var vnetNameFull = vnetNameFull_param  != '' ?vnetNameFull_param: '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

resource vnetResourceGroup 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: vnetResourceGroupName
  scope:subscription(subscriptionIdDevTestProd)
}

var vNetRGsalt = substring(uniqueString(vnetResourceGroup.id), 0, 5)
var commmonRGsalt = substring(uniqueString(commonResourceGroupName), 0, 5)
var uniqueDetermenistic = '${commmonRGsalt}${vNetRGsalt}'

module nsgAIGateway '../modules-common/nsgAIGateway.bicep' = {
  name: 'depl-aigw-apim-nsg-${name}-${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${name}-apim'
    tags: tags
    location:location
  }
}

// If this subnet has a route table, it should include a route to handle APIM management control plane traffic.
module routeTableAIGateway '../modules-common/routeTableAIGateway.bicep' = {
  name: 'depl-aigw-rt-${name}-${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'rt-${name}'
    tags: tags
    location:location
  }
}

//If there is a forced tunneling applied on the subnet (directly through route table or in-directly through BGP), you need to enable service endpoints for the following services (only on the APIM subnet)

// SUBNET - APIM
var apimSubnetSettings =   {
  cidr: CIDRApim
  name: 'apimSubnetSettings'
  delegations: []
  serviceEndpoints: [
    'Microsoft.AzureActiveDirectory'
    'Microsoft.EventHub'
    'Microsoft.KeyVault'
    'Microsoft.ServiceBus'
    'Microsoft.Sql'
    'Microsoft.Storage'
  ]
}

module subnetApimAIGw '../../modules/subnetWithNsg.bicep' = {
  name: 'depl-apimAiGW-${uniqueDetermenistic}'
  params: {
    name: 'snt-${name}-apim'
    virtualNetworkName: vnetNameFull
    addressPrefix: apimSubnetSettings.cidr
    location: location
    serviceEndpoints: apimSubnetSettings.serviceEndpoints
    delegations: apimSubnetSettings.delegations
    routeTableId: routeTableAIGateway.outputs.id
    nsgId:nsgAIGateway.outputs.id
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    vnetResourceGroup
  ]
}

// SUBNET - FUNCTION APP

var functionAppSubnetSettings =   {
  cidr: CIDRFunctionApp
  name: 'functionAppSubnetSettings'
  delegations: [
    'Microsoft.Web/serverFarms'
  ]
  serviceEndpoints: [
    'Microsoft.KeyVault'
    'Microsoft.Storage'
    'Microsoft.CognitiveServices'
    'Microsoft.ContainerRegistry'
    'Microsoft.AzureCosmosDB'
    'Microsoft.Web'
  ]
}

module nsgFunctionApp '../modules-common/nsgFunctionApp.bicep' = {
  name: 'depl-aigw-func-nsg-${name}-${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${name}-function-app'
    tags: tags
    location:location
  }
}

module subnetFunctionApp '../../modules/subnetWithNsg.bicep' = {
  name: 'depl-subnetFunctionApp-${uniqueDetermenistic}'
  params: {
    name: 'snt-${name}-function-app'
    virtualNetworkName: vnetNameFull
    addressPrefix: functionAppSubnetSettings.cidr
    location: location
    serviceEndpoints: functionAppSubnetSettings.serviceEndpoints
    delegations: functionAppSubnetSettings.delegations
    nsgId:nsgFunctionApp.outputs.id
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    vnetResourceGroup
  ]
}

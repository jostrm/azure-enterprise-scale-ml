targetScope = 'subscription'  // Just to avoid sending a static RG. Instead: ESML dynamic via naming convention and parameters
@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment. This name is reflected in resource group and sub-resources')
param env string
@description('Specifies the short location notation. This name is reflected in resource group and sub-resources')
param locationSuffix string
param resourceSuffix string
@description('Deployment location')
param location string
@description('tags')
param tags object
@description('AI Factory suffix. If you have multiple instances')
param aifactorySuffixRG string =''
@description('Specifies the virtual network name')
param vnetNameBase string
@description('CIDR for common vNet ')
param common_vnet_cidr string
@description('common Power BI subnet for vNet gateway')
param common_pbi_subnet_name string
@description('CIDR for common Power BI subnet for gateway')
param common_pbi_subnet_cidr string
@description('common subnet')
param common_subnet_name string
@description('CIDR for common subnet')
param common_subnet_cidr string
@description('common Bastion host subnet for RDP access over private IP')
param common_bastion_subnet_name string
@description('common Bastion host subnet CIDR')
param common_bastion_subnet_cidr string
@description('common scoring subnet CIDR')
param common_subnet_scoring_cidr string
@description('CIDR range. xx.YY.x.x/16')
param cidr_range string
@description('Resource group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string = ''
@description('Optional:Whitelist IP addresses from project members to see keyvault, and to connect via Bastion')
param IPwhiteList string = ''
@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jå

var subscriptionIdDevTestProd = subscription().subscriptionId
var common_vnet_cidr_v = replace(common_vnet_cidr,'XX',cidr_range)
var common_subnet_cidr_v = replace(common_subnet_cidr,'XX',cidr_range)
var common_pbi_subnet_cidr_v = replace(common_pbi_subnet_cidr,'XX',cidr_range)
var common_bastion_subnet_cidr_v = replace(common_bastion_subnet_cidr,'XX',cidr_range)
var common_subnet_scoring_cidr_v = replace(common_subnet_scoring_cidr,'XX',cidr_range)
var vnetNameFull ='${vnetNameBase}-${locationSuffix}-${env}${resourceSuffix}'  // vnt-esmlcmn-weu-dev-001
var commonResourceGroupName = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // esml-common-weu-dev-002 // esml-common-weu-dev-002 // DEPENDENCIES - should exist

resource esmlCommonResourceGroup 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: commonResourceGroupName
  scope:subscription(subscriptionIdDevTestProd)
}

module nsgCommon '../modules-common/nsgCommon.bicep' = {
  name: 'nsg-${common_subnet_name}'
  scope: esmlCommonResourceGroup
  params: {
    name: 'nsg-${common_subnet_name}'
    tags: tags
    location:location
    bastionIpRange: common_bastion_subnet_cidr_v
  }
}

module nsgCommonScoring '../modules-common/nsgCommonScoring.bicep' = {
  name: 'nsg-${common_subnet_name}-scoring'
  scope: esmlCommonResourceGroup
  params: {
    name: 'nsg-${common_subnet_name}-scoring'
    tags: tags
    location:location
  }
}

module nsgBastion '../modules-common/nsgBastion.bicep' = {
  name: 'nsg-${common_bastion_subnet_name}'
  scope: esmlCommonResourceGroup
  params: {
    name: 'nsg-${common_bastion_subnet_name}'
    tags: tags
    location:location
    IPwhiteList:IPwhiteList
  }
}

module nsgPBI  '../modules-common/nsgPowerBI.bicep'= {
  scope: esmlCommonResourceGroup
  name: 'nsg-${common_pbi_subnet_name}-depl'
  params: {
    name: 'nsg-${common_pbi_subnet_name}'
    tags: tags
    location:location
  }
}
module vNetCommon '../modules-common/vNetCommon.bicep' = {
  scope: esmlCommonResourceGroup
  name: vnetNameFull
  params: {
    location: location
    common_pbi_subnet_cidr: common_pbi_subnet_cidr_v
    common_pbi_subnet_name: common_pbi_subnet_name
    common_subnet_cidr: common_subnet_cidr_v
    common_subnet_scoring_cidr:common_subnet_scoring_cidr_v
    common_subnet_name: common_subnet_name
    common_vnet_cidr: common_vnet_cidr_v
    common_bastion_subnet_name: common_bastion_subnet_name
    common_bastion_subnet_cidr: common_bastion_subnet_cidr_v
    tags: tags
    vnetNameFull: vnetNameFull
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
  dependsOn: [
    nsgCommon
    nsgBastion
    nsgPBI
    nsgCommonScoring
  ]
}


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
param commonResourceSuffix string
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
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
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
param deployAIGatewayNetworking bool = false // If true, deploys the AI Gateway networking also
param deployOnlyAIGatewayNetworking bool = false
param ai_gateway_apim_cidr string = ''
param ai_gateway_app_cidr string = ''

var subscriptionIdDevTestProd = subscription().subscriptionId
var common_vnet_cidr_v = replace(common_vnet_cidr,'XX',cidr_range)
var common_subnet_cidr_v = replace(common_subnet_cidr,'XX',cidr_range)
var common_pbi_subnet_cidr_v = replace(common_pbi_subnet_cidr,'XX',cidr_range)
var common_bastion_subnet_cidr_v = replace(common_bastion_subnet_cidr,'XX',cidr_range)
var common_subnet_scoring_cidr_v = replace(common_subnet_scoring_cidr,'XX',cidr_range)
var ai_gateway_apim_cidr_v = deployAIGatewayNetworking? replace(ai_gateway_apim_cidr,'XX',cidr_range): ''
var ai_gateway_app_cidr_v = deployAIGatewayNetworking? replace(ai_gateway_app_cidr,'XX',cidr_range):''

var commonResourceGroupName = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // esml-common-weu-dev-002 // esml-common-weu-dev-002 // DEPENDENCIES - should exist

var vnetResourceGroupName = vnetResourceGroup_param != '' ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroupName
var vnetNameFull = vnetNameFull_param  != '' ?vnetNameFull_param: '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'  // vnt-esmlcmn-weu-dev-001 @

var vNetRGsalt = substring(uniqueString(vnetResourceGroup.id), 0, 5)
var commmonRGsalt = substring(uniqueString(commonResourceGroupName), 0, 5)
var uniqueDetermenistic = '${commmonRGsalt}${vNetRGsalt}'

resource vnetResourceGroup 'Microsoft.Resources/resourceGroups@2020-10-01' existing = {
  name: vnetResourceGroupName
  scope:subscription(subscriptionIdDevTestProd)
}

module nsgCommon '../modules-common/nsgCommon.bicep' = {
  name: 'nsg-${common_subnet_name}-depl${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${common_subnet_name}'
    tags: tags
    location:location
    bastionIpRange: common_bastion_subnet_cidr_v
  }
}

module nsgCommonScoring '../modules-common/nsgCommonScoring.bicep' = {
  name: 'nsg-${common_subnet_name}-scoring-depl${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${common_subnet_name}-scoring'
    tags: tags
    location:location
    bastionIpRange: common_bastion_subnet_cidr_v
  }
  dependsOn:[
    nsgCommon
  ]
}

var ipWhitelist_array_1 = array(split(replace(IPwhiteList, '\\s+', ''), ','))
var ipWhitelist_array = (empty(IPwhiteList) || IPwhiteList == 'null' || length(IPwhiteList) < 5) ? [] : union(ipWhitelist_array_1,[]) // remove dups

module nsgBastion '../modules-common/nsgBastion.bicep' = if(empty(ipWhitelist_array)==false){
  name: 'nsg-${common_bastion_subnet_name}-depl${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${common_bastion_subnet_name}'
    tags: tags
    location:location
    IPwhiteList_Array: ipWhitelist_array
  }
  dependsOn:[
    nsgCommonScoring
  ]
}
module nsgBastionNoWhitelist '../modules-common/nsgBastionNoWhitelist.bicep' = if(empty(ipWhitelist_array)){
  name: 'nsg-${common_bastion_subnet_name}-NoWLdepl${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: 'nsg-${common_bastion_subnet_name}'
    tags: tags
    location:location
    IPwhiteList_Array: ipWhitelist_array
  }
  dependsOn:[
    nsgCommonScoring
  ]
}

module nsgPBI  '../modules-common/nsgPowerBI.bicep'= {
  scope: vnetResourceGroup
  name: 'nsg-${common_pbi_subnet_name}-depl${uniqueDetermenistic}'
  params: {
    name: 'nsg-${common_pbi_subnet_name}'
    tags: tags
    location:location
  }
  dependsOn:[
    nsgBastion
  ]
}
module vNetCommon '../modules-common/vNetCommon.bicep' = {
  scope: vnetResourceGroup
  name: '${vnetNameFull}depl${uniqueDetermenistic}'
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
    deployOnlyAIGatewayNetworking:deployOnlyAIGatewayNetworking
  }
  dependsOn: [
    nsgCommon
    nsgBastion
    nsgPBI
    nsgCommonScoring
  ]
}

//var aiGwNetworkingName = 'ai-gateway-${locationSuffix}-${env}-${commonResourceSuffix}'
var aiGwNetworkingName = 'ai-gateway'
module aiGatewayNetworking '../ai-gateway/14-add-networking-aigw.bicep' = if(deployAIGatewayNetworking){
  name: 'ai-gateway-networking-${uniqueDetermenistic}'
  scope: vnetResourceGroup
  params: {
    name: aiGwNetworkingName
    location: location
    tags: tags
    aifactorySuffixRG: aifactorySuffixRG
    commonResourceSuffix: commonResourceSuffix
    commonRGNamePrefix: commonRGNamePrefix
    env: env
    locationSuffix: locationSuffix
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    vnetName: vnetNameFull
    vnetNameBase: vnetNameBase
    network_env: network_env
    vnetNameFull_param: vnetNameFull_param
    vnetResourceGroup_param: vnetResourceGroup_param
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
    CIDRApim: ai_gateway_apim_cidr_v
    CIDRFunctionApp: ai_gateway_app_cidr_v  
  }
  dependsOn:[
    vNetCommon
  ]
}


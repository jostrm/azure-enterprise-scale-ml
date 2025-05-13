@description('Deployment location')
param location string
@description('tags')
param tags object
@description('Specifies the name of the NSG, network security group')
param vnetNameFull string
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
@description('CIDR for common scoring subnet')
param common_subnet_scoring_cidr string
@description('common Bastion host subnet for RDP access over private IP')
param common_bastion_subnet_name string
@description('common Bastion host subnet CIDR')
param common_bastion_subnet_cidr string
@description('ESML can run standalone/demo mode, this is deafault mode, meaning default FALSE value, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can change this, to use your HUB DnzZones instead.')
param centralDnsZoneByPolicyInHub bool = false
param deployOnlyAIGatewayNetworking bool = false

resource nsgCommon 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = {
  name: 'nsg-${common_subnet_name}'
}
resource nsgBastion 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = if(!deployOnlyAIGatewayNetworking) {
  name: 'nsg-${common_bastion_subnet_name}'
}

resource nsgPBI 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = if(!deployOnlyAIGatewayNetworking) {
  name: 'nsg-${common_pbi_subnet_name}'
}

resource nsgCommonScoring 'Microsoft.Network/networkSecurityGroups@2020-06-01' existing = if(!deployOnlyAIGatewayNetworking) {
  name: 'nsg-${common_subnet_name}-scoring'
}

var pbiSettings = {
  cidr: common_pbi_subnet_cidr
  delegations: [
    'Microsoft.PowerPlatform/vnetaccesslinks'
  ]
  serviceEndpoints: []
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2021-03-01' = {
  name: vnetNameFull
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        common_vnet_cidr
      ]
    }
    
    subnets: [
      {
        name: common_subnet_name
        properties: {
          addressPrefix: common_subnet_cidr
          serviceEndpoints: [ // Note: If only used to TRAIN models, We can have a separate SCORING subnet, with ServiceEndpoints
            {
              locations: [
                location
              ]
              service: 'Microsoft.KeyVault'
            }
            {
              service: 'Microsoft.Storage' // Needed, IF (pend) we want to add subnet to DATALAKE (firewall), added as a "virtualNetworkRules"
            }
          ]
          networkSecurityGroup: nsgCommon.id == '' ? null : {
            id: nsgCommon.id
          }   
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
        }
      }
      !deployOnlyAIGatewayNetworking? { 
        name: '${common_subnet_name}-scoring' // Note: Here we need ServiceEndpoints (KV, Storage. Optional: ContainerRegistry)
        properties: {
          addressPrefix: common_subnet_scoring_cidr
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
          serviceEndpoints: [
            {
              service: 'Microsoft.KeyVault' // Needed: KV och Storage for (AKS och Batch scoring, AKS gets own subnet and needs keyvault
            }
            {
              service: 'Microsoft.ContainerRegistry' // Optional
            }
            {
              service: 'Microsoft.Storage'
            }
          ]
          networkSecurityGroup: nsgCommonScoring.id == '' ? null : {
            id: nsgCommonScoring.id
          }  
        }
      }: {}
      !deployOnlyAIGatewayNetworking? {
        name: common_pbi_subnet_name
        properties: {
          addressPrefix: common_pbi_subnet_cidr
          serviceEndpoints: []
          delegations: [
            {
              properties: {
                serviceName: pbiSettings.delegations[0]
              }
              name: '${toLower(split(split(pbiSettings.delegations[0], '.')[0], '/')[0])}-del-${substring(uniqueString(common_pbi_subnet_name),0,12)}'
            }
          ]
          networkSecurityGroup: nsgPBI.id == '' ? null : {
            id: nsgPBI.id
          }
        }
      }:{}
      !deployOnlyAIGatewayNetworking? {
        name: common_bastion_subnet_name
        properties: {
          addressPrefix: common_bastion_subnet_cidr
          serviceEndpoints: []
          delegations: []
          networkSecurityGroup: nsgBastion.id == '' ? null : {
            id: nsgBastion.id
          }
        }
      }:{}
    ]

  }
  resource subnet1 'subnets' existing = {
    name: common_subnet_name
  }
  resource subnet2 'subnets' existing = if (!deployOnlyAIGatewayNetworking){
    name: common_pbi_subnet_name
  }
  resource subnet3 'subnets' existing = if(!deployOnlyAIGatewayNetworking){
    name: common_bastion_subnet_name
  }
}
output subnet1ResourceId string = virtualNetwork::subnet1.id
output subnet2ResourceId string = !deployOnlyAIGatewayNetworking? virtualNetwork::subnet2.id: ''
output subnetBastionId string = !deployOnlyAIGatewayNetworking? virtualNetwork::subnet3.id: ''

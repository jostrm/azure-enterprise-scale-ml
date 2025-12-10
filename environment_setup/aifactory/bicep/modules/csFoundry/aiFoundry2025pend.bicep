metadata name = 'AI Foundry Private Endpoints'
metadata description = 'This module deploys private endpoints for AI Foundry Cognitive Services.'

@description('Required. The name of the Cognitive Services account to create private endpoints for.')
param cognitiveServiceName string

@description('Required. The resource ID of the Cognitive Services account.')
param cognitiveServiceId string

@description('Required. Location for all Resources.')
param location string

@description('Optional. Tags of the resource.')
param tags object

// AI Factory private endpoint information
@description('Required. Private DNS zones configuration.')
param privateLinksDnsZones object

@description('Required. The resource ID of the subnet for private endpoints.')
param privateEndpointSubnetRID string

@description('Optional. Whether to create private endpoints the AI Factory way.')
param createPrivateEndpointsAIFactoryWay bool = true

@description('Optional. Whether central DNS zone is managed by policy in hub.')
param centralDnsZoneByPolicyInHub bool = false
@description('Existing API Management resource ID (for optional private endpoint).')
param apiManagementResourceId string = ''

var apiManagementProvided = !empty(apiManagementResourceId)
var apiManagementParts = apiManagementProvided ? split(apiManagementResourceId, '/') : split('', '/')
var apiManagementName = apiManagementProvided ? last(apiManagementParts) : ''

resource pendCogServiceAIF 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpointsAIFactoryWay) {
  name: '${cognitiveServiceName}-pend' //'${privateEndpointName}-2'
  location: location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${cognitiveServiceName}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${cognitiveServiceName}-pend'
        properties: {
          groupIds: [
            'account'
          ]
          privateLinkServiceId: cognitiveServiceId
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnetRID
    }
  }
}

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && createPrivateEndpointsAIFactoryWay) {
  name: '${pendCogServiceAIF.name}DnsZone'
  parent: pendCogServiceAIF
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateLinksDnsZones.openai.name
        properties:{
          privateDnsZoneId: privateLinksDnsZones.openai.id //openai
        }
      }
      {
        name: privateLinksDnsZones.cognitiveservices.name
        properties:{
          privateDnsZoneId: privateLinksDnsZones.cognitiveservices.id//cognitiveservices
        }
      }
      {
        name: privateLinksDnsZones.servicesai.name
        properties:{
          privateDnsZoneId: privateLinksDnsZones.servicesai.id
        }
      }
    ]
  }
}

resource privateEndpointApiManagement 'Microsoft.Network/privateEndpoints@2024-05-01' = if (apiManagementProvided) {
  name: '${take(apiManagementName, 40)}-pend'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetRID
    }
    privateLinkServiceConnections: [
      {
        name: '${take(apiManagementName, 40)}-pend-nic'
        properties: {
          privateLinkServiceId: apiManagementResourceId
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
          groupIds: [
            'Gateway'
          ]
        }

      }
    ]
  }
  dependsOn: [
    pendCogServiceAIF
  ]
}
resource privateEndpointDnsAPIM 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && createPrivateEndpointsAIFactoryWay) {
  name: '${privateEndpointApiManagement.name}DnsZone'
  parent: privateEndpointApiManagement
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateLinksDnsZones.apim.name
        properties:{
          privateDnsZoneId: privateLinksDnsZones.apim.id
        }
      }
    ]
  }
}
@description('The name of the private endpoint.')
output privateEndpointName string = createPrivateEndpointsAIFactoryWay ? pendCogServiceAIF.name : ''

@description('The resource ID of the private endpoint.')
output privateEndpointId string = createPrivateEndpointsAIFactoryWay ? pendCogServiceAIF.id : ''

@description('The resource ID of the private DNS zone group.')
output privateDnsZoneGroupId string = (!centralDnsZoneByPolicyInHub && createPrivateEndpointsAIFactoryWay) ? privateEndpointDns.id : ''

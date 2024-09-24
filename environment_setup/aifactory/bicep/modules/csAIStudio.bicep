@description('Specifies the name of the service')
param cognitiveName string
@description('Specifies the tags that will be associated with resources')
param tags object
@description('Specifies the location that will be used')
param location string
@description('Specifies the SKU, where default is standard')
param sku string
@description('Specifies the VNET id that will be associated with the private endpoint')
param vnetId string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
@description('ResourceID of subnet for private endpoints')
param subnetId string
@description('Restore instead of Purge')
param restore bool
param privateLinksDnsZones object
param centralDnsZoneByPolicyInHub bool = true
param kind  string = 'AIServices'
param publicNetworkAccess bool = false
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param disableLocalAuth bool = false
var subnetRef = '${vnetId}/subnets/${subnetName}'

var nameCleaned = toLower(replace(cognitiveName, '-', ''))
resource cognitive 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: nameCleaned
  location: location
  kind: kind
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    customSubDomainName: nameCleaned
    publicNetworkAccess: publicNetworkAccess? 'Enabled': 'Disabled'
    restore: restore
    restrictOutboundNetworkAccess: publicNetworkAccess? false:true
    disableLocalAuth: disableLocalAuth
    apiProperties: {
      statisticsEnabled: false
    }
    networkAcls: {
      defaultAction: publicNetworkAccess? 'Allow':'Deny'
      virtualNetworkRules: [for rule in vnetRules: {
        id: rule
        ignoreMissingVnetServiceEndpoint: false
      }]
      ipRules: ipRules
    }
  }
  identity: {
    type: 'SystemAssigned'
  }
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  properties: {
    subnet: {
      id: subnetRef
    }
    customNetworkInterfaceName: 'pend-nic-${kind}-${nameCleaned}'
    privateLinkServiceConnections: [
      {
        name: pendCogSerName
        properties: {
          privateLinkServiceId: cognitive.id
          groupIds: [
            'account'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Compliance with network design'
          }
        }
      }
    ]
  }
}

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-06-01' = if (centralDnsZoneByPolicyInHub == false) {
  name: '${pendCognitiveServices.name}/${pendCognitiveServices.name}DnsZone'
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
    ]
  }
}

/*
output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'openai'
    id:cognitive.id
    groupid:'account'
  }
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:cognitive.id
    groupid:'account'
  }
]
*/

output aiServicesId string = cognitive.id
output aiServicesEndpoint string = cognitive.properties.endpoint
output openAiId string = cognitive.id
output aiServicesPrincipalId string = cognitive.identity.principalId
output name string = cognitive.name
output resourceId string = cognitive.id

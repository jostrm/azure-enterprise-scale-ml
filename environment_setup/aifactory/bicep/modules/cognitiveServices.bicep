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
param kind  string
param deployments array = []
param publicNetworkAccess bool = false
param pendCogSerName string
var subnetRef = '${vnetId}/subnets/${subnetName}'

resource cognitive 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: cognitiveName
  location: location
  kind: kind
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    customSubDomainName: toLower(cognitiveName)
    publicNetworkAccess: publicNetworkAccess? 'enabled': 'disabled'
    networkAcls: {
      defaultAction: publicNetworkAccess? 'Allow':'Deny'
      virtualNetworkRules: json('[{"id": "${subnetRef}"}]')
      ipRules: json('[]')
    }
  }
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  properties: {
    subnet: {
      id: subnetRef
    }
    customNetworkInterfaceName: 'pend-nic-${kind}'
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

@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = [for deployment in deployments: {
  parent: cognitive
  name: deployment.name
  properties: {
    model: deployment.model
    raiPolicyName: deployment.?raiPolicyName ?? null
  }
  sku: contains(deployment, 'sku') ? deployment.sku : {
    name: 'Standard'
    capacity: 20
  }
}]

output cognitiveName string = cognitive.name
output cognitiveId string = cognitive.id
output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'account'
    id:cognitive.id
  }
]

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
param kind  string
param deployments array = []
param publicNetworkAccess bool = false
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param restore bool

var subnetRef = '${vnetId}/subnets/${subnetName}'
var nameCleaned = toLower(replace(cognitiveName, '-', ''))

resource cognitive 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: cognitiveName
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
    networkAcls: {
      defaultAction: publicNetworkAccess? 'Allow':'Deny'
      virtualNetworkRules: [for rule in vnetRules: {
        id: rule
        ignoreMissingVnetServiceEndpoint: false
      }]
      ipRules: ipRules
    }
  }
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    customNetworkInterfaceName: 'pend-nic-${kind}-${cognitiveName}'
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

/*
@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = [for deployment in deployments: {
  parent: cognitive
  name: deployment.name
  
  properties: {
    model: deployment.model
    //raiPolicyName: deployment.?raiPolicyName ?? 'Microsoft.Default'
    raiPolicyName:'Microsoft.Default'
    //versionUpgradeOption: deployment.?versionUpgradeOption ??'OnceCurrentVersionExpired'
    versionUpgradeOption:'OnceCurrentVersionExpired'
    scaleSettings: {
      capacity: deployment.scaleType.capacity
      scaleType:deployment.scaleType.scaleType
    }
  }
  sku: {
    name: deployment.sku
    //capacity: deployment.capacity
    //tier: deployment.tier
  }
}]

*/

output cognitiveId string = cognitive.id
output azureOpenAIEndpoint string = cognitive.properties.endpoint
output cognitiveName string = cognitive.name
output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:cognitive.id
    groupid:'account'
  }
]

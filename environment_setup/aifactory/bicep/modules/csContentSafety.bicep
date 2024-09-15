@description('ResourceID of subnet for private endpoints')
param subnetId string
param csSKU string = 'S0'
param location string
param contentsafetyName string
param kind string = 'ContentSafety'
param publicNetworkAccess bool = true
param vnetRules array = []
param ipRules array = []
param pendCogSerName string
param vnetId string
param subnetName string
param restore bool

var subnetRef = '${vnetId}/subnets/${subnetName}'
var nameCleaned = toLower(replace(contentsafetyName, '-', ''))

resource contentSafetyAccount 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: contentsafetyName
  location: location
  kind: kind
  sku: {
    name: csSKU
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
  properties: {
    subnet: {
      id: subnetId
    }
    customNetworkInterfaceName: 'pend-nic-${kind}-${contentsafetyName}'
    privateLinkServiceConnections: [
      {
        name: pendCogSerName
        properties: {
          privateLinkServiceId: contentSafetyAccount.id
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

output name string = contentSafetyAccount.name
output resourceId string = contentSafetyAccount.id
output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:contentSafetyAccount.id
    groupid:'account'
  }
]

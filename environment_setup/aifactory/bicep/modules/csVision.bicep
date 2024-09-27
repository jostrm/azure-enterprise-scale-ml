param csSKU string = 'S0'
param location string
param name string
param kind string = 'ComputerVision'
param publicNetworkAccess bool = true
param vnetRules array = []
param ipRules array = []
param pendCogSerName string
param vnetId string
param subnetName string
param restore bool

var subnetRef = '${vnetId}/subnets/${subnetName}'
var nameCleaned = toLower(replace(name, '-', ''))

resource visionAccount 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: name
  location: location
  kind: kind
  identity: {
    type: 'SystemAssigned'
  }
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
      id: subnetRef
    }
    customNetworkInterfaceName: 'pend-nic-${kind}-${nameCleaned}'
    privateLinkServiceConnections: [
      {
        name: pendCogSerName
        properties: {
          privateLinkServiceId: visionAccount.id
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

output name string = visionAccount.name
output resourceId string = visionAccount.id
output principalId string = visionAccount.identity.principalId // Error, "The template output 'principalId' is not valid: The language expression property 'identity' doesn't exist,

output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:visionAccount.id
    groupid:'account'
  }
]

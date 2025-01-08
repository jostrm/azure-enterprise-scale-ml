param csSKU string = 'S0'
param location string
param name string
param kind string = 'ComputerVision'
param publicNetworkAccess bool = true
param vnetRules array = []
param ipRules array = []
param pendCogSerName string
param vnetName string
param subnetName string
param restore bool
param keyvaultName string
param vnetResourceGroupName string

var nameCleaned = toLower(replace(name, '-', ''))

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

resource visionAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
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
    apiProperties: {
      responsibleAiNotice: 'Acknowledged'
    }
    networkAcls: {
      bypass:'AzureServices'
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
      id: subnet.id
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
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

// listKeys(visionAccount.id, '2022-11-01').keys[0].value
// storageAccount.listKeys().keys[0].value
// visionAccount.listKeys().key1
//listKeys(visionAccount.id, '2024-10-01').key1

resource keyVault4Vision 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault: Computer Vision K in vault as S')
resource kValueVision 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault4Vision
  name: 'aifactory-proj-vision-api-key'
  properties: {
    value:visionAccount.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
@description('Key Vault: Computer Vision Endpoint in vault as S')
resource kValueVisionEP 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault4Vision
  name: 'aifactory-proj-vision-api-endpoint'
  properties: {
    value:visionAccount.properties.endpoint
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

output name string = visionAccount.name
output resourceId string = visionAccount.id
output principalId string = visionAccount.identity.principalId // Error, "The template output 'principalId' is not valid: The language expression property 'identity' doesn't exist,
output computerVisionEndpoint string = visionAccount.properties.endpoint

output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:visionAccount.id
    groupid:'account'
  }
]

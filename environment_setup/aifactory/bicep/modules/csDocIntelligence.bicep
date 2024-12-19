param csSKU string = 'S0'
param location string
param name string
param kind string = 'FormRecognizer'
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

resource csAccountDocInt 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
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
      //bypass:'AzureServices'
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
          privateLinkServiceId: csAccountDocInt.id
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
resource keyVaultDocInt 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault: Azur AI Document Intelligence K in vault as S')
resource kValueDocInt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultDocInt
  name: 'aifactory-proj-aidocintelligence-api-key'
  properties: {
    value:csAccountDocInt.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
@description('Key Vault: Azure AI Document Intelligence Endpoint in vault as S')
resource kValueDocInt2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultDocInt
  name: 'aifactory-proj-aidocintelligence-api-endpoint'
  properties: {
    value:csAccountDocInt.properties.endpoint
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}


output name string = csAccountDocInt.name
output resourceId string = csAccountDocInt.id
output principalId string = csAccountDocInt.identity.principalId 
output endpoint string = csAccountDocInt.properties.endpoint
output host string = split(csAccountDocInt.properties.endpoint, '/')[2]

output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:csAccountDocInt.id
    groupid:'account'
  }
]

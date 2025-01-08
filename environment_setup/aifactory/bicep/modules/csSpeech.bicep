param csSKU string = 'S0'
param location string
param name string
param kind string = 'SpeechServices'
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
resource csAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
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

resource pendCognitiveServicesSpeech 'Microsoft.Network/privateEndpoints@2023-04-01' = {
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
          privateLinkServiceId: csAccount.id
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

resource keyVault4Speech 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault: Speech k in vault')
resource kValueSpeech 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault4Speech
  name: 'aifactory-proj-speech-api-key'
  properties: {
    value:csAccount.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
@description('Key Vault: Speech Endpoint in vault')
resource kValueSpeechEP 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault4Speech
  name: 'aifactory-proj-speech-api-ednpoint'
  properties: {
    value:csAccount.properties.endpoint
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}


output name string = csAccount.name
output resourceId string = csAccount.id
output principalId string = csAccount.identity.principalId

output dnsConfig array = [
  {
    name: pendCognitiveServicesSpeech.name
    type: 'cognitiveservices'
    id:csAccount.id
    groupid:'account'
  }
]

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
param enablePublicAccessWithPerimeter bool = false
param disableLocalAuth bool = false

var nameCleaned = toLower(replace(name, '-', ''))
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
var rules = [for rule in vnetRules: {
  id: rule
  ignoreMissingVnetServiceEndpoint: true
}]

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
    publicNetworkAccess: publicNetworkAccess || enablePublicAccessWithPerimeter? 'Enabled': 'Disabled'
    restore: restore
    restrictOutboundNetworkAccess: publicNetworkAccess? false:true
    disableLocalAuth: disableLocalAuth
    networkAcls: !enablePublicAccessWithPerimeter ? {
      //bypass:'AzureServices'
      defaultAction: 'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      virtualNetworkRules: rules
      ipRules: ipRules
    }: null
  }
  
}

resource pendCognitiveServicesSpeech 'Microsoft.Network/privateEndpoints@2023-04-01' = if(!enablePublicAccessWithPerimeter){
  location: location
  name: '${nameCleaned}-pend'
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${nameCleaned}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${nameCleaned}-pend'
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

// API key secret: use a nested module so ARM never evaluates listKeys() when
// disableLocalAuth=true. Conditional resources do NOT prevent ARM from evaluating
// list* expressions in the resource body - only a conditional module does.
module speechKvKey './csSpeech-kvSecret.bicep' = if(!disableLocalAuth) {
  name: take('speech-kv-key-${name}', 64)
  params: {
    speechAccountName: csAccount.name
    keyvaultName: keyvaultName
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
    name: !enablePublicAccessWithPerimeter? pendCognitiveServicesSpeech.name: ''
    type: 'cognitiveservices'
    id:csAccount.id
    groupid:'account'
  }
]

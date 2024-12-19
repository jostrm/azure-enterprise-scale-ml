@description('Specifies the name of the service')
param cognitiveName string
@description('Specifies the tags that will be associated with resources')
param tags object
@description('Specifies the location that will be used')
param location string
@description('Specifies the SKU, where default is standard')
param sku string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
@description('Name of vNet')
param vnetName string
@description('Restore instead of Purge')
param restore bool
param privateLinksDnsZones object
param centralDnsZoneByPolicyInHub bool = true
param kind string = 'AIServices'
param publicNetworkAccess bool = false
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param disableLocalAuth bool = false
param vnetResourceGroupName string
param keyvaultName string
@allowed([
  '1106-preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
param modelGPT4Version string = '1106-preview' // If your region doesn't support this version, please change it.

var nameCleaned = toLower(replace(cognitiveName, '-', ''))
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
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
      bypass:'AzureServices'
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

resource gpt4modelOpenAI 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'gpt-4'
  parent: aiServices
  sku: {
    name: 'Standard'
    capacity: 25
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4'
      version:modelGPT4Version 
    }
    raiPolicyName: 'Microsoft.Default'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable' // 'NoAutoUpgrade'
  }

}

resource embedding2 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'text-embedding-ada-002'
  parent: aiServices
  sku: {
    name: 'Standard'
    capacity: 25
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-ada-002'
      version:'2'
    }
    raiPolicyName: 'Microsoft.Default'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    gpt4modelOpenAI
  ]
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
          privateLinkServiceId: aiServices.id
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
  name: '${pendCognitiveServices.name}DnsZone'
  parent: pendCognitiveServices
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
resource keyVaultOpenAI 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault: Azure AI Services K in vault as S')
resource kValueAIServices 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultOpenAI
  name: 'aifactory-proj-aiservices-api-key'
  properties: {
    value: aiServices.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
@description('Key Vault: Azure AI Services endpoint in vault as S')
resource epValueAIServices 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultOpenAI
  name: 'aifactory-proj-aiservices-ep'
  properties: {
    value: aiServices.properties.endpoint
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
@description('Key Vault: Azure OpenAI endpoint in vault as S. Same key as Azure AI Services')
resource epValueOpenAI 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultOpenAI
  name: 'aifactory-proj-openai-ep'
  properties: {
    value: aiServices.properties.endpoints['OpenAI Language Model Instance API']
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

output aiServicesEndpoint string = aiServices.properties.endpoint
output endpoints object = aiServices.properties.endpoints
output openAIEndpoint string = aiServices.properties.endpoints['OpenAI Language Model Instance API']

output aiServicesPrincipalId string = aiServices.identity.principalId
output name string = aiServices.name
output resourceId string = aiServices.id

//output aiServicesId string = aiServices.id
//output openAiId string = aiServices.id

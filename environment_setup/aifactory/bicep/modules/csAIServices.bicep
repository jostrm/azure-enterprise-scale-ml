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
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param disableLocalAuth bool = true
param vnetResourceGroupName string
param acrNameDummy string = ''
param keyvaultName string
param publicNetworkAccess bool = false
param enablePublicAccessWithPerimeter bool = false
/*
@allowed([
  '1106-Preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
*/

param modelGPT4Version string // If your region doesn't support this version, please change it.

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
    publicNetworkAccess: (enablePublicAccessWithPerimeter ||publicNetworkAccess) ? 'Enabled':'Disabled' //03-02: Change to Enabled // If not Deny/Disabled, then ipRules will be ignored (cannot be changed later either) publicNetworkAccess? 'Enabled': 'Disabled' 
    restore: restore
    restrictOutboundNetworkAccess: false // publicNetworkAccess? false:true
    disableLocalAuth: disableLocalAuth
    apiProperties: {
      statisticsEnabled: false
    }
    networkAcls: {
      bypass:'AzureServices'
      defaultAction: enablePublicAccessWithPerimeter? 'Allow':'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      virtualNetworkRules: [for rule in vnetRules: {
        id: rule
        ignoreMissingVnetServiceEndpoint: true
      }]
      ipRules: ipRules
    }
  }
  identity: {
    type: 'SystemAssigned'
  }
}

/*
resource gpt4modelOpenAI 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if (!empty(modelGPT4Version)) {
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
  dependsOn: [
    aiServices
  ]
}

*/

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
    aiServices
  ]
}

// aiservicesprj003sdcdev3pmpb002 in state Accepted (Code: AccountProvisioningStateInvalid)
resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${pendCogSerName}-nic'
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
            description: 'Auto-Approved'
            actionsRequired: 'None'
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

@description('Specifies the name of the service')
param cognitiveName string
@description('Specifies the tags that will be associated with resources')
param tags object
@description('Specifies the location that will be used')
param location string
@description('Specifies the SKU, where default is standard')
param sku string
@description('Specifies the VNET id that will be associated with the private endpoint')
param vnetName string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param kind string
param publicNetworkAccess bool = false
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param restore bool
param vnetResourceGroupName string

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
  name: cognitiveName
  location: location
  kind: kind
  identity: {
    type: 'SystemAssigned'
  }
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

resource gpt4services 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
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
      version:'turbo-2024-04-09' // If your region doesn't support this version, please change it.
    }
    raiPolicyName: 'Microsoft.Default'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource embedding2services 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
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
    gpt4services
  ]
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: 'pend-nic-${kind}-${cognitiveName}'
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
  dependsOn: [
    embedding2services
  ]
}

output cognitiveId string = aiServices.id
output azureOpenAIEndpoint string = aiServices.properties.endpoint
output cognitiveName string = aiServices.name
//output principalId string = cognitive.identity.principalId // Is this used? 

output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:aiServices.id
    groupid:'account'
  }
]

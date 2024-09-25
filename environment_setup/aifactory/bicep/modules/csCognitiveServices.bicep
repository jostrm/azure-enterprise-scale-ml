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

resource gpt4turbo 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: '${cognitiveName}/gpt-4'
  //parent: cognitive
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
  dependsOn: [
    cognitive
  ]
}

resource embedding2 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'text-embedding-ada-002'
  parent: cognitive
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
    gpt4turbo
  ]
}

/* DeploymentModelNotSupported - The model 'Format: OpenAI, Name: text-embedding-3-large, Version: ' of account deployment is not supported.*/

resource embedding3 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'text-embedding-3-large'
  parent: cognitive
  sku: {
    name: 'Standard'
    capacity: 25
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version:'1' 
      //name: 'text-embedding-ada-002'
      //version:'2'
    }
    raiPolicyName: 'Microsoft.Default'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    embedding2
  ]
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: pendCogSerName
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
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
  dependsOn: [
    embedding3
  ]
}

output cognitiveId string = cognitive.id
output azureOpenAIEndpoint string = cognitive.properties.endpoint
output cognitiveName string = cognitive.name
//output principalId string = cognitive.identity.principalId // Is this used? 

output dnsConfig array = [
  {
    name: pendCognitiveServices.name
    type: 'cognitiveservices'
    id:cognitive.id
    groupid:'account'
  }
]

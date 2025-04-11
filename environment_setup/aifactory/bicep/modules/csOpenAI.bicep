@description('Specifies the name of the service')
param cognitiveName string
@description('Specifies the tags that will be associated with resources')
param tags object
@description('Specifies the location that will be used')
param location string
@description('Specifies the SKU, where default is standard')
param sku string = 'S0'
@description('Specifies the VNET name that will be associated with the private endpoint')
param vnetName string
@description('Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param kind string = 'OpenAI'
param publicNetworkAccess bool = false
param pendCogSerName string
param vnetRules array = []
param ipRules array = []
param restore bool=false
param disableLocalAuth bool = true
/*
@allowed([
  '1106-Preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
*/

param modelGPT4Version string = '1106-Preview' // If your region doesn't support this version, please change it.
param laWorkspaceName string
param keyvaultName string
param vnetResourceGroupName string
param commonResourceGroupName string
param aiSearchPrincipalId string

var nameCleaned = toLower(replace(cognitiveName, '-', ''))

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: laWorkspaceName
  scope: resourceGroup(commonResourceGroupName)
}

//var subnetRef = '${vnetId}/subnets/${subnetName}'
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

//var subnetRef = subnet.id

// TODO: in ADO pipeline: https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks?tabs=portal#grant-access-to-trusted-azure-services-for-azure-openai
resource cognitiveOpenAI 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: cognitiveName
  location: location
  kind: kind
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: sku
  }
  properties: {
    allowedFqdnList: []
    customSubDomainName: nameCleaned
    publicNetworkAccess: publicNetworkAccess? 'Enabled': 'Disabled'
    restore: restore
    restrictOutboundNetworkAccess: publicNetworkAccess? false:true
    disableLocalAuth: disableLocalAuth
    networkAcls: {
      bypass:'AzureServices'
      defaultAction: 'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      virtualNetworkRules: [for rule in vnetRules: {
        id: rule
        ignoreMissingVnetServiceEndpoint: true
      }]
      ipRules: ipRules
    }
  }
}

/*
resource gpt4modelOpenAI 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'gpt-4'
  parent: cognitiveOpenAI
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
*/

resource embedding2 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  name: 'text-embedding-ada-002'
  parent: cognitiveOpenAI
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
    cognitiveOpenAI
  ]
}

resource openAIDiagSettingsOpenAI 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'default'
  scope: cognitiveOpenAI
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
    logAnalyticsDestinationType: null
  }
}

resource pendCognitiveServicesOpenAI 'Microsoft.Network/privateEndpoints@2023-04-01' = {
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
          privateLinkServiceId: cognitiveOpenAI.id
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
    embedding2
  ]
}

/*
resource keyVaultOpenAI 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}
*/

// Failed to list key. disableLocalAuth is set to be true
/*
@description('Key Vault: Azure OpenAI K in vault as S')
resource kValueOpenAI 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultOpenAI
  name: 'aifactory-proj-azureopenai-api-key'
  properties: {
    value:cognitiveOpenAI.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

*/

// Search -> OpenAI
/*
var cognitiveServicesOpenAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
resource openAIAssignmentCognitiveServicesOpenAIContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cognitiveOpenAI.id, cognitiveServicesOpenAIContributorRoleId, aiSearchPrincipalId)  
  properties: {
    principalId: aiSearchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIContributorRoleId)
    description: '018'
  }
  scope: cognitiveOpenAI
}
  */

// Users -> OpenAI

output cognitiveId string = cognitiveOpenAI.id
output azureOpenAIEndpoint string = cognitiveOpenAI.properties.endpoint
output cognitiveName string = cognitiveOpenAI.name
output principalId string = cognitiveOpenAI.identity.principalId // SystemAssigned. Unable to evaluate template outputs: 'principalId'

output dnsConfig array = [
  {
    name: pendCognitiveServicesOpenAI.name
    type: 'openai'
    id:cognitiveOpenAI.id
    groupid:'account'
  }
]

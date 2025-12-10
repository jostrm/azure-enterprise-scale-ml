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
import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?

/*
@allowed([
  '1106-Preview'
  '0613'
  'vision-preview'
  'turbo-2024-04-0'
])
*/
param deployModel_text_embedding_ada_002 bool = false // text-embedding-ada-002
param deployModel_text_embedding_3_small bool = false // text-embedding-3-small
param deployModel_text_embedding_3_large bool = false // text-embedding-3-large
// GPT-4o-mini
param deployModel_gpt_4o_mini bool = false // gpt-4o-mini
param default_embedding_capacity int = 25
param default_gpt_capacity int = 40
param default_model_sku string = 'Standard'
// GPT X
param deployModel_gpt_X bool = false
param modelGPTXName string = ''
param modelGPTXVersion string = '1'// If your region doesn't support this version, please change it.
param modelGPTXSku string = 'Standard'
param modelGPTXCapacity int = 30

var nameCleaned = toLower(replace(cognitiveName, '-', ''))

var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var identity = !empty(managedIdentities)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'SystemAssigned, UserAssigned' : 'SystemAssigned')
        : (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'}


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
resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
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
    networkAcls: !enablePublicAccessWithPerimeter ? {
      bypass:'AzureServices'
      defaultAction: enablePublicAccessWithPerimeter? 'Allow':'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      virtualNetworkRules: rules
      ipRules: ipRules
    }:null
  }
  identity:identity
}

resource textEmbedding3Small 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if(deployModel_text_embedding_3_small) {
  name: 'text-embedding-3-small'
  parent: aiServices
  sku: {
    name: default_model_sku
    capacity: default_embedding_capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    aiServices
  ]
}
resource embedding2 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if(deployModel_text_embedding_ada_002) {
  name: 'text-embedding-ada-002'
  parent: aiServices
  sku: {
    name: default_model_sku
    capacity: default_embedding_capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-ada-002'
      version:'2'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    aiServices
    ...(deployModel_text_embedding_3_small ? [textEmbedding3Small] : [])
  ]
}
resource gpt4omini 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if(deployModel_gpt_4o_mini) {
  name: 'gpt-4o-mini'
  parent: aiServices
  sku: {
    name: default_model_sku
    capacity: default_gpt_capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    aiServices
    ...(deployModel_text_embedding_ada_002 ? [embedding2] : [])
    ...(deployModel_text_embedding_3_small ? [textEmbedding3Small] : [])
  ]
}
resource gptXmodelOpenAI 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if (deployModel_gpt_X && !empty(modelGPTXVersion) && !empty(modelGPTXName)) {
  name: modelGPTXName
  parent: aiServices
  sku: {
    name: modelGPTXSku
    capacity: modelGPTXCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelGPTXName
      version:modelGPTXVersion
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable' // 'NoAutoUpgrade'
  }
  dependsOn: [
    aiServices
    ...(deployModel_text_embedding_ada_002 ? [embedding2] : [])
    ...(deployModel_text_embedding_3_small ? [textEmbedding3Small] : [])
    ...(deployModel_gpt_4o_mini ? [gpt4omini] : [])
  ]
}

resource embedding3large 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if(deployModel_text_embedding_3_large) {
  name: 'text-embedding-3-large'
  parent: aiServices
  sku: {
    name: default_model_sku
    capacity: default_embedding_capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    aiServices
    ...(deployModel_text_embedding_ada_002 ? [embedding2] : [])
    ...(deployModel_text_embedding_3_small ? [textEmbedding3Small] : [])
    ...(deployModel_gpt_4o_mini ? [gpt4omini] : [])
    ...(deployModel_gpt_X ? [gptXmodelOpenAI] : [])
  ]
}

// aiservicesprj003sdcdev3pmpb002 in state Accepted (Code: AccountProvisioningStateInvalid)
resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = if (!enablePublicAccessWithPerimeter) {
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

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (centralDnsZoneByPolicyInHub == false && !enablePublicAccessWithPerimeter) {
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
      {
        name: privateLinksDnsZones.servicesai.name
        properties:{
          privateDnsZoneId: privateLinksDnsZones.servicesai.id // ai services
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

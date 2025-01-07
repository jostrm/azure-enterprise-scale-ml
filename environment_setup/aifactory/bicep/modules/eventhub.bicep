@description('Name for the Event Hub cluster.')
param namespaceName string

@description('Name for the Event Hub to be created in the Event Hub namespace within the Event Hub cluster.')
param eventHubName string = namespaceName

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

var subnetRef = '${vnetId}/subnets/${subnetName}'

@description('Specifies the tags that should be applied to machine learning studio resources')
param tags object

@description('Specifies the Azure location for all resources.')
param location string = resourceGroup().location

@description('')
param eHRuleName string = 'rule'

param keyvaultName string

resource namespaceNameEV 'Microsoft.EventHub/namespaces@2021-11-01' = {
  identity:{
    type:'SystemAssigned'
  }
  name: namespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    isAutoInflateEnabled: false
    maximumThroughputUnits: 0
  }
}

resource eventHub 'Microsoft.EventHub/namespaces/eventhubs@2021-11-01' = {
  parent: namespaceNameEV
  name: eventHubName
  properties: {
    messageRetentionInDays: 7
    partitionCount: 1
  }
}

resource namespaceName_rule 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2021-11-01' = {
  name: '${namespaceName}/${eventHubName}/${eHRuleName}'
  properties: {
    rights: [
      'Send'
      'Listen'
    ]
  }
  dependsOn: [
    eventHub
  ]
}

var keysObj = listKeys(resourceId('Microsoft.EventHub/namespaces/eventhubs/authorizationRules', namespaceName, eventHubName, eHRuleName), '2024-01-01')

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
  scope: resourceGroup()
}

@description('Key Vault Secret: Eventhubs ConnectionString')
resource managedEndpointPrimaryKeyEntry 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'aifactory-proj-eventhub-connectionstring'
  properties: {
    value:keysObj.primaryConnectionString
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource eventHubPend 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  location: location
  name: privateEndpointName
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: namespaceNameEV.id
          groupIds: [
            'namespace'
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


/*NS*/
output eHNamespaceId string = namespaceNameEV.id
output eHNnsName string = namespaceNameEV.name
output principalId string = namespaceNameEV.identity.principalId
/*EH*/
output eHubNameId string = eventHub.id

/*NS Rules*/
output eHAuthRulesId string = namespaceName_rule.id
/*Other*/
output eHName string = eventHubName

output dnsConfig array = [
  {
    name: eventHubPend.name
    type: 'namespace'
    id: namespaceNameEV.id
  }
]

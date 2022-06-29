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

resource namespaceName_resource 'Microsoft.EventHub/namespaces@2021-11-01' = {
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

resource namespaceName_eventHubName 'Microsoft.EventHub/namespaces/eventhubs@2021-11-01' = {
  parent: namespaceName_resource
  name: eventHubName
  properties: {
    messageRetentionInDays: 7
    partitionCount: 1
  }
  dependsOn: [
    namespaceName_resource
  ]
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
    namespaceName_eventHubName
  ]
}

var keysObj = listKeys(resourceId('Microsoft.EventHub/namespaces/eventhubs/authorizationRules', namespaceName, eventHubName, eHRuleName), '2021-01-01-preview')

/*NS*/
output eHNamespaceId string = namespaceName_resource.id
output eHNnsName string = namespaceName_resource.name
output principalId string = namespaceName_resource.identity.principalId
/*EH*/
output eHubNameId string = namespaceName_eventHubName.id

/*NS Rules*/
output eHAuthRulesId string = namespaceName_rule.id
/*Other*/
// output eHObjName object = keysObj
output eHPConnString string = keysObj.primaryConnectionString
output eHName string = eventHubName

resource eventHubPend 'Microsoft.Network/privateEndpoints@2020-07-01' = {
  name: eventHubName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    privateLinkServiceConnections: [
      {
        id: 'string'
        properties: {
          privateLinkServiceId: namespaceName_resource.id
          groupIds: [
            'namespace'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Private endpoint for Eventhub namespace'
          }
        }
        name: 'pend-evenhubns'
      }
    ]
  }
}

output dnsConfig array = [
  {
    name: eventHubPend.name
    type: 'namespace'
  }
]

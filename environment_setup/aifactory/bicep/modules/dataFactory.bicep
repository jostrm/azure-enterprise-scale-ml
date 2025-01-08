@description('Specifies the name of the Azure Data Factory')
param name string

@description('Location where datafacory should be deployed')
param location string

@description('Specifies a object with key value pairs added as tags to Data Factory resource')
param tags object

@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('Specifies name of the portal private endpoint')
param portalPrivateEndpointName string

@description('Specifies the name of the runtime service private endpoint')
param runtimePrivateEndpointName string

var subnetRef = '${vnetId}/subnets/${subnetName}'

var groupIds = [
  {
    name: portalPrivateEndpointName
    gid: 'portal'
  }
  {
    name: runtimePrivateEndpointName
    gid: 'dataFactory'
  }
]

resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    globalParameters: {}
  }
}

resource pendAdf 'Microsoft.Network/privateEndpoints@2020-07-01' = [for obj in groupIds: {
  name: obj.name
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
          privateLinkServiceId: adf.id
          groupIds: [
            obj.gid
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
        name: 'pend-adf-${obj.gid}'
      }
    ]
  }
}]

output adfId string = adf.id
output adfName string = adf.name
output principalId string = adf.identity.principalId

output dnsConfig array = [
  {
    name: pendAdf[0].name
    type: 'portal'
    id:adf.id
  }
  {
    name: pendAdf[1].name
    type: 'dataFactory'
    id:adf.id
  }
]

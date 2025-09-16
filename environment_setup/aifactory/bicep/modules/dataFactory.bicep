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

import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?
param enablePublicAccessWithPerimeter bool = false
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

var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var identity = !empty(managedIdentities)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'}


resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: name
  location: location
  tags: tags
  identity:identity
  properties: {
    globalParameters: {}
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled': 'Disabled'
  }
}

resource pendAdf 'Microsoft.Network/privateEndpoints@2023-04-01' = [for obj in groupIds: if(!enablePublicAccessWithPerimeter){
  name: '${name}-${obj.gid}-pend'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    customNetworkInterfaceName: '${name}-${obj.gid}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${name}-${obj.gid}-pend'
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
      }
    ]
  }
}]

output adfId string = adf.id
output adfName string = adf.name
output principalId string = adf.identity.principalId

output dnsConfig array = [
  {
    name: !enablePublicAccessWithPerimeter? pendAdf[0].name: ''
    type: 'portal'
    id:adf.id
    groupid:groupIds[0].gid
  }
  {
    name: !enablePublicAccessWithPerimeter? pendAdf[1].name: ''
    type: 'dataFactory'
    id:adf.id
    groupid:groupIds[1].gid
  }
]

param location string
param tags object
param name string

resource apimRouteTable 'Microsoft.Network/routeTables@2023-11-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': name })
  properties: {
    routes: [
      {
        name: 'apim-management'
        properties: {
          addressPrefix: 'ApiManagement'
          nextHopType: 'Internet'
        }
      }
      // Add additional routes as required
    ]
  }
}

output id string = apimRouteTable.id
output name string = apimRouteTable.name

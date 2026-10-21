targetScope = 'resourceGroup'

@minLength(1)
@description('Full approved new subnet ID. Caller must validate the subscription, resource group, parent VNet, and absence before deploying.')
param integrationSubnetId string

@minLength(1)
param integrationSubnetPrefix string

@minLength(1)
param networkSecurityGroupId string

@description('Empty deliberately means no route table association; otherwise an approved existing route table ID.')
param routeTableId string = ''

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: split(integrationSubnetId, '/')[8]
}

resource integrationSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: split(integrationSubnetId, '/')[10]
  properties: union({
    addressPrefix: integrationSubnetPrefix
    networkSecurityGroup: {
      id: networkSecurityGroupId
    }
    delegations: [
      {
        name: 'apim-v2-integration'
        properties: {
          serviceName: 'Microsoft.Web/serverFarms'
        }
      }
    ]
  }, empty(routeTableId) ? {} : {
    routeTable: {
      id: routeTableId
    }
  })
}

output subnetId string = integrationSubnet.id

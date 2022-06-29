targetScope = 'subscription'

param rgName string
param location string
param tags object
param managedBy string

resource rg1 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  //scope: resourceGroup('subGuid', commonResourceGroupName)
  name: rgName
  location: location
  tags: tags
  managedBy: managedBy
}
output rgId string = rg1.id

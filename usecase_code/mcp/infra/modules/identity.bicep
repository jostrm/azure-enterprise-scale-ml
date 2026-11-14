targetScope = 'resourceGroup'

@description('Name of the user-assigned managed identity.')
param identityName string

@description('Azure region for the identity.')
param location string

@description('Required AppOnboard and workload ownership tags.')
param tags object

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: tags
}

output resourceId string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId

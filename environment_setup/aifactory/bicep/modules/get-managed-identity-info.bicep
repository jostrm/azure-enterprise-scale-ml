// Helper module to get managed identity principal IDs
targetScope = 'resourceGroup'

@description('Managed Identity name')
param managedIdentityName string

// Reference existing managed identity (no conditional needed)
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: managedIdentityName
}

// Outputs - these will be available since the resource exists
@description('Principal ID of the managed identity')
output principalId string = managedIdentity.properties.principalId

@description('Client ID of the managed identity')
output clientId string = managedIdentity.properties.clientId

@description('Resource ID of the managed identity')
output resourceId string = managedIdentity.id

@description('Managed identity name')
output name string = managedIdentity.name

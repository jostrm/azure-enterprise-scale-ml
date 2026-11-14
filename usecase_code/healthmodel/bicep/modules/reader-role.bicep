// Grants the health model's system-assigned identity a read-only role on one resource group.
targetScope = 'resourceGroup'

@description('Object ID of the health model system-assigned identity.')
param principalId string

@description('Role definition GUID. Monitoring Reader by default: metrics, Resource Health and nested model state.')
param roleDefinitionId string = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

@description('Health model name, used in the role assignment description.')
param healthModelName string

resource readerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // The principal is part of the name, so a re-created model never collides with a stale assignment.
  name: guid(resourceGroup().id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    description: 'Azure Monitor health model ${healthModelName} reads metrics and Resource Health (read-only).'
  }
}

output roleAssignmentId string = readerAssignment.id

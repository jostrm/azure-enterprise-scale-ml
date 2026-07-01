// =============================================================================
// roleAssignment.resourcegroup.bicep
// Grants the throttle Logic App managed identity 'Cognitive Services Contributor'
// at resource-group scope (single AI Factory project RG).
// =============================================================================
targetScope = 'resourceGroup'

@description('Principal id (object id) of the Logic App managed identity.')
param principalId string

// Cognitive Services Contributor
var roleDefinitionId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'

resource ra 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
  }
}

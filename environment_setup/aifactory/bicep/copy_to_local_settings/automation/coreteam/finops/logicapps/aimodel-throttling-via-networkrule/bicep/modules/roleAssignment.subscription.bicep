// =============================================================================
// roleAssignment.subscription.bicep
// Grants the throttle Logic App managed identity 'Cognitive Services Contributor'
// at subscription scope so it can change network settings and reject/approve
// private endpoint connections on any Foundry/Cognitive Services account.
// =============================================================================
targetScope = 'subscription'

@description('Principal id (object id) of the Logic App managed identity.')
param principalId string

// Cognitive Services Contributor
var roleDefinitionId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'

resource ra 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
  }
}

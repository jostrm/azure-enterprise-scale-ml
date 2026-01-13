@description('AI Foundry account name to scope the role assignment')
param aiFoundryAccountName string

@description('Principal ID of the AI Search service managed identity')
param aiSearchPrincipalId string

@description('Role definition ID for Cognitive Services OpenAI User')
param openAIUserRoleId string = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
  name: aiFoundryAccountName
}

resource aiSearchOpenAIUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundryAccount.id, aiSearchPrincipalId, openAIUserRoleId)
  scope: aiFoundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUserRoleId)
    principalId: aiSearchPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentCreated bool = true

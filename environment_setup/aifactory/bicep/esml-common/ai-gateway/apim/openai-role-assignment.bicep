targetScope = 'resourceGroup'

@description('Azure OpenAI Cognitive Services account name in this resource group.')
param azureOpenAIResourceName string

@description('Object ID of APIM system-assigned managed identity.')
param apimManagedIdentityPrincipalId string

var openAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource azureOpenAI 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: azureOpenAIResourceName
}

resource apimOpenAIUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureOpenAI.id, apimManagedIdentityPrincipalId, openAIUserRoleId)
  scope: azureOpenAI
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUserRoleId)
    principalId: apimManagedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    description: 'Allows the APIM managed identity to invoke this Azure OpenAI backend.'
  }
}

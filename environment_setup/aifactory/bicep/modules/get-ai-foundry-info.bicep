// ================================================================
// GET AI FOUNDRY ACCOUNT INFO MODULE
// This module retrieves information about an existing AI Foundry account
// including its system-assigned managed identity principal ID
// ================================================================

@description('The name of the AI Foundry account')
param aiFoundryAccountName string

// Reference the existing AI Foundry account
resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: aiFoundryAccountName
}

@description('The principal ID of the AI Foundry account system-assigned managed identity')
output principalId string = aiFoundryAccount.identity.principalId

@description('The resource ID of the AI Foundry account')
output resourceId string = aiFoundryAccount.id

@description('The name of the AI Foundry account')
output name string = aiFoundryAccount.name

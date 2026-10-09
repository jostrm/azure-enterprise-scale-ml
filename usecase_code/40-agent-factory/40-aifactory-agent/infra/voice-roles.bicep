targetScope = 'resourceGroup'

// Optional live voice only (voice.enabled). Azure Voice Live authenticates with Microsoft Entra and, per
// https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-how-to#credentials, needs both roles on the
// Foundry account. They are broader than the project-scoped runtime role in identity.bicep, which is why they live in
// this separate, opt-in template: they are never created unless voice is enabled, and are never removed by turning it off.
// Verify in a test environment whether a narrower scope or role is enough before enabling this in production.
param identityName string
param foundryAccount string

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccount
}

resource voiceCognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, identity.id, 'voice-cognitive-services-user')
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
  }
}
resource voiceFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, identity.id, 'voice-foundry-user')
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  }
}

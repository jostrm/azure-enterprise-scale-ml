@description('Existing Azure AI (Cognitive Services) account name.')
param aiAccountName string
param profileName string = 'default'

// Reference to the parent Cognitive Services account
resource aiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiAccountName
}

// Defender for AI settings child resource (preview API)
resource defenderSettings 'Microsoft.CognitiveServices/accounts/defenderForAISettings@2025-10-01-preview' = {
  name: profileName
  parent: aiAccount
  properties: {
    state: 'Enabled'
  }
}

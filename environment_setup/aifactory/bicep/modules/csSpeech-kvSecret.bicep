// Sub-module: stores the Speech API key in Key Vault.
// Called conditionally (= if(!disableLocalAuth)) from csSpeech.bicep so that
// ARM never evaluates listKeys() when local auth is disabled.
param speechAccountName string
param keyvaultName string

resource csAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: speechAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

@description('Key Vault: Speech API key')
resource kValueSpeech 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'aifactory-proj-speech-api-key'
  properties: {
    value: csAccount.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

// Sub-module: stores the Document Intelligence API key in Key Vault.
// Called conditionally (= if(!disableLocalAuth)) from csDocIntelligence.bicep so that
// ARM never evaluates listKeys() when local auth is disabled.
param docIntAccountName string
param keyvaultName string

@description('Expiry of every secret and key this template creates, in Unix epoch seconds. Default: one year after the deployment runs (keyVaultDefaults.json secretExpiresAfter).')
param keyVaultSecretExpiry int = dateTimeToEpoch(dateTimeAdd(utcNow(), 'P1Y'))

resource csAccountDocInt 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: docIntAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

@description('Key Vault: Azure AI Document Intelligence API key')
resource kValueDocInt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'aifactory-proj-aidocintelligence-api-key'
  properties: {
    value: csAccountDocInt.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
      exp: keyVaultSecretExpiry
    }
  }
}

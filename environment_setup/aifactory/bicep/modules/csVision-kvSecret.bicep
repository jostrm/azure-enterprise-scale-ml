// Sub-module: stores the Vision API key in Key Vault.
// Called conditionally (= if(!disableLocalAuth)) from csVision.bicep so that
// ARM never evaluates listKeys() when local auth is disabled.
param visionAccountName string
param keyvaultName string

resource visionAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: visionAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

@description('Key Vault: Computer Vision API key')
resource kValueVision 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'aifactory-proj-vision-api-key'
  properties: {
    value: visionAccount.listKeys().key1
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

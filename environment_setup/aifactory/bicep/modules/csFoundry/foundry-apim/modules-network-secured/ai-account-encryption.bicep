// ================================================================
// AI ACCOUNT CMK ENCRYPTION MODULE
// Updates an existing AI Account with customer-managed key encryption
// Uses RBAC instead of Access Policies for Key Vault permissions
// ================================================================

param aiFoundryName string
param aiFoundryPrincipalId string
param location string
param keyVaultName string
param keyVaultUri string
param keyName string
param keyVersion string = '' // Optional - if empty, uses latest version

// Reference the existing AI Account (post-creation, after managed identity is available)
resource existingAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: aiFoundryName
}

// Reference the existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultName
}

// Assign Key Vault Crypto Service Encryption User role to AI Account System-Assigned Managed Identity
// This role grants: get, wrapKey, unwrapKey permissions for CMK
resource kvRbacForAiAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, aiFoundryPrincipalId, 'e147488a-f6f5-4113-8e2d-b22465e65bf6', 'ai-account-cmk')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'e147488a-f6f5-4113-8e2d-b22465e65bf6') // Key Vault Crypto Service Encryption User
    principalId: aiFoundryPrincipalId
    principalType: 'ServicePrincipal'
    description: 'CMK encryption permissions for AI Foundry account'
  }
}

// Note: Cosmos DB requires Key Vault access for CMK
// Using the global Cosmos DB service principal
var cosmosDbGlobalPrincipalId = 'a232010e-820c-4083-83bb-3ace5fc29d0b'

// Assign Key Vault Crypto Service Encryption User role to Cosmos DB service principal
resource kvRbacForCosmosDb 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, cosmosDbGlobalPrincipalId, 'e147488a-f6f5-4113-8e2d-b22465e65bf6', 'cosmosdb-cmk')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'e147488a-f6f5-4113-8e2d-b22465e65bf6') // Key Vault Crypto Service Encryption User
    principalId: cosmosDbGlobalPrincipalId
    principalType: 'ServicePrincipal'
    description: 'CMK encryption permissions for Cosmos DB'
  }
}

// Update the AI Account with customer-managed key encryption
resource accountUpdate 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: existingAccount.name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    // NEW: Customer-managed key encryption
    encryption: {
      keySource: 'Microsoft.KeyVault'
      keyVaultProperties: {
        keyVaultUri: keyVaultUri
        keyName: keyName
        keyVersion: empty(keyVersion) ? null : keyVersion // Use latest if not specified
      }
    }

    // EXISTING properties from the account
    publicNetworkAccess: existingAccount.properties.publicNetworkAccess
    allowProjectManagement: existingAccount.properties.allowProjectManagement
    customSubDomainName: existingAccount.properties.customSubDomainName
    disableLocalAuth: existingAccount.properties.disableLocalAuth
    networkAcls: existingAccount.properties.networkAcls
    networkInjections: existingAccount.properties.networkInjections
  }
  dependsOn: [
    kvRbacForAiAccount
    kvRbacForCosmosDb
  ]
}

output accountEncrypted bool = true
output encryptionKeyVaultUri string = keyVaultUri
output encryptionKeyName string = keyName

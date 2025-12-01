// ================================================================
// DISK ENCRYPTION SET MODULE
// Creates a Disk Encryption Set for AKS CMK encryption
// Requires a Key Vault key and creates a managed identity with proper RBAC
// ================================================================

@description('The name of the Disk Encryption Set')
param desName string

@description('The location for the Disk Encryption Set')
param location string

@description('The Key Vault resource ID')
param keyVaultId string

@description('The Key Vault key URI (with version)')
param keyUrl string

@description('Tags to apply to the resource')
param tags object = {}

// Create the Disk Encryption Set with SystemAssigned identity
resource diskEncryptionSet 'Microsoft.Compute/diskEncryptionSets@2024-03-02' = {
  name: desName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    activeKey: {
      sourceVault: {
        id: keyVaultId
      }
      keyUrl: keyUrl
    }
    encryptionType: 'EncryptionAtRestWithCustomerKey'
  }
}

@description('Disk Encryption Set resource ID')
output desId string = diskEncryptionSet.id

@description('Disk Encryption Set name')
output desName string = diskEncryptionSet.name

@description('Disk Encryption Set principal ID (for RBAC)')
output desPrincipalId string = diskEncryptionSet.identity.principalId

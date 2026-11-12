// Replaces aif_ensure_seeding_keyvault: the v1.24 stages still reference a seeding Key Vault shell.
// No secrets are written; the portal passes empty secret names, so no stage reads from it.
targetScope = 'resourceGroup'

param location string
param keyVaultName string
param costCenter string

resource seedingVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: {
    CostCenter: costCenter
    Purpose: 'AIFactorySeeding'
  }
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

output keyVaultId string = seedingVault.id

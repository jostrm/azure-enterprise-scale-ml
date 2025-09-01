
param policyName string
param keyVaultResourceName string
param principalId string
param keyVaultPermissions object
param additionalPrincipalIds array = []

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultResourceName
}

var main_principal_2_array = array(principalId)
var all_principals = union(main_principal_2_array, additionalPrincipalIds)

resource keyVaultAccessPolicyAdditionalGroup 'Microsoft.KeyVault/vaults/accessPolicies@2024-11-01' = {
  parent:keyVault
  name:policyName
  properties: {
    accessPolicies: [for oid in all_principals:{
      objectId: oid // object id (required) and if service principle also OID, not AppId
      permissions: keyVaultPermissions
      tenantId: subscription().tenantId
    }]
  }
}

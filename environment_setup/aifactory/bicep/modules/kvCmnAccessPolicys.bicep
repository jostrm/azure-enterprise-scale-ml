@description('Name of the KeyVault resource ex. kv-myservice.')
param keyVaultResourceName string
@description('Object ID of the main principal (Managed Identity, Service Principal or user). Empty, placeholder (<todo>, <optional>_ObjectID) and other non-GUID values are skipped.')
@secure()
param principalId string
@description('Assigned permissions for principalId and additionalPrincipalIds')
param keyVaultPermissions object
@description('optional additional, assigned permissions for Principal Id, ObjectID of AD users. Non-GUID values are skipped.')
param additionalPrincipalIds array

// No 'replace': skipped placeholders can leave an empty list, and 'replace' would then wipe every policy on the vault.
@allowed([
  'add'
  'remove'
])
@description('Policy name')
param policyName string

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultResourceName
}

var main_principal_2_array = array(principalId)
// Trimmed and lower-cased so ' b' from "a, b" or a secret value ending in a newline is kept, and case duplicates merge.
var all_principals = union(map(union(main_principal_2_array,additionalPrincipalIds), oid => toLower(trim(oid))), [])
// Key Vault rejects a non-GUID objectId, so variables-file placeholders such as databricksOID '<optional>_ObjectID'
// or DATABRICKS_OID '<todo>' are skipped instead of failing the deployment. GUID shape: 8-4-4-4-12 characters.
var guid_principals = filter(all_principals, oid => length(oid) == 36 && length(replace(oid, '-', '')) == 32 && take(skip(oid, 8), 1) == '-' && take(skip(oid, 13), 1) == '-' && take(skip(oid, 18), 1) == '-' && take(skip(oid, 23), 1) == '-')

resource keyVaultAccessPolicyAdditionalGroup 'Microsoft.KeyVault/vaults/accessPolicies@2024-11-01' = {
  parent:keyVault
  name:policyName
  properties: {
    accessPolicies: [for userOID in guid_principals:{
      objectId: userOID // object id (required) and if service principle also OID, not AppId
      permissions: keyVaultPermissions
      tenantId: subscription().tenantId
    }]
  }
}

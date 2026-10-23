// ================================================================
// KEY VAULT RBAC FOR A LIST OF PRINCIPALS
// The Azure RBAC replacement for the former access-policy module kvCmnAccessPolicys.bicep:
// the same principal inputs and rule, one built-in Key Vault role assignment per principal.
// Access-policy secret permissions map to roles: get or get/list -> secretsUser;
// get/list/set or all -> secretsOfficer (no narrower built-in role exists).
// ================================================================

@description('Name of the Key Vault resource ex. kv-myservice.')
param keyVaultResourceName string
@description('Object ID of the main principal (Managed Identity, Service Principal or user). Empty, placeholder (<todo>, <optional>_ObjectID) and other non-GUID values are skipped.')
@secure()
param principalId string
@description('Optional additional object IDs that get the same role. Non-GUID values are skipped.')
param additionalPrincipalIds array

@description('Built-in Key Vault data role, by name in common/keyVaultDefaults.json.')
@allowed([
  'secretsUser'
  'secretsOfficer'
  'cryptoUser'
  'cryptoServiceEncryptionUser'
  'certificatesOfficer'
  'administrator'
])
param keyVaultRole string

@description('Principal type of every principal. Empty lets Azure resolve it, for lists that mix users and groups.')
@allowed([
  ''
  'User'
  'Group'
  'ServicePrincipal'
])
param principalType string = ''

var roleDefinitionId = loadJsonContent('common/keyVaultDefaults.json', '$.roleDefinitionIds')[keyVaultRole]

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: keyVaultResourceName
}

var main_principal_2_array = array(principalId)
// Trimmed and lower-cased so ' b' from "a, b" or a secret value ending in a newline is kept, and case duplicates merge.
// Same body as normalizedObjectIds in common/objectIds.bicep, inlined to keep this module classic ARM.
var all_principals = union(filter(map(union(main_principal_2_array, additionalPrincipalIds), id => toLower(trim(id))), id => !empty(id) && id != 'null'), [])
// A role assignment needs the tenant's object ID, so variables-file placeholders such as databricksOID
// '<optional>_ObjectID' or DATABRICKS_OID '<todo>' are skipped instead of failing the deployment. GUID shape: 8-4-4-4-12.
var guid_principals = filter(all_principals, oid => length(oid) == 36 && length(replace(oid, '-', '')) == 32 && take(skip(oid, 8), 1) == '-' && take(skip(oid, 13), 1) == '-' && take(skip(oid, 18), 1) == '-' && take(skip(oid, 23), 1) == '-')

// Seeded like kvRbacSingleAssignment.bicep without a suffix: one name per vault, principal and role, so
// two templates that grant the same role to the same principal on the same vault never collide.
resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for oid in guid_principals: {
  name: guid(keyVault.id, oid, roleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: oid
    principalType: empty(principalType) ? null : principalType
    description: 'AI Factory Key Vault ${keyVaultRole} for ${oid}'
  }
}]

output roleAssignmentCount int = length(guid_principals)

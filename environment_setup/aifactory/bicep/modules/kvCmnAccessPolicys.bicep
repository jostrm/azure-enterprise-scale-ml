@description('Name of the KeyVault resource ex. kv-myservice.')
param keyVaultResourceName string
@description('Principal Id of the Azure resource (Managed Identity).')
@secure()
param principalId string
@description('Assigned permissions for Principal Id (Managed Identity)')
param keyVaultPermissions object
@description('optinal additional, assigned permissions for Principal Id, ObjectID of AD users')
param additionalPrincipalIds array

@allowed([
  'add'
  'remove'
  'replace'
])
@description('Policy name')
param policyName string

resource keyVault 'Microsoft.KeyVault/vaults@2019-09-01' existing = {
  name: keyVaultResourceName
}

var main_principal_2_array = array(principalId)
var all_principals = union(main_principal_2_array,additionalPrincipalIds)

resource keyVaultAccessPolicyAdditional 'Microsoft.KeyVault/vaults/accessPolicies@2019-09-01' = {
  parent:keyVault
  name:policyName
  properties: {
    accessPolicies: [for userOID in all_principals:{
      objectId: principalId // object id (required) and if service principle also OID, not AppId
      permissions: keyVaultPermissions
      tenantId: subscription().tenantId
    }]
  }
}

/*
resource keyVaultAccessPolicy 'Microsoft.KeyVault/vaults/accessPolicies@2019-09-01' = {
  parent:keyVault
  name:policyName
  properties: {
    accessPolicies: [
      {
        objectId: principalId
        permissions: keyVaultPermissions
        tenantId: subscription().tenantId
      }
    ]
  }
}
*/

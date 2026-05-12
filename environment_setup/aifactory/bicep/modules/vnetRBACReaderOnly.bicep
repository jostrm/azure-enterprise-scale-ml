// ============================================================================
// VNet Reader RBAC Module (No Bastion Dependency)
// Assigns Network Reader role to users, groups, SPs, and MIs on the VNet
// This allows reading VNet/subnet status, endpoint status, etc.
// ============================================================================

@description('VNet name to assign read permissions on')
param vNetName string

@description('Service principals and managed identities array')
param servicePrincipleAndMIArray array

@description('User or group object IDs array')
param user_object_ids array

@description('Use AD groups for role assignments (affects principalType)')
param useAdGroups bool = false

// Network Reader role - can view all network resources but cannot make changes
// Sufficient for reading VNet/subnet status, endpoint status, etc.
@description('Network Reader role - read-only access to network resources')
resource networkReaderRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Network Reader built-in role
}

// Reference to the existing VNet
resource vNetNameResource 'Microsoft.Network/virtualNetworks@2021-03-01' existing = {
  name: vNetName
}

// Assign Network Reader to users/groups on VNet
resource networkReaderUserVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(user_object_ids)): {
  name: guid('${user_object_ids[i]}-nwReader-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkReaderRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: 'Network Reader to user/group with OID ${user_object_ids[i]} for vNet: ${vNetName}'
  }
  scope: vNetNameResource
}]

// Assign Network Reader to service principals/managed identities on VNet
resource networkReaderSPVnet 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)): {
  name: guid('${servicePrincipleAndMIArray[i]}-nwReaderSP-${vNetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkReaderRoleDefinition.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: 'Network Reader to service principal/MI with OID ${servicePrincipleAndMIArray[i]} for vNet: ${vNetName}'
  }
  scope: vNetNameResource
}]

@description('Network Reader role assignment deployment status')
output networkReaderDeployed bool = true

@description('Number of user/group role assignments created')
output userRoleAssignmentsCount int = length(user_object_ids)

@description('Number of SP/MI role assignments created')
output spMiRoleAssignmentsCount int = length(servicePrincipleAndMIArray)

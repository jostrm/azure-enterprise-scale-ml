// ============================================================================
// RBAC for Subnet Network Contributor Role
// This module assigns Network Contributor role on a specific subnet to enable:
// - Microsoft.Network/virtualNetworks/subnets/join/action (required for Azure ML compute clusters)
// ============================================================================

param vNetName string // Name of the virtual network
param subnetName string // Name of the subnet (e.g., 'aca-subnet', 'aks-subnet', 'genai-subnet')
param servicePrincipleAndMIArray array // Service principal and managed identity object IDs
param user_object_ids array // User object IDs or EntraID group IDs
param useAdGroups bool = false // Whether user_object_ids contains AD groups

@description('Network Contributor role - required to join subnets')
resource networkContributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '4d97b98b-1d4f-4787-a291-c67834d212e7'
}

// Reference to existing VNet
resource vNetResource 'Microsoft.Network/virtualNetworks@2023-11-01' existing = {
  name: vNetName
}

// Reference to existing subnet
resource subnetResource 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vNetResource
  name: subnetName
}

// Network Contributor for Users/Groups on Subnet
resource networkContributorUserSubnet 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(user_object_ids)): {
  name: guid('${user_object_ids[i]}-nwContributor-${subnetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: user_object_ids[i]
    principalType: useAdGroups ? 'Group' : 'User'
    description: 'Network Contributor to USER with OID ${user_object_ids[i]} for subnet: ${subnetName}'
  }
  scope: subnetResource
}]

// Network Contributor for Service Principals and Managed Identities on Subnet
resource networkContributorSPSubnet 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): {
  name: guid('${servicePrincipleAndMIArray[i]}-nwContribSP-${subnetName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: networkContributorRoleDefinition.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: 'Network Contributor to SERVICE PRINCIPAL with OID ${servicePrincipleAndMIArray[i]} for subnet: ${subnetName}'
  }
  scope: subnetResource
}]

// ============================================================================
// Outputs
// ============================================================================

@description('Subnet resource ID where Network Contributor was assigned')
output subnetId string = subnetResource.id

@description('Number of user role assignments created')
output userRoleAssignmentCount int = length(user_object_ids)

@description('Number of SP/MI role assignments created')
output spMiRoleAssignmentCount int = length(servicePrincipleAndMIArray)

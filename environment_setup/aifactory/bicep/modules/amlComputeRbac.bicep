// ============================================================================
// RBAC for Azure ML Compute Cluster Creation with VNet Integration
// This module assigns roles required for users and service principals to:
// 1. Create compute clusters in Azure ML workspace (Azure ML Compute Operator)
// 2. Access Azure ML Registry for model deployment (Azure ML Registry User)
// 
// Note: Network Contributor role on subnet should be assigned separately 
// in the VNet's resource group scope
// ============================================================================

param projectTeamGroupOrUser array // User object IDs or EntraID group IDs
param servicePrincipleAndMIArray array // Service principal and managed identity object IDs
param useAdGroups bool = false // Whether projectTeamGroupOrUser contains AD groups
param amlWorkspaceName string // Azure ML workspace name for Compute Operator role

// Role definitions
@description('Azure ML Compute Operator role - required to create compute clusters')
resource amlComputeOperatorRole 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'e503ece1-11d0-4e8e-8e2c-7a6c3bf38815'
}

@description('Azure ML Registry User role - required to access Azure ML Registry')
resource amlRegistryUserRole 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: '1823dd4f-9b8c-4ab6-ab4e-7397a3684615'
}

// Reference existing Azure ML workspace for scoping Compute Operator role
resource amlWorkspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = {
  name: amlWorkspaceName
}

var principalTypeUser = useAdGroups ? 'Group' : 'User'

// ============================================================================
// Azure ML Compute Operator Role Assignments on Workspace
// Required for: Creating and managing compute clusters
// ============================================================================

// Compute Operator for Users/Groups
resource computeOperatorUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(projectTeamGroupOrUser)): {
  name: guid(amlWorkspace.id, amlComputeOperatorRole.id, projectTeamGroupOrUser[i])
  scope: amlWorkspace
  properties: {
    roleDefinitionId: amlComputeOperatorRole.id
    principalId: projectTeamGroupOrUser[i]
    principalType: principalTypeUser
    description: 'Azure ML Compute Operator on workspace ${amlWorkspaceName} for ${principalTypeUser} ${projectTeamGroupOrUser[i]}'
  }
}]

// Compute Operator for Service Principals and Managed Identities
resource computeOperatorSPs 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): {
  name: guid(amlWorkspace.id, amlComputeOperatorRole.id, servicePrincipleAndMIArray[i])
  scope: amlWorkspace
  properties: {
    roleDefinitionId: amlComputeOperatorRole.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: 'Azure ML Compute Operator on workspace ${amlWorkspaceName} for SP/MI ${servicePrincipleAndMIArray[i]}'
  }
}]

// ============================================================================
// Azure ML Registry User Role Assignments on Workspace
// Required for: Accessing Azure ML Registry for model deployment
// ============================================================================

// Registry User for Users/Groups
resource registryUserUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(projectTeamGroupOrUser)): {
  name: guid(amlWorkspace.id, amlRegistryUserRole.id, projectTeamGroupOrUser[i])
  scope: amlWorkspace
  properties: {
    roleDefinitionId: amlRegistryUserRole.id
    principalId: projectTeamGroupOrUser[i]
    principalType: principalTypeUser
    description: 'Azure ML Registry User on workspace ${amlWorkspaceName} for ${principalTypeUser} ${projectTeamGroupOrUser[i]}'
  }
}]

// Registry User for Service Principals and Managed Identities
resource registryUserSPs 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, length(servicePrincipleAndMIArray)): {
  name: guid(amlWorkspace.id, amlRegistryUserRole.id, servicePrincipleAndMIArray[i])
  scope: amlWorkspace
  properties: {
    roleDefinitionId: amlRegistryUserRole.id
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description: 'Azure ML Registry User on workspace ${amlWorkspaceName} for SP/MI ${servicePrincipleAndMIArray[i]}'
  }
}]

// ============================================================================
// Outputs
// ============================================================================

@description('Azure ML workspace resource ID where roles were assigned')
output amlWorkspaceId string = amlWorkspace.id

@description('Number of user role assignments created')
output userRoleAssignmentCount int = length(projectTeamGroupOrUser) * 2

@description('Number of SP/MI role assignments created')
output spMiRoleAssignmentCount int = length(servicePrincipleAndMIArray) * 2

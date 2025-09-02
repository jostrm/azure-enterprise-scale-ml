// ================================================================
// STORAGE PRIVATE ENDPOINT READER ROLE TO AI PROJECT MODULE
// This module assigns Reader role on storage account private endpoints
// to the AI Foundry project's system-assigned managed identity
// ================================================================

// ============== PARAMETERS ==============
@description('Storage account name to assign Reader role for')
param storageAccountName string

@description('AI Project name (Azure ML workspace name)')
param aiProjectName string

@description('Blob private endpoint name')
param blobPrivateEndpointName string

// ============================================================================
// EXISTING RESOURCES
// ============================================================================

// Reference to existing AI Foundry project (Azure ML workspace)
resource existingAIProject 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' existing = {
  name: aiProjectName
}

// Reference to existing blob private endpoint
resource existingBlobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' existing = {
  name: blobPrivateEndpointName
}

// ============================================================================
// ROLE DEFINITIONS
// ============================================================================

@description('Built-in Role: [Reader](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#reader)')
resource readerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  scope: subscription()
}

// ============================================================================
// ROLE ASSIGNMENTS
// ============================================================================

@description('Assign the AI Project system-assigned managed identity Reader role on the storage blob private endpoint.')
resource aiProjectReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: existingBlobPrivateEndpoint
  name: guid(existingBlobPrivateEndpoint.id, existingAIProject.id, readerRole.id, 'blob-reader')
  properties: {
    roleDefinitionId: readerRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: existingAIProject.identity.principalId
  }
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Storage account name that was configured')
output storageAccountName string = storageAccountName

@description('AI Project name that was assigned the Reader role')
output aiProjectName string = aiProjectName

@description('Blob private endpoint name that was configured')
output blobPrivateEndpointName string = blobPrivateEndpointName

@description('Role assignment completed successfully')
output roleAssignmentCompleted bool = true

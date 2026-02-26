// Helper module to conditionally get AI Search principal ID
targetScope = 'resourceGroup'

@description('AI Search service name')
param aiSearchName string

@description('Check if AI Search exists')
param aiSearchExists bool = false

param aiSearchEnabled bool = false

// This module handles the conditional logic internally
// Note: This will fail at deployment time if aiSearchExists=true but AI Search doesn't   actually exist

// Outputs - handle the conditional logic here
@description('Principal ID of AI Search service (empty if service does not exist)')
output principalId string = aiSearchExists && aiSearchEnabled ? reference(resourceId('Microsoft.Search/searchServices', aiSearchName), '2024-06-01-preview', 'Full').identity.principalId : ''

@description('AI Search service name')
output name string = aiSearchName

@description('AI Search exists flag')
output exists bool = aiSearchExists && aiSearchEnabled

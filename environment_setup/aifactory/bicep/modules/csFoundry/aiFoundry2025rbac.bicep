/* This (AVM) is worse, since using aiFoundry2025rbac.bicep
┌─────────────────────────────────────────────────────────┐
│  POTENTIAL OVER-ASSIGNMENT ISSUE                        │
│  ┌─────────────────────────────────────────────────────┐│
│  │ From: Deploy-Your-AI-Application-In-Production repo:││
│  │  aiFoundry2025rbac.bicep assigns:                   ││
│  │  Users → Contributor + User roles (MORE access)     ││
│  │  SP    → User roles only      (LESS access)         ││
│  └─────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────┐│
│  │ From: Enterprise scale AI Factory (jostrm) repo:    ││
│  │  buildRoleAssignments.bicep assigns:                ││
│  │  Users → User roles only      (LESS access)         ││
│  │  SP    → Contributor roles    (MORE access)         ││
│  └─────────────────────────────────────────────────────┘│
│  ⚠️  Different permission models!                      │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  This: Explicit Individual Role Assignment Resources     │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  For Users/Groups:                                  │ │
│  │  ├─ OpenAI Contributor                              │ │
│  │  │  Role: a001fd3d-188f-4b5d-821b-7da978bf7442      │ │
│  │  ├─ Cognitive Services Contributor                  │ │
│  │  │  Role: a97b65f3-24c7-4388-baec-2e87135dc908      │ │
│  │  └─ Cognitive Services User                         │ │
│  │     Role: a97b65f3-24c7-4388-baec-2e87135dc908      │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  For Service Principals:                            │ │
│  │  └─ OpenAI User                                     │ │
│  │     Role: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd      │ │
│  └─────────────────────────────────────────────────────┘ │
│  📝 Fixed schema - specific role combinations           
└─────────────────────────────────────────────────────────┘
*/
@description('Array of user object IDs to assign roles to')
param userObjectIds array = []

@description('Array of service principal IDs to assign roles to')
param servicePrincipalIds array = []

@description('Project principal ID to assign roles to')
param projectPrincipalId string = ''

@description('Name of the Cognitive Services account to assign roles for')
param cognitiveServicesAccountName string

@description('Role definition ID for Cognitive Services Contributor')
param cognitiveServicesContributorRoleId string

@description('Role definition ID for Cognitive Services User')
param cognitiveServicesUserRoleId string

@description('Role definition ID for OpenAI Contributor')
param openAIContributorRoleId string

@description('Role definition ID for OpenAI User')
param openAIUserRoleId string

@description('Role definition ID for Azure AI Developer')
param azureAIDeveloperRoleId string = '64702f94-c441-49e6-a78b-ef80e0188fee'

@description('Whether to use AD Groups instead of individual users')
param useAdGroups bool = false

resource cognitiveServicesAccount 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' existing = {
  name: cognitiveServicesAccountName
}

// Assign OpenAI Contributor role to users
resource openAIContributorRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, openAIContributorRoleId, 'contributor')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIContributorRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Assign Cognitive Services Contributor role to users
resource cognitiveServicesContributorRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, cognitiveServicesContributorRoleId, 'contributor')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Assign Cognitive Services User role to users
resource cognitiveServicesUserRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, cognitiveServicesUserRoleId, 'user')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// Assign OpenAI User role to service principals
resource openAIUserRoleAssignmentServicePrincipals 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (spId, i) in servicePrincipalIds: {
  name: guid(cognitiveServicesAccount.id, spId, openAIUserRoleId, 'sp-user')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIUserRoleId)
    principalId: spId
    principalType: 'ServicePrincipal'
  }
}]

// Assign Azure AI Developer role to users
resource azureAIDeveloperRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, azureAIDeveloperRoleId, 'ai-developer')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
  }
}]

// ============== PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign OpenAI Contributor role to project principal
resource openAIContributorRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, openAIContributorRoleId, 'project-contributor')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - OpenAI Contributor for project operations'
  }
}

// Assign Cognitive Services Contributor role to project principal
resource cognitiveServicesContributorRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, cognitiveServicesContributorRoleId, 'project-cs-contributor')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - Cognitive Services Contributor for project operations'
  }
}

// Assign Cognitive Services User role to project principal
resource cognitiveServicesUserRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, cognitiveServicesUserRoleId, 'project-cs-user')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - Cognitive Services User for project operations'
  }
}

// Assign Azure AI Developer role to project principal
resource azureAIDeveloperRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, azureAIDeveloperRoleId, 'project-ai-developer')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'AI Foundry project managed identity - Azure AI Developer for project operations'
  }
}

// Output the assigned role names for reference
output userRoleNames array = [for (userObjectId, i) in userObjectIds: 'User ${userObjectId} assigned OpenAI Contributor, Cognitive Services Contributor, Cognitive Services User, and Azure AI Developer roles']
output servicePrincipalRoleNames array = [for (spId, i) in servicePrincipalIds: 'Service Principal ${spId} assigned OpenAI User role']
output projectPrincipalRoleNames string = !empty(projectPrincipalId) ? 'Project Principal ${projectPrincipalId} assigned OpenAI Contributor, Cognitive Services Contributor, Cognitive Services User, and Azure AI Developer roles' : 'No project principal provided'

@description('Number of role assignments created')
output roleAssignmentsCount int = (length(userObjectIds) * 4) + length(servicePrincipalIds) + (!empty(projectPrincipalId) ? 4 : 0)

/* This (AVM) is worse, since using aiFoundry2025rbac.bicep
┌───────────────────────────────────────  }  }
}]

// Assign OpenAI User role to service principalsOpenAI User role to service principals┐
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
│  │  ├─ Cognitive Services User                         │ │
│  │  │  Role: a97b65f3-24c7-4388-baec-2e87135dc908      │ │
│  │  └─ Cognitive Services Data Contributor (Preview)   │ │
│  │     Role: 19c28022-e58e-450d-a464-0b2a53034789      │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  For Service Principals:                            │ │
│  │  ├─ OpenAI User                                     │ │
│  │  │  Role: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd      │ │
│  │  └─ Cognitive Services Data Contributor (Preview)   │ │
│  │     Role: 19c28022-e58e-450d-a464-0b2a53034789      │ │
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

@description('Whether to use AD Groups instead of individual users')
param useAdGroups bool = false

@description('Role definition ID for Cognitive Services Data Contributor (Preview)')
param cognitiveServicesDataContributorRoleId string = '19c28022-e58e-450d-a464-0b2a53034789'

resource cognitiveServicesAccount 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' existing = {
  name: cognitiveServicesAccountName
}

// Assign OpenAI Contributor role to users
resource openAIContributorRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, openAIContributorRoleId, 'user-openai-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIContributorRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: '!01: user-openai-contributor-manual'
  }
}]

// Assign Cognitive Services Contributor role to users
resource cognitiveServicesContributorRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, cognitiveServicesContributorRoleId, 'user-cs-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: '!02: user-cs-contributor-manual'
  }
}]

// Assign Cognitive Services Data Contributor (Preview) role to users
resource cognitiveServicesDataContributorRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, cognitiveServicesDataContributorRoleId, 'user-cs-data-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesDataContributorRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: '!02b: user-cs-data-contributor-manual'
  }
}]

/*
// Assign Cognitive Services User role to users
resource cognitiveServicesUserRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, cognitiveServicesUserRoleId, 'user-cs-user-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: '03: user-cs-user-manual'
  }
}]

// Assign Azure AI Developer role to users
resource azureAIDeveloperRoleAssignmentUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (userObjectId, i) in userObjectIds: {
  name: guid(cognitiveServicesAccount.id, userObjectId, azureAIDeveloperRoleId, 'user-ai-developer-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', azureAIDeveloperRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: '04: user-ai-developer-manual'
  }
}]

*/

// ============== PROJECT PRINCIPAL ROLE ASSIGNMENTS ==============

// Assign OpenAI User role to service principals
resource openAIUserRoleAssignmentServicePrincipals 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (spId, i) in servicePrincipalIds: {
  name: guid(cognitiveServicesAccount.id, spId, openAIUserRoleId, 'sp-user-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIUserRoleId)
    principalId: spId
    principalType: 'ServicePrincipal'
    description: '!05: sp-user-manual (2 rows OK)'
  }
}]

// Assign Cognitive Services Data Contributor (Preview) role to service principals
resource cognitiveServicesDataContributorRoleAssignmentSPs 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (spId, i) in servicePrincipalIds: {
  name: guid(cognitiveServicesAccount.id, spId, cognitiveServicesDataContributorRoleId, 'sp-cs-data-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesDataContributorRoleId)
    principalId: spId
    principalType: 'ServicePrincipal'
    description: '!05b: sp-cs-data-contributor-manual'
  }
}]

// Assign OpenAI Contributor role to project principal
resource openAIContributorRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, openAIContributorRoleId, 'project-openai-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', openAIContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: '!06:project-openai-contributor-manual: AI Foundry project managed identity - OpenAI Contributor for project operations'
  }
}

// Assign Cognitive Services Contributor role to project principal
resource cognitiveServicesContributorRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, cognitiveServicesContributorRoleId, 'project-cs-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: '!07:project-cs-contributor-manual:AI Foundry project managed identity - Cognitive Services Contributor for project operations'
  }
}

// Assign Cognitive Services User role to project principal
resource cognitiveServicesUserRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, cognitiveServicesUserRoleId, 'project-cs-user-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: '!08:project-cs-user-manual: AI Foundry project managed identity - Cognitive Services User for project operations'
  }
}

// Assign Cognitive Services Data Contributor (Preview) role to project principal
resource cognitiveServicesDataContributorRoleAssignmentProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(projectPrincipalId)) {
  name: guid(cognitiveServicesAccount.id, projectPrincipalId, cognitiveServicesDataContributorRoleId, 'project-cs-data-contributor-manual')
  scope: cognitiveServicesAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesDataContributorRoleId)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    description: '!08b:project-cs-data-contributor-manual: AI Foundry project managed identity - Cognitive Services Data Contributor (Preview)'
  }
}

// Output the assigned role names for reference
output userRoleNames array = [for (userObjectId, i) in userObjectIds: 'User ${userObjectId} assigned OpenAI Contributor, Cognitive Services Contributor, and Cognitive Services User roles']
output servicePrincipalRoleNames array = [for (spId, i) in servicePrincipalIds: 'Service Principal ${spId} assigned OpenAI User role']
output projectPrincipalRoleNames string = !empty(projectPrincipalId) ? 'Project Principal ${projectPrincipalId} assigned OpenAI Contributor, Cognitive Services Contributor, and Cognitive Services User roles' : 'No project principal provided'

@description('Number of role assignments created')
output roleAssignmentsCount int = (length(userObjectIds) * 3) + length(servicePrincipalIds) + (!empty(projectPrincipalId) ? 3 : 0)

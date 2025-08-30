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

// Output the assigned role names for reference
output userRoleNames array = [for (userObjectId, i) in userObjectIds: 'User ${userObjectId} assigned OpenAI Contributor, Cognitive Services Contributor, and Cognitive Services User roles']
output servicePrincipalRoleNames array = [for (spId, i) in servicePrincipalIds: 'Service Principal ${spId} assigned OpenAI User role']

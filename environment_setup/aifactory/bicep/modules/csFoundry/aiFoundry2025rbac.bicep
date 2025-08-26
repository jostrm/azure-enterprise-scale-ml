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

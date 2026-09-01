@description('Name of the existing Log Analytics workspace in this resource group.')
param workspaceName string

@description('Object IDs of project users or Microsoft Entra groups.')
param userObjectIds array

@description('Whether userObjectIds contains Microsoft Entra group object IDs.')
param useAdGroups bool = false

var logAnalyticsReaderRoleId = '73c42c96-874c-492b-b04d-ab87d138a893'

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource logAnalyticsReaderProjectMembers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for userObjectId in userObjectIds: {
  name: guid(logAnalyticsWorkspace.id, logAnalyticsReaderRoleId, userObjectId)
  scope: logAnalyticsWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logAnalyticsReaderRoleId)
    principalId: userObjectId
    principalType: useAdGroups ? 'Group' : 'User'
    description: 'Log Analytics Reader for project member ${userObjectId} on ${logAnalyticsWorkspace.name}'
  }
}]

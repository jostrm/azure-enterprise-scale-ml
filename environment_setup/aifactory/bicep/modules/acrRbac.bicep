param aiHubName string
param aiHubRgName string
param acrName string

resource acr 'Microsoft.ContainerRegistry/registries@2023-08-01-preview' existing = {
  name: acrName
}

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (!empty(aiHubName)) {
  name: aiHubName
  scope: resourceGroup(aiHubRgName)
}

@description('Built-in Role: [AcrPull](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#acrpull)')
resource containerRegistryPullRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  scope: subscription()
}

@description('Built-in Role: [AcrPush](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#acrpush)')
resource containerRegistryPushRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '8311e382-0749-4cb8-b61a-304f252e45ec'
  scope: subscription()
}


@description('Assign AML Workspace\'s ID: AcrPush to workload\'s container registry.')
resource containerRegistryPushRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiHubName)) {
  name: guid(acr.id, aiHub.name, containerRegistryPushRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPushRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiHub.identity.principalId
  }
}

@description('Assign AML Workspace\'s Managed Online Endpoint: AcrPull to workload\'s container registry.')
resource computeInstanceContainerRegistryPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01'= if (!empty(aiHubName)) {
  name: guid(acr.id, aiHub.name, containerRegistryPullRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPullRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiHub.identity.principalId
  }
}

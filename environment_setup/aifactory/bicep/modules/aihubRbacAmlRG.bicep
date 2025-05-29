param azureMachineLearningObjectId string
param aiHubName string = ''
param aiHubPrincipalId string = ''

var aml_appId = '0736f41a-0425-4b46-bdb5-1563eff02385'
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Hub -is-> AI services
var azureAIAdministrator = 'b78c5d69-af96-48a3-bf8d-a8b4d589de94' // AIHub -> RG: (AIServices, AI Projects, Agents)

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing  = if(!empty(aiHubName)) {
  name: aiHubName
}

@description('Role Assignment for ResoureGroup: AzureML OID for Contributor')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, contributorRole,azureMachineLearningObjectId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRole)
    principalId: azureMachineLearningObjectId
    principalType: 'ServicePrincipal'
    description:'Contributor on RG for AML SP on RG: ${resourceGroup().id}'
  }
  scope:resourceGroup()
}

// AI Hub on RG level
@description('AI Hub: azureAIAdministrator:')
resource azureAIAdministratorAiHub 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!empty(aiHubName)) {
  name: guid(resourceGroup().id, azureAIAdministrator, aiHubPrincipalId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIAdministrator)
    principalId: aiHubPrincipalId
    principalType: 'ServicePrincipal'
    description:'azureAIAdministrator role to AI Hub for : ${aiHub.name}'
  }
  scope:resourceGroup()
}


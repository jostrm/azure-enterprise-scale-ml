
param azureMachineLearningObjectId string

var aml_appId = '0736f41a-0425-4b46-bdb5-1563eff02385'
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Hub -is-> AI services

@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
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

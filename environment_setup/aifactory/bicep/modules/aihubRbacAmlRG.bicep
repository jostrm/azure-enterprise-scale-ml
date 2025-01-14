
var aml_appId = '0736f41a-0425-4b46-bdb5-1563eff02385'
var aml_oId = 'b6b19655-d941-419f-abe6-8378b92cb8d2'

// AI services
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Hub -is-> AI services

@description('Role Assignment for ResoureGroup: acrPushRoleId for users.')
resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, contributorRole,aml_oId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRole)
    principalId: aml_oId
    principalType: 'ServicePrincipal'
    description:'Contributor on RG for AML SP on RG: ${resourceGroup().id}'
  }
  scope:resourceGroup()
}

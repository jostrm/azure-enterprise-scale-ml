param projectSP string
param adfSP string
param projectADuser string
param amlName string
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var main_principal_2_array = array(projectADuser)
var all_users = union(main_principal_2_array,additionalUserIds)


resource amlNameResource 'Microsoft.MachineLearningServices/workspaces@2021-04-01' existing = {
  name: amlName
}

resource contributorSP 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${projectSP}-${contributorRole}-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${contributorRole}'
    principalId: projectSP
    principalType: 'ServicePrincipal'
    description:'Contributor to service principal ${projectSP} for Azure ML ${amlName}'
  }
  scope:amlNameResource
}
resource contributorADF 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = if(adfSP!='null') {
  name: guid('${adfSP}-${contributorRole}-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${contributorRole}'
    principalId: adfSP
    principalType: 'ServicePrincipal'
    description:'Contributor to Azure datafactory ${adfSP} to run Azure ML pipelines ${amlName}'
  }
  scope:amlNameResource
  dependsOn: [
    contributorSP
  ]
}

resource contributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(all_users)):{
  name: guid('${all_users[i]}-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: '${subscription().id}/providers/Microsoft.Authorization/roleDefinitions/${contributorRole}'
    principalId: all_users[i]
    principalType: 'User'
    description:'Contributor to USER with OID  ${all_users[i]} for Azure ML ${amlName}'
  }
  scope:amlNameResource
  dependsOn: [
    contributorSP
    contributorADF
  ]
}]

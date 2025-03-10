@secure()
param projectSP string

@description('Specifies the objectId of the Data factory managed identity')
param adfSP string

@description('Specifies the objectId of the technical contact')
param projectADuser string

@description('Specifies the name the azure machine learning resource')
param amlName string

param useAdGroups bool = false

@description('This is the built-in Contributor role. See https://docs.microsoft.com/azure/role-based-access-control/built-in-roles#contributor')
resource contributorRoleDefinition 'Microsoft.Authorization/roleDefinitions@2018-01-01-preview' existing = {
  scope: subscription()
  name: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
var main_principal_2_array = array(projectADuser)
//var all_users = union(main_principal_2_array,additionalUserIds)


resource amlNameResource 'Microsoft.MachineLearningServices/workspaces@2021-04-01' existing = {
  name: amlName
}

resource contributorSP 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid('${projectSP}-contributor-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: projectSP
    principalType: 'ServicePrincipal'
    description:'Contributor to service principal ${projectSP} for Azure ML ${amlName}'
  }
  scope:amlNameResource
}
resource contributorADF 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = if(adfSP!='null') {
  name: guid('${adfSP}-contributor-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: adfSP
    principalType: 'ServicePrincipal'
    description:'Contributor to Azure datafactory ${adfSP} to run Azure ML pipelines ${amlName}'
  }
  scope:amlNameResource
  dependsOn: [
    contributorSP
  ]
}

resource contributorUserOrGroup 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(additionalUserIds)):{
  name: guid('${additionalUserIds[i]}-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: additionalUserIds[i]
    principalType:useAdGroups? 'Group':'User'
    description:'Contributor to USER or GROUP with OID  ${additionalUserIds[i]} for Azure ML ${amlName}'
  }
  scope:amlNameResource
  dependsOn: [
    contributorSP
    contributorADF
  ]
}]

resource contributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(main_principal_2_array)): if(useAdGroups==false){
  name: guid('${main_principal_2_array[i]}-${amlName}-${resourceGroup().id}')
  properties: {
    roleDefinitionId: contributorRoleDefinition.id
    principalId: main_principal_2_array[i]
    principalType:'User'
    description:'Contributor to USER with OID  ${main_principal_2_array[i]} for Azure ML ${amlName}'
  }
  scope:amlNameResource
  dependsOn: [
    contributorSP
    contributorADF
  ]
}]
 
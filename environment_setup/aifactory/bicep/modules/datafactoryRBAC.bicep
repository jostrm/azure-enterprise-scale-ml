@description('Specifies the objectId of the technical contact')
param userPrincipalId string = ''
@description('Specifies the name the datafactory resource')
param datafactoryName string
param useAdGroups bool = false
@description('Additional optional Object ID of more people to access Resource group')
param additionalUserIds array
param servicePrincipleAndMIArray array = []
param disableContributorAccessForUsers bool = false

var roleContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
var roleDataFactoryContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '673868aa-7521-48a0-acc6-0f60742d39f5')
var roleDataFactoryDataFlowDeveloper = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'e5c9c5c8-8c8a-4f2d-9b9a-4b4b4b4b4b4b')
var allUsers = additionalUserIds

resource datafactory 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: datafactoryName
}

resource contributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(allUsers)): if(!disableContributorAccessForUsers){
  name: guid(allUsers[i], roleContributor, datafactory.id, 'contributor-adf')
  properties: {
    roleDefinitionId: roleContributor
    principalId: allUsers[i]
    principalType:useAdGroups? 'Group':'User'
    description:'01 - ADF: Contributor to USER with OID  ${allUsers[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]

resource dataFactoryContributorUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(allUsers)):{
  name: guid(allUsers[i], roleDataFactoryContributor, datafactory.id, 'adf-contributor')
  properties: {
    roleDefinitionId: roleDataFactoryContributor
    principalId: allUsers[i]
    principalType:useAdGroups? 'Group':'User'
    description:'02 - ADF: Data Factory Contributor to USER with OID  ${allUsers[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]

resource dataFactoryDataFlowDeveloperUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(allUsers)):{
  name: guid(allUsers[i], roleDataFactoryDataFlowDeveloper, datafactory.id, 'adf-dataflow-dev')
  properties: {
    roleDefinitionId: roleDataFactoryDataFlowDeveloper
    principalId: allUsers[i]
    principalType:useAdGroups? 'Group':'User'
    description:'03 - ADF: Data Factory Data Flow Developer to USER with OID  ${allUsers[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]

// Service Principal and Managed Identity Role Assignments
resource contributorServicePrincipal 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)): if(!disableContributorAccessForUsers){
  name: guid(servicePrincipleAndMIArray[i], roleContributor, datafactory.id, 'sp-contributor')
  properties: {
    roleDefinitionId: roleContributor
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'04 - ADF: Contributor to SERVICE PRINCIPAL with OID  ${servicePrincipleAndMIArray[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]

resource dataFactoryContributorServicePrincipal 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(servicePrincipleAndMIArray[i], roleDataFactoryContributor, datafactory.id, 'sp-adf-contributor')
  properties: {
    roleDefinitionId: roleDataFactoryContributor
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'05 - ADF: Data Factory Contributor to SERVICE PRINCIPAL with OID  ${servicePrincipleAndMIArray[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]

resource dataFactoryDataFlowDeveloperServicePrincipal 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, length(servicePrincipleAndMIArray)):{
  name: guid(servicePrincipleAndMIArray[i], roleDataFactoryDataFlowDeveloper, datafactory.id, 'sp-adf-dataflow-dev')
  properties: {
    roleDefinitionId: roleDataFactoryDataFlowDeveloper
    principalId: servicePrincipleAndMIArray[i]
    principalType: 'ServicePrincipal'
    description:'06 - ADF: Data Factory Data Flow Developer to SERVICE PRINCIPAL with OID  ${servicePrincipleAndMIArray[i]} for Data Factory: ${datafactoryName}'
  }
  scope:datafactory
}]


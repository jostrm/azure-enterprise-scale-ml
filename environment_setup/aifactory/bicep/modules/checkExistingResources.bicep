param resourceGroupName string
param resourceNames object

// mlEndpoint: 'Microsoft.MachineLearningServices/workspaces/onlineEndpoints'
@description('Array of resource types to check existence for')
param resourceTypes object = {
  aiFoundryHub: 'Microsoft.MachineLearningServices/workspaces'
  aiFoundryProject: 'Microsoft.MachineLearningServices/workspaces'
  aiSearch: 'Microsoft.Search/searchServices'
  dashboardInsights: 'Microsoft.Portal/dashboards'
  applicationInsight: 'Microsoft.Insights/components'
  aiServices: 'Microsoft.CognitiveServices/accounts'
  bing: 'Microsoft.Bing/accounts'
  containerAppsEnv: 'Microsoft.App/managedEnvironments'
  containerAppA: 'Microsoft.App/containerApps'
  containerAppW: 'Microsoft.App/containerApps'
  cosmosDB: 'Microsoft.DocumentDB/databaseAccounts'
  functionApp: 'Microsoft.Web/sites'
  webApp: 'Microsoft.Web/sites'
  funcAppServicePlan: 'Microsoft.Web/serverfarms'
  webbAppServicePlan: 'Microsoft.Web/serverfarms'
  keyvault: 'Microsoft.KeyVault/vaults'
  miACA: 'Microsoft.ManagedIdentity/userAssignedIdentities'
  miPrj: 'Microsoft.ManagedIdentity/userAssignedIdentities'
  storageAccount1001: 'Microsoft.Storage/storageAccounts'
  storageAccount2001: 'Microsoft.Storage/storageAccounts'
  redis: 'Microsoft.Cache/Redis'
  postgreSQL: 'Microsoft.DBforPostgreSQL/flexibleServers'
  sqlServer: 'Microsoft.Sql/servers'
  sqlDatabase: 'Microsoft.Sql/servers/databases'
  aiFoundry: 'Microsoft.CognitiveServices/accounts'
}

//Microsoft.DBforPostgreSQL/flexibleServers@2025-01-01-preview
//Microsoft.DBforPostgreSQL/servers

/*
  {
    name: 'mlEndpoint'
    resourceName: resourceNames.mlEndpoint
    resourceType: resourceTypes.mlEndpoint
  }
*/
var allResourceInfo = [
  {
    name: 'aiFoundryHub'
    resourceName: resourceNames.aiFoundryHub
    resourceType: resourceTypes.aiFoundryHub
  }
  {
    name: 'aiFoundryProject'
    resourceName: resourceNames.aiFoundryProject
    resourceType: resourceTypes.aiFoundryProject
  }
  {
    name: 'aiSearch'
    resourceName: resourceNames.aiSearch
    resourceType: resourceTypes.aiSearch
  }
  {
    name: 'dashboardInsights'
    resourceName: resourceNames.dashboardInsights
    resourceType: resourceTypes.dashboardInsights
  }
  {
    name: 'applicationInsight'
    resourceName: resourceNames.applicationInsight
    resourceType: resourceTypes.applicationInsight
  }
  {
    name: 'aiServices'
    resourceName: resourceNames.aiServices
    resourceType: resourceTypes.aiServices
  }
  {
    name: 'bing'
    resourceName: resourceNames.bing
    resourceType: resourceTypes.bing
  }
  {
    name: 'containerAppsEnv'
    resourceName: resourceNames.containerAppsEnv
    resourceType: resourceTypes.containerAppsEnv
  }
  {
    name: 'containerAppA'
    resourceName: resourceNames.containerAppA
    resourceType: resourceTypes.containerAppA
  }
  {
    name: 'containerAppW'
    resourceName: resourceNames.containerAppW
    resourceType: resourceTypes.containerAppW
  }
  {
    name: 'cosmosDB'
    resourceName: resourceNames.cosmosDB
    resourceType: resourceTypes.cosmosDB
  }
  {
    name: 'functionApp'
    resourceName: resourceNames.functionApp
    resourceType: resourceTypes.functionApp
  }
  {
    name: 'webApp'
    resourceName: resourceNames.webApp
    resourceType: resourceTypes.webApp
  }
  {
    name: 'funcAppServicePlan'
    resourceName: resourceNames.funcAppServicePlan
    resourceType: resourceTypes.funcAppServicePlan
  }
  {
    name: 'webbAppServicePlan'
    resourceName: resourceNames.webbAppServicePlan
    resourceType: resourceTypes.webbAppServicePlan
  }
  {
    name: 'keyvault'
    resourceName: resourceNames.keyvault
    resourceType: resourceTypes.keyvault
  }
  {
    name: 'miACA'
    resourceName: resourceNames.miACA
    resourceType: resourceTypes.miACA
  }
  {
    name: 'miPrj'
    resourceName: resourceNames.miPrj
    resourceType: resourceTypes.miPrj
  }
  {
    name: 'storageAccount1001'
    resourceName: resourceNames.storageAccount1001
    resourceType: resourceTypes.storageAccount1001
  }
  {
    name: 'storageAccount2001'
    resourceName: resourceNames.storageAccount2001
    resourceType: resourceTypes.storageAccount2001
  }
  {
    name: 'redis'
    resourceName: resourceNames.redis
    resourceType: resourceTypes.redis
  }
  {
    name: 'postgreSQL'
    resourceName: resourceNames.postgreSQL
    resourceType: resourceTypes.postgreSQL
  }
  {
    name: 'sqlServer'
    resourceName: resourceNames.sqlServer
    resourceType: resourceTypes.sqlServer
  }
  {
    name: 'sqlDatabase'
    resourceName: resourceNames.sqlDatabase
    resourceType: resourceTypes.sqlDatabase
  }
  {
    name: 'aiFoundry'
    resourceName: resourceNames.aiFoundry
    resourceType: resourceTypes.aiFoundry
  }
]

// Call the checkResourceExists module for each resource
module checkResourceExists 'checkResourceExists.bicep' = [for (resourceInfo, i) in allResourceInfo: {
  name: 'checkResourceExists-${resourceInfo.name}'
  params: {
    resourceGroupName: resourceGroupName
    resourceName: resourceInfo.resourceName
    resourceType: resourceInfo.resourceType
    parentResourceName: resourceInfo.name == 'sqlDatabase' ? resourceNames.sqlServer : ''
  }
}]

output aiFoundryHubExists bool = length(resourceNames.aiFoundryHub) > 0 ? checkResourceExists[0].outputs.exists : false
output aiFoundryProjectExists bool = length(resourceNames.aiFoundryProject) > 0 ? checkResourceExists[1].outputs.exists : false
//output mlEndpointExists bool = length(resourceNames.mlEndpoint) > 0 ? checkResourceExists[2].outputs.exists : false
output aiSearchExists bool = length(resourceNames.aiSearch) > 0 ? checkResourceExists[3].outputs.exists : false
output dashboardInsightsExists bool = length(resourceNames.dashboardInsights) > 0 ? checkResourceExists[4].outputs.exists : false
output applicationInsightExists bool = length(resourceNames.applicationInsight) > 0 ? checkResourceExists[5].outputs.exists : false
output aiServicesExists bool = length(resourceNames.aiServices) > 0 ? checkResourceExists[6].outputs.exists : false
output bingExists bool = length(resourceNames.bing) > 0 ? checkResourceExists[7].outputs.exists : false
output containerAppsEnvExists bool = length(resourceNames.containerAppsEnv) > 0 ? checkResourceExists[8].outputs.exists : false
output containerAppAExists bool = length(resourceNames.containerAppA) > 0 ? checkResourceExists[8].outputs.exists : false
output containerAppWExists bool = length(resourceNames.containerAppW) > 0 ? checkResourceExists[9].outputs.exists : false
output cosmosDBExists bool = length(resourceNames.cosmosDB) > 0 ? checkResourceExists[10].outputs.exists : false
output functionAppExists bool = length(resourceNames.functionApp) > 0 ? checkResourceExists[10].outputs.exists : false
output webAppExists bool = length(resourceNames.webApp) > 0 ? checkResourceExists[11].outputs.exists : false
output funcAppServicePlanExists bool = length(resourceNames.funcAppServicePlan) > 0 ? checkResourceExists[12].outputs.exists : false
output webbAppServicePlanExists bool = length(resourceNames.webbAppServicePlan) > 0 ? checkResourceExists[13].outputs.exists : false
output keyvaultExists bool = length(resourceNames.keyvault) > 0 ? checkResourceExists[13].outputs.exists : false
output miACAExists bool = length(resourceNames.miACA) > 0 ? checkResourceExists[14].outputs.exists : false
output miPrjExists bool = length(resourceNames.miPrj) > 0 ? checkResourceExists[15].outputs.exists : false
output storageAccount1001Exists bool = length(resourceNames.storageAccount1001) > 0 ? checkResourceExists[15].outputs.exists : false
output storageAccount2001Exists bool = length(resourceNames.storageAccount2001) > 0 ? checkResourceExists[15].outputs.exists : false
output redisExists bool = length(resourceNames.redis) > 0 ? checkResourceExists[16].outputs.exists : false
output postgreSQLExists bool = length(resourceNames.postgreSQL) > 0 ? checkResourceExists[17].outputs.exists : false
output sqlServerExists bool = length(resourceNames.sqlServer) > 0 ? checkResourceExists[18].outputs.exists : false
output sqlDatabaseExists bool = length(resourceNames.sqlDatabase) > 0 ? checkResourceExists[19].outputs.exists : false
output aiFoundryExists bool = length(resourceNames.aiFoundry) > 0 ? checkResourceExists[20].outputs.exists : false

// Debug Resource IDs
output keyvaultResourceId string = length(resourceNames.keyvault) > 0 ? checkResourceExists[13].outputs.resourceId : ''
output aiSearchResourceId string = length(resourceNames.keyvault) > 0 ? checkResourceExists[13].outputs.resourceId : ''

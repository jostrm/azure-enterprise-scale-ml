param resourceGroupName string
param resourceName string
param resourceType string
param parentResourceName string = '' // Optional, for resources with a parent

// Individual resource blocks for each type
resource existingAiFoundryHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (resourceType == 'Microsoft.MachineLearningServices/workspaces') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingAiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if (resourceType == 'Microsoft.Search/searchServices') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingDashboardInsights 'Microsoft.Portal/dashboards@2020-09-01-preview' existing = if (resourceType == 'Microsoft.Portal/dashboards') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingApplicationInsight 'Microsoft.Insights/components@2020-02-02' existing = if (resourceType == 'Microsoft.Insights/components') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingAiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (resourceType == 'Microsoft.CognitiveServices/accounts') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingBing 'Microsoft.Bing/accounts@2020-06-10' existing = if (resourceType == 'Microsoft.Bing/accounts') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingContainerAppsEnv 'Microsoft.App/managedEnvironments@2025-01-01' existing = if (resourceType == 'Microsoft.App/managedEnvironments') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingContainerApp 'Microsoft.App/containerApps@2025-01-01' existing = if (resourceType == 'Microsoft.App/containerApps') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingCosmosDB 'Microsoft.DocumentDB/databaseAccounts@2024-12-01-preview' existing = if (resourceType == 'Microsoft.DocumentDB/databaseAccounts') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingFunctionApp 'Microsoft.Web/sites@2022-09-01' existing = if (resourceType == 'Microsoft.Web/sites') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingFuncAppServicePlan 'Microsoft.Web/serverfarms@2022-09-01' existing = if (resourceType == 'Microsoft.Web/serverfarms') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingKeyvault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (resourceType == 'Microsoft.KeyVault/vaults') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingMi 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if (resourceType == 'Microsoft.Storage/storageAccounts') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingRedis 'Microsoft.Cache/Redis@2024-11-01' existing = if (resourceType == 'Microsoft.Cache/Redis') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingPostgreSQL 'Microsoft.DBforPostgreSQL/flexibleServers@2025-01-01-preview' existing = if (resourceType == 'Microsoft.DBforPostgreSQL/servers') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingSqlServer 'Microsoft.Sql/servers@2022-05-01-preview' existing = if (resourceType == 'Microsoft.Sql/servers') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingSqlDatabase 'Microsoft.Sql/servers/databases@2022-05-01-preview' existing = if (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName)) {
  name: '${parentResourceName}/${resourceName}'
  scope: resourceGroup(resourceGroupName)
}
output exists bool = (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName))
  ? !empty(existingSqlDatabase)
  : (resourceType == 'Microsoft.Sql/servers')
    ? !empty(existingSqlServer)
    : (resourceType == 'Microsoft.DBforPostgreSQL/servers')
      ? !empty(existingPostgreSQL)
      : (resourceType == 'Microsoft.Cache/Redis')
        ? !empty(existingRedis)
        : (resourceType == 'Microsoft.Storage/storageAccounts')
          ? !empty(existingStorageAccount)
          : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities')
            ? !empty(existingMi)
            : (resourceType == 'Microsoft.KeyVault/vaults')
              ? !empty(existingKeyvault)
              : (resourceType == 'Microsoft.Web/serverfarms')
                ? !empty(existingFuncAppServicePlan)
                : (resourceType == 'Microsoft.Web/sites')
                  ? !empty(existingFunctionApp)
                  : (resourceType == 'Microsoft.DocumentDB/databaseAccounts')
                    ? !empty(existingCosmosDB)
                    : (resourceType == 'Microsoft.App/containerApps')
                      ? !empty(existingContainerApp)
                      : (resourceType == 'Microsoft.App/managedEnvironments')
                        ? !empty(existingContainerAppsEnv)
                        : (resourceType == 'Microsoft.Bing/accounts')
                          ? !empty(existingBing)
                          : (resourceType == 'Microsoft.CognitiveServices/accounts')
                            ? !empty(existingAiServices)
                            : (resourceType == 'Microsoft.Insights/components')
                              ? !empty(existingApplicationInsight)
                              : (resourceType == 'Microsoft.Portal/dashboards')
                                ? !empty(existingDashboardInsights)
                                : (resourceType == 'Microsoft.Search/searchServices')
                                  ? !empty(existingAiSearch)
                                  : (resourceType == 'Microsoft.MachineLearningServices/workspaces')
                                    ? !empty(existingAiFoundryHub)
                                    : false
/*
output resourceId string = (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName))
  ? (!empty(existingSqlDatabase) && !empty(existingSqlDatabase.id)) ? existingSqlDatabase.id : ''
  : (resourceType == 'Microsoft.Sql/servers')
    ? (!empty(existingSqlServer) && !empty(existingSqlServer.id)) ? existingSqlServer.id : ''
    : (resourceType == 'Microsoft.DBforPostgreSQL/servers')
      ? (!empty(existingPostgreSQL) && !empty(existingPostgreSQL.id)) ? existingPostgreSQL.id : ''
      : (resourceType == 'Microsoft.Cache/Redis')
        ? (!empty(existingRedis) && !empty(existingRedis.id)) ? existingRedis.id : ''
        : (resourceType == 'Microsoft.Storage/storageAccounts')
          ? (!empty(existingStorageAccount) && !empty(existingStorageAccount.id)) ? existingStorageAccount.id : ''
          : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities')
            ? (!empty(existingMi) && !empty(existingMi.id)) ? existingMi.id : ''
            : (resourceType == 'Microsoft.KeyVault/vaults')
              ? (!empty(existingKeyvault) && !empty(existingKeyvault.id)) ? existingKeyvault.id : ''
              : (resourceType == 'Microsoft.Web/serverfarms')
                ? (!empty(existingFuncAppServicePlan) && !empty(existingFuncAppServicePlan.id)) ? existingFuncAppServicePlan.id : ''
                : (resourceType == 'Microsoft.Web/sites')
                  ? (!empty(existingFunctionApp) && !empty(existingFunctionApp.id)) ? existingFunctionApp.id : ''
                  : (resourceType == 'Microsoft.DocumentDB/databaseAccounts')
                    ? (!empty(existingCosmosDB) && !empty(existingCosmosDB.id)) ? existingCosmosDB.id : ''
                    : (resourceType == 'Microsoft.App/containerApps')
                      ? (!empty(existingContainerApp) && !empty(existingContainerApp.id)) ? existingContainerApp.id : ''
                      : (resourceType == 'Microsoft.App/managedEnvironments')
                        ? (!empty(existingContainerAppsEnv) && !empty(existingContainerAppsEnv.id)) ? existingContainerAppsEnv.id : ''
                        : (resourceType == 'Microsoft.Bing/accounts')
                          ? (!empty(existingBing) && !empty(existingBing.id)) ? existingBing.id : ''
                          : (resourceType == 'Microsoft.CognitiveServices/accounts')
                            ? (!empty(existingAiServices) && !empty(existingAiServices.id)) ? existingAiServices.id : ''
                            : (resourceType == 'Microsoft.Insights/components')
                              ? (!empty(existingApplicationInsight) && !empty(existingApplicationInsight.id)) ? existingApplicationInsight.id : ''
                              : (resourceType == 'Microsoft.Portal/dashboards')
                                ? (!empty(existingDashboardInsights) && !empty(existingDashboardInsights.id)) ? existingDashboardInsights.id : ''
                                : (resourceType == 'Microsoft.Search/searchServices')
                                  ? (!empty(existingAiSearch) && !empty(existingAiSearch.id)) ? existingAiSearch.id : ''
                                  : (resourceType == 'Microsoft.MachineLearningServices/workspaces')
                                    ? (!empty(existingAiFoundryHub) && !empty(existingAiFoundryHub.id)) ? existingAiFoundryHub.id : ''
                                    : ''

*/

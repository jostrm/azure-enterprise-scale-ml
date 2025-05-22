param resourceGroupName string
param resourceName string
param resourceType string
param parentResourceName string = '' // Optional, for resources with a parent

/*
output exists bool = (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName))
  ? !empty(resourceId(resourceGroupName, resourceType, parentResourceName, resourceName))
  : !empty(resourceId(resourceGroupName, resourceType, resourceName))

output resourceId string = (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName))
  ? resourceId(resourceGroupName, resourceType, parentResourceName, resourceName)
  : resourceId(resourceGroupName, resourceType, resourceName)

*/

// Individual resource blocks for each type
resource existingAiFoundryHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (resourceType == 'Microsoft.MachineLearningServices/workspaces') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingAiFoundryProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' existing = if (resourceType == 'Microsoft.MachineLearningServices/workspaces') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}
/*
resource existingMlEndpoint 'Microsoft.MachineLearningServices/workspaces/onlineEndpoints@2024-10-01-preview' existing = if (resourceType == 'Microsoft.MachineLearningServices/workspaces/onlineEndpoints') {
  name: '${parentResourceName}/${resourceName}'
  scope: resourceGroup(resourceGroupName)
}
*/

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

resource existingContainerAppA 'Microsoft.App/containerApps@2025-01-01' existing = if (resourceType == 'Microsoft.App/containerApps') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingContainerAppW 'Microsoft.App/containerApps@2025-01-01' existing = if (resourceType == 'Microsoft.App/containerApps') {
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

resource existingWebApp 'Microsoft.Web/sites@2022-09-01' existing = if (resourceType == 'Microsoft.Web/sites') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingFuncAppServicePlan 'Microsoft.Web/serverfarms@2022-09-01' existing = if (resourceType == 'Microsoft.Web/serverfarms') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingWebbAppServicePlan 'Microsoft.Web/serverfarms@2022-09-01' existing = if (resourceType == 'Microsoft.Web/serverfarms') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingKeyvault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (resourceType == 'Microsoft.KeyVault/vaults') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingMiACA 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingMiPrj 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = if (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingStorageAccount1001 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if (resourceType == 'Microsoft.Storage/storageAccounts') {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}

resource existingStorageAccount2001 'Microsoft.Storage/storageAccounts@2024-01-01' existing = if (resourceType == 'Microsoft.Storage/storageAccounts') {
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
resource existingAiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = if (resourceType == 'Microsoft.CognitiveServices/accounts') {
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
  ? (empty(existingSqlDatabase)) ? false : !empty(existingSqlDatabase.id)
  : (resourceType == 'Microsoft.Sql/servers')
    ? (empty(existingSqlServer)) ? false : !empty(existingSqlServer.id)
    : (resourceType == 'Microsoft.DBforPostgreSQL/servers')
      ? (empty(existingPostgreSQL)) ? false : !empty(existingPostgreSQL.id)
      : (resourceType == 'Microsoft.Cache/Redis')
        ? (empty(existingRedis)) ? false : !empty(existingRedis.id)
        : (resourceType == 'Microsoft.Storage/storageAccounts' && resourceName == 'storageAccount1001')
          ? (empty(existingStorageAccount1001)) ? false : !empty(existingStorageAccount1001.id)
          : (resourceType == 'Microsoft.Storage/storageAccounts' && resourceName == 'storageAccount2001')
            ? (empty(existingStorageAccount2001)) ? false : !empty(existingStorageAccount2001.id)
            : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities' && resourceName == 'miACA')
              ? (empty(existingMiACA)) ? false : !empty(existingMiACA.id)
              : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities' && resourceName == 'miPrj')
                ? (empty(existingMiPrj)) ? false : !empty(existingMiPrj.id)
                : (resourceType == 'Microsoft.KeyVault/vaults')
                  ? (empty(existingKeyvault)) ? false : !empty(existingKeyvault.id)
                  : (resourceType == 'Microsoft.Web/serverfarms' && resourceName == 'funcAppServicePlan')
                    ? (empty(existingFuncAppServicePlan)) ? false : !empty(existingFuncAppServicePlan.id)
                    : (resourceType == 'Microsoft.Web/serverfarms' && resourceName == 'webbAppServicePlan')
                      ? (empty(existingWebbAppServicePlan)) ? false : !empty(existingWebbAppServicePlan.id)
                      : (resourceType == 'Microsoft.Web/sites' && resourceName == 'functionApp')
                        ? (empty(existingFunctionApp)) ? false : !empty(existingFunctionApp.id)
                        : (resourceType == 'Microsoft.Web/sites' && resourceName == 'webApp')
                          ? (empty(existingWebApp)) ? false : !empty(existingWebApp.id)
                          : (resourceType == 'Microsoft.DocumentDB/databaseAccounts')
                            ? (empty(existingCosmosDB)) ? false : !empty(existingCosmosDB.id)
                            : (resourceType == 'Microsoft.App/containerApps' && resourceName == 'containerAppA')
                              ? (empty(existingContainerAppA)) ? false : !empty(existingContainerAppA.id)
                              : (resourceType == 'Microsoft.App/containerApps' && resourceName == 'containerAppW')
                                ? (empty(existingContainerAppW)) ? false : !empty(existingContainerAppW.id)
                                : (resourceType == 'Microsoft.App/managedEnvironments')
                                  ? (empty(existingContainerAppsEnv)) ? false : !empty(existingContainerAppsEnv.id)
                                  : (resourceType == 'Microsoft.Bing/accounts')
                                    ? (empty(existingBing)) ? false : !empty(existingBing.id)
                                    : (resourceType == 'Microsoft.CognitiveServices/accounts' && resourceName == 'aiServices')
                                      ? (empty(existingAiServices)) ? false : !empty(existingAiServices.id)
                                      : (resourceType == 'Microsoft.CognitiveServices/accounts' && resourceName == 'aiFoundry')
                                        ? (empty(existingAiFoundry)) ? false : !empty(existingAiFoundry.id)
                                        : (resourceType == 'Microsoft.Insights/components')
                                          ? (empty(existingApplicationInsight)) ? false : !empty(existingApplicationInsight.id)
                                          : (resourceType == 'Microsoft.Portal/dashboards')
                                            ? (empty(existingDashboardInsights)) ? false : !empty(existingDashboardInsights.id)
                                            : (resourceType == 'Microsoft.Search/searchServices')
                                              ? (empty(existingAiSearch)) ? false : !empty(existingAiSearch.id)
                                              : (resourceType == 'Microsoft.MachineLearningServices/workspaces' && resourceName == 'aiFoundryHub')
                                                ? (empty(existingAiFoundryHub)) ? false : !empty(existingAiFoundryHub.id)
                                                : (resourceType == 'Microsoft.MachineLearningServices/workspaces' && resourceName == 'aiFoundryProject')
                                                  ? (empty(existingAiFoundryProject)) ? false : !empty(existingAiFoundryProject.id)
                                                  : false

output resourceId string = (resourceType == 'Microsoft.Sql/servers/databases' && !empty(parentResourceName))
  ? (empty(existingSqlDatabase)) ? '' : existingSqlDatabase.id
  : (resourceType == 'Microsoft.Sql/servers')
    ? (empty(existingSqlServer)) ? '' : existingSqlServer.id
    : (resourceType == 'Microsoft.DBforPostgreSQL/servers')
      ? (empty(existingPostgreSQL)) ? '' : existingPostgreSQL.id
      : (resourceType == 'Microsoft.Cache/Redis')
        ? (empty(existingRedis)) ? '' : existingRedis.id
        : (resourceType == 'Microsoft.Storage/storageAccounts' && resourceName == 'storageAccount1001')
          ? (empty(existingStorageAccount1001)) ? '' : existingStorageAccount1001.id
          : (resourceType == 'Microsoft.Storage/storageAccounts' && resourceName == 'storageAccount2001')
            ? (empty(existingStorageAccount2001)) ? '' : existingStorageAccount2001.id
            : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities' && resourceName == 'miACA')
              ? (empty(existingMiACA)) ? '' : existingMiACA.id
              : (resourceType == 'Microsoft.ManagedIdentity/userAssignedIdentities' && resourceName == 'miPrj')
                ? (empty(existingMiPrj)) ? '' : existingMiPrj.id
                : (resourceType == 'Microsoft.KeyVault/vaults')
                  ? (empty(existingKeyvault)) ? '' : existingKeyvault.id
                  : (resourceType == 'Microsoft.Web/serverfarms' && resourceName == 'funcAppServicePlan')
                    ? (empty(existingFuncAppServicePlan)) ? '' : existingFuncAppServicePlan.id
                    : (resourceType == 'Microsoft.Web/serverfarms' && resourceName == 'webbAppServicePlan')
                      ? (empty(existingWebbAppServicePlan)) ? '' : existingWebbAppServicePlan.id
                      : (resourceType == 'Microsoft.Web/sites' && resourceName == 'functionApp')
                        ? (empty(existingFunctionApp)) ? '' : existingFunctionApp.id
                        : (resourceType == 'Microsoft.Web/sites' && resourceName == 'webApp')
                          ? (empty(existingWebApp)) ? '' : existingWebApp.id
                          : (resourceType == 'Microsoft.DocumentDB/databaseAccounts')
                            ? (empty(existingCosmosDB)) ? '' : existingCosmosDB.id
                            : (resourceType == 'Microsoft.App/containerApps' && resourceName == 'containerAppA')
                              ? (empty(existingContainerAppA)) ? '' : existingContainerAppA.id
                              : (resourceType == 'Microsoft.App/containerApps' && resourceName == 'containerAppW')
                                ? (empty(existingContainerAppW)) ? '' : existingContainerAppW.id
                                : (resourceType == 'Microsoft.App/managedEnvironments')
                                  ? (empty(existingContainerAppsEnv)) ? '' : existingContainerAppsEnv.id
                                  : (resourceType == 'Microsoft.Bing/accounts')
                                    ? (empty(existingBing)) ? '' : existingBing.id
                                    : (resourceType == 'Microsoft.CognitiveServices/accounts' && resourceName == 'aiServices')
                                      ? (empty(existingAiServices)) ? '' : existingAiServices.id
                                      : (resourceType == 'Microsoft.CognitiveServices/accounts' && resourceName == 'aiFoundry')
                                        ? (empty(existingAiFoundry)) ? '' : existingAiFoundry.id
                                        : (resourceType == 'Microsoft.Insights/components')
                                          ? (empty(existingApplicationInsight)) ? '' : existingApplicationInsight.id
                                          : (resourceType == 'Microsoft.Portal/dashboards')
                                            ? (empty(existingDashboardInsights)) ? '' : existingDashboardInsights.id
                                            : (resourceType == 'Microsoft.Search/searchServices')
                                              ? (empty(existingAiSearch)) ? '' : existingAiSearch.id
                                              : (resourceType == 'Microsoft.MachineLearningServices/workspaces' && resourceName == 'aiFoundryHub')
                                                ? (empty(existingAiFoundryHub)) ? '' : existingAiFoundryHub.id
                                                : (resourceType == 'Microsoft.MachineLearningServices/workspaces' && resourceName == 'aiFoundryProject')
                                                  ? (empty(existingAiFoundryProject)) ? '' : existingAiFoundryProject.id
                                                  : ''

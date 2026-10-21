// Private Linux Python Function App for the AI Factory lifecycle template, in an existing AI Factory project.
// Reuses the project's VNet integration subnet (snt-prjNNN-webapp, delegated to Microsoft.Web/serverFarms), a
// private endpoint subnet, the project's storage account (identity-based, no keys) and Application Insights.
// Public network access and basic publishing credentials are off; deploy over the VPN with Entra auth.
// Route-all stays off: private endpoints (RFC1918) go through the VNet, GitHub egress uses the platform's outbound IPs.

targetScope = 'resourceGroup'

@description('Function App name. Keep it outside purple\'s own project Function pattern func-prj<NNN>-..., for example aiflc-prj001-<loc>-<env>-<uniq5>-001.')
param functionAppName string

@description('App Service plan name.')
param planName string = 'asp-${functionAppName}'

@description('Dedicated Linux plan SKU. Elastic Premium is not supported here: it needs an Azure Files content share, which needs storage keys.')
@allowed(['B1', 'B2', 'B3', 'S1', 'P0v3', 'P1v3'])
param planSku string = 'B1'

param location string = resourceGroup().location

@allowed(['3.11', '3.12'])
param pythonVersion string = '3.11'

@description('Subnet resource ID for regional VNet integration (delegated to Microsoft.Web/serverFarms; /26 or larger when plans share it).')
param integrationSubnetId string

@description('Subnet resource ID for the private endpoint.')
param privateEndpointSubnetId string

@description('privatelink.azurewebsites.net zone ID. Empty when a central DNS policy (centralDnsZoneByPolicyInHub) adds the zone group.')
param privateDnsZoneId string = ''

@description('Existing storage account in this resource group for AzureWebJobsStorage, the event queue and the state table.')
param storageAccountName string

@description('Existing Application Insights component in this resource group.')
param appInsightsName string

@description('Log Analytics workspace resource ID for FunctionAppLogs and metrics. Empty: no diagnostic setting.')
param logAnalyticsWorkspaceId string = ''

@description('RBAC-enabled Key Vault the Function reads its secrets from (AIF_KEY_VAULT_NAME). Empty: no grant.')
param keyVaultName string = ''

@description('Grant the queue role (needed when AIF_EVENT_PROCESSING=queue).')
param grantQueueRole bool = true

@secure()
@description('Extra app settings (AIF_*). Secrets are read from Key Vault by name, never passed here.')
param appSettings object = {}

param tags object = {}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: planSku
  }
  properties: {
    reserved: true
  }
}

var baseSettings = [
  { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
  { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
  { name: 'AzureWebJobsStorage__accountName', value: storage.name }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
  { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
  { name: 'AIF_STORE', value: 'table' }
  { name: 'AIF_TABLE_ACCOUNT', value: storage.name }
]
var baseNames = [
  'FUNCTIONS_EXTENSION_VERSION'
  'FUNCTIONS_WORKER_RUNTIME'
  'AzureWebJobsStorage__accountName'
  'APPLICATIONINSIGHTS_CONNECTION_STRING'
  'SCM_DO_BUILD_DURING_DEPLOYMENT'
  'AIF_STORE'
  'AIF_TABLE_ACCOUNT'
]
var extraSettings = [for setting in filter(items(appSettings), item => !contains(baseNames, item.key)): {
  name: setting.key
  value: string(setting.value)
}]

resource site 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  tags: union(tags, { 'hidden-link: /app-insights-resource-id': insights.id })
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    publicNetworkAccess: 'Disabled'
    virtualNetworkSubnetId: integrationSubnetId
    siteConfig: {
      linuxFxVersion: 'Python|${pythonVersion}'
      alwaysOn: true
      healthCheckPath: '/api/v1/health'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      http20Enabled: true
      vnetRouteAllEnabled: false
      ipSecurityRestrictionsDefaultAction: 'Deny'
      scmIpSecurityRestrictionsDefaultAction: 'Deny'
      appSettings: concat(baseSettings, extraSettings)
    }
  }
}

resource scmBasicAuth 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: site
  name: 'scm'
  properties: {
    allow: false
  }
}

resource ftpBasicAuth 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-04-01' = {
  parent: site
  name: 'ftp'
  properties: {
    allow: false
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${functionAppName}-pend'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    customNetworkInterfaceName: '${functionAppName}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${functionAppName}-pend'
        properties: {
          privateLinkServiceId: site.id
          groupIds: ['sites']
        }
      }
    ]
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!empty(privateDnsZoneId)) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-azurewebsites-net'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

module roles 'roles.bicep' = {
  name: 'roles-${uniqueString(site.id)}'
  params: {
    principalId: site.identity.principalId
    storageAccountName: storage.name
    grantQueueRole: grantQueueRole
    keyVaultName: keyVaultName
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: 'diag-${functionAppName}'
  scope: site
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      { category: 'FunctionAppLogs', enabled: true }
      { category: 'AppServiceAuditLogs', enabled: true }
      { category: 'AppServiceAuthenticationLogs', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

output functionAppName string = site.name
output defaultHostName string = site.properties.defaultHostName
output principalId string = site.identity.principalId

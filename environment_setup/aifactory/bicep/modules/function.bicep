param name string
param location string
param tags object
param appServicePlanName string = ''
param sku object = {
  name: 'EP1'  // EP1 is for Premium plan which supports private endpoints
  tier: 'ElasticPremium'
  family: 'EP'
  capacity: 1
}
param appSettings array = []
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string
param storageAccountName string
param ipRules array = []
param allowedOrigins array = [
  'https://mlworkspace.azure.ai'
  'https://ml.azure.com'
  'https://*.ml.azure.com'
  'https://ai.azure.com'
  'https://*.ai.azure.com'
  'https://mlworkspacecanary.azure.ai'
  'https://mlworkspace.azureml-test.net'
  'https://42.swedencentral.instances.azureml.ms'
  'https://*.instances.azureml.ms'
  'https://*.azureml.ms'
]
param applicationInsightsName string = ''
param logAnalyticsWorkspaceName string = ''
param logAnalyticsWorkspaceRG string = ''
param runtime string = 'dotnet'  // Options: 'node', 'dotnet', 'java', 'python'

// Use provided name or create one based on Function name
var servicePlanName = !empty(appServicePlanName) ? appServicePlanName : '${name}-plan'

// Get references to resources
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = if (!empty(logAnalyticsWorkspaceName)) {
  name: logAnalyticsWorkspaceName
  scope: resourceGroup(logAnalyticsWorkspaceRG)
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

// Get subnet reference for private endpoint
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  name: '${vnetName}/${subnetNamePend}'
  scope: resourceGroup(vnetResourceGroupName)
}

// Create App Service Plan
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: servicePlanName
  location: location
  tags: tags
  sku: sku
  properties: {
    reserved: runtime == 'node' || runtime == 'python' // Set to true for Linux
  }
}

// Create Function App
resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: name
  location: location
  tags: tags
  kind: runtime == 'node' || runtime == 'python' ? 'functionapp,linux' : 'functionapp'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    virtualNetworkSubnetId: enablePublicAccessWithPerimeter ? null : subnet.id
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled' : (enablePublicGenAIAccess ? 'Enabled' : 'Disabled')
    siteConfig: {
      alwaysOn: true
      cors: {
        allowedOrigins: allowedOrigins
      }
      ipSecurityRestrictions: enablePublicAccessWithPerimeter ? [] : ipRules
      appSettings: concat([
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: runtime
        }
        {
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: toLower(name)
        }
        {
          name: 'WEBSITE_VNET_ROUTE_ALL'
          value: '1'
        }
      ], appSettings, !empty(applicationInsightsName) ? [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ] : [])
    }
  }
}

// Create private endpoint
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if(enablePublicAccessWithPerimeter==false) {
  name: 'p-${name}-function'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'p-${name}-function'
        properties: {
          privateLinkServiceId: functionApp.id
          groupIds: [
            'sites'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output defaultHostname string = functionApp.properties.defaultHostName
output principalId string = functionApp.identity.principalId
output dnsConfig array = [
  {
    name: !enablePublicAccessWithPerimeter ? privateEndpoint.name : ''
    type: 'sites'
    id: !enablePublicAccessWithPerimeter ? privateEndpoint.id : ''
  }
]

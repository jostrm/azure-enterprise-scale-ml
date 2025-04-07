param name string
param location string
param tags object
param appServicePlanName string = ''
param sku object = {
  name: 'S1'
  tier: 'Standard'
  capacity: 1
}
param appSettings array = []
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string
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
param applicationInsightsName string
param logAnalyticsWorkspaceName string
param logAnalyticsWorkspaceRG string


// Use provided name or create one based on WebApp name
var servicePlanName = !empty(appServicePlanName) ? appServicePlanName : '${name}-plan'

// Get references to resources
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = if (!empty(logAnalyticsWorkspaceName)) {
  name: logAnalyticsWorkspaceName
  scope: resourceGroup(logAnalyticsWorkspaceRG)
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
    reserved: false // Set to true for Linux runtime == 'node' || runtime == 'python' // Set to true for Linux
  }
}

// Create Web App
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: name
  location: location
  tags: tags
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
      appSettings: concat(appSettings, !empty(applicationInsightsName) ? [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'ApplicationInsightsAgent_EXTENSION_VERSION'
          value: '~2'
        }
      ] : [])
    }
  }
}

// Create private endpoint
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if(enablePublicAccessWithPerimeter==false) {
  name: 'p-${name}-webapp'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'p-${name}-webapp'
        properties: {
          privateLinkServiceId: webApp.id
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

output webAppName string = webApp.name
output webAppId string = webApp.id
output defaultHostname string = webApp.properties.defaultHostName
output principalId string = webApp.identity.principalId
output dnsConfig array = [
  {
    name: !enablePublicAccessWithPerimeter? privateEndpoint.name: ''
    type: 'sites'
    id:!enablePublicAccessWithPerimeter? privateEndpoint.id: ''
  }
]

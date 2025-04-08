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
param runtime string = 'python'  // Options: 'dotnet', 'node', 'python', 'java'
param pythonVersion string = '3.11' // Used if runtime is 'python'
param subnetIntegrationName string  // Name of the subnet for VNet integration

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
// Get subnet reference for VNet integration
resource integrationSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  name: '${vnetName}/${subnetIntegrationName}'
  scope: resourceGroup(vnetResourceGroupName)
}

// Create App Service Plan
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: servicePlanName
  location: location
  tags: tags
  sku: sku
  properties: {
    reserved: runtime == 'node' || runtime == 'python' // Set to true for Linux runtimes
  }
}

var formattedIpRules = [for (ip, i) in ipRules: {
  // Ensure IP addresses are properly formatted with CIDR notation
  ipAddress: contains(ip, 'ipAddress') 
    ? ip.ipAddress 
    : (contains(ip, '/') 
      ? ip 
      : '${ip}/32')  // Add /32 mask if it's a single IP without mask
  action: contains(ip, 'action') ? ip.action : 'Allow'
  priority: contains(ip, 'priority') ? ip.priority : (100 + i)
  name: contains(ip, 'name') ? ip.name : 'Rule-${i}'
  description: contains(ip, 'description') ? ip.description : 'Allow access from IP'
}]
// Add a deny all rule
var denyAllRule = {
  ipAddress: '0.0.0.0/0'
  action: 'Deny'
  priority: 2147483647 // Highest possible priority number (lowest precedence)
  name: 'Deny-All'
  description: 'Deny all access by default'
}

// Create Web App
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: name
  location: location
  tags: tags
  kind: runtime == 'node' || runtime == 'python' ? 'app,linux' : 'app'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    virtualNetworkSubnetId: enablePublicAccessWithPerimeter ? null : integrationSubnet.id
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled' : (enablePublicGenAIAccess ? 'Enabled' : 'Disabled')
    siteConfig: {
      alwaysOn: true
      cors: {
        allowedOrigins: allowedOrigins
      }
      ipSecurityRestrictions: enablePublicAccessWithPerimeter ? [] : concat(formattedIpRules, [denyAllRule])
      // Set the appropriate runtime stack
      linuxFxVersion: runtime == 'python' ? 'PYTHON|${pythonVersion}' : runtime == 'node' ? 'NODE|18-lts' : runtime == 'java' ? 'JAVA|17-java17' : ''
      netFrameworkVersion: runtime == 'dotnet' ? 'v7.0' : null // Only set netFrameworkVersion for Windows/.NET apps
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
    type: 'azurewebapps'
    id:!enablePublicAccessWithPerimeter? privateEndpoint.id: ''
  }
]

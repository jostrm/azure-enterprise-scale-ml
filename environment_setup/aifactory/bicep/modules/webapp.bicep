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
param createPrivateEndpoint bool = true
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
param runtime string = 'python'  // Options: 'dotnet', 'node', 'python', 'java', 'dotnet'
param pythonVersion string = '3.11' // Used if runtime is 'python'
param subnetIntegrationName string  // Name of the subnet for VNet integration
param hostNameSslStates array = [] // 'Optional. Hostname SSL states are used to manage the SSL bindings for app\'s hostnames.')
param systemAssignedIdentity bool = true // Enables system assigned managed identity on the resource
param userAssignedIdentities object = {} // Optional. The ID(s) to assign to the resource.
@description('Optional. Site redundancy mode.')
@allowed([
  'ActiveActive'
  'Failover'
  'GeoRedundant'
  'Manual'
  'None'
])
param redundancyMode string = 'None'
param byoACEv3 bool = false // Optional, default is false. Set to true if you want to deploy ASE v3 instead of Multitenant App Service Plan.
param byoAceFullResourceId string = '' // Full resource ID of App Service Environment
param byoAceAppServicePlanRID string = '' // Full resource ID, default is empty. Set to the App Service Plan ID if you want to deploy ASE v3 instead of Multitenant App Service Plan.
//Note: No explicit VNet integration needed: ACEv3 is already deployed into its own subnet, so you don't need to specify virtualNetworkSubnetId separately.

// Use provided name or create one based on WebApp name
var servicePlanName = !empty(appServicePlanName) ? appServicePlanName : '${name}-plan'

// Get references to resources
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
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
// TODO: Linux or Windows
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

var identityType = systemAssignedIdentity 
  ? (!empty(userAssignedIdentities) ? 'SystemAssigned, UserAssigned' : 'SystemAssigned') 
  : (!empty(userAssignedIdentities) ? 'UserAssigned' : 'None')

var identity = identityType != 'None' ? {
  type: identityType
  userAssignedIdentities: !empty(userAssignedIdentities) ? userAssignedIdentities : null
} : null

// Create Web App
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: name
  location: location
  tags: tags
  kind: runtime == 'node' || runtime == 'python' || runtime == 'java'? 'app,linux' : 'app'
  identity: identity
  properties: {
    serverFarmId: byoACEv3? byoAceAppServicePlanRID: appServicePlan.id
    httpsOnly: true
    hostingEnvironmentProfile: !empty(byoAceFullResourceId) ? {
      id: byoAceFullResourceId
    } : null
    virtualNetworkSubnetId: enablePublicAccessWithPerimeter || byoACEv3 ? any(null) : integrationSubnet.id
    publicNetworkAccess: byoACEv3 ? 'Disabled' : (enablePublicAccessWithPerimeter || enablePublicGenAIAccess ? 'Enabled' : 'Disabled')
    siteConfig: {
      alwaysOn: true
      cors: {
        allowedOrigins: allowedOrigins
      }
      ipSecurityRestrictions: enablePublicAccessWithPerimeter || byoACEv3? [] : concat(formattedIpRules, [denyAllRule])
      // Set the appropriate runtime stack
      linuxFxVersion: runtime == 'python' ? 'PYTHON|${pythonVersion}' : runtime == 'node' ? 'NODE|18-lts' : runtime == 'java' ? 'JAVA|17-java17' : ''
      netFrameworkVersion: runtime == 'dotnet' ? 'v7.0' : null // Only set netFrameworkVersion for Windows/.NET apps
      appSettings: concat(appSettings, !empty(applicationInsightsName) ? [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: (!empty(applicationInsightsName))? appInsights.properties.ConnectionString: ''
        }
        {
          name: 'ApplicationInsightsAgent_EXTENSION_VERSION'
          value: '~2'
        }
      ] : [])
    }
    hostNameSslStates: hostNameSslStates
    redundancyMode: redundancyMode
  }
}

// Create private endpoint
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if(createPrivateEndpoint && !byoACEv3) {
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
    name: (createPrivateEndpoint && !byoACEv3)? privateEndpoint.name: ''
    type: 'azurewebapps'
    id:(createPrivateEndpoint && !byoACEv3)? privateEndpoint.id: ''
  }
]

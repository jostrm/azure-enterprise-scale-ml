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
@allowed([
  'dotnet'
  'node'
  'python'
  'java'
])
param runtime string = 'python'  // Options: 'dotnet', 'node', 'python', 'java'
@allowed([
  '3.7'
  '3.8'
  '3.9'
  '3.10'
  '3.11'
  '3.12'
  // Node.js versions
  '18-lts'
  '20-lts'
  // Java LTS versions
  '8'
  '11'
  '17'
  '21'
  // .NET versions
  'v4.8'
  'v6.0'
  'v7.0'
  'v8.0'
])
param runtimeVersion string = '3.11' // Used if runtime is 'python'
param subnetIntegrationName string  // Name of the subnet for VNet integration
param hostNameSslStatesIn array = [] // 'Optional. Hostname SSL states are used to manage the SSL bindings for app\'s hostnames.')
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
param alwaysOn bool = true // Optional, default is true. Set to false if you want to disable Always On for the Function App.
param byoASEv3 bool = false // Optional, default is false. Set to true if you want to deploy ASE v3 instead of Multitenant App Service Plan.
param byoAseFullResourceId string = '' // Full resource ID of App Service Environment
param byoAseAppServicePlanRID string = '' // Full resource ID, default is empty. Set to the App Service Plan ID if you want to deploy ASE v3 instead of Multitenant App Service Plan.
//Note: No explicit VNet integration needed: ACEv3 is already deployed into its own subnet, so you don't need to specify virtualNetworkSubnetId separately.

// Use provided name or create one based on WebApp name
var servicePlanName = !empty(appServicePlanName) ? appServicePlanName : '${name}-plan'
var byoACE3Intenal = !empty(byoAseFullResourceId)
var aseName = last(split(byoAseFullResourceId, '/')) // Split the resource ID by '/' and take the last segment

var hostNameSslStatesDefault= !empty(hostNameSslStatesIn) ? hostNameSslStatesIn : [
  {
    name: '${name}.azurewebsites.net'
    hostType: 'Standard'
    sslState: 'Disabled'
  }
]

var hostNameSslStates = byoASEv3 ? [
  {
    name: '${name}.${aseName}.appserviceenvironment.net'
    sslState: 'Disabled'
    hostType: 'Standard'
  }
  {
    name: '${name}.scm.${aseName}.appserviceenvironment.net'
    sslState: 'Disabled'
    hostType: 'Repository'
  }
] : hostNameSslStatesDefault


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
resource appServicePlan 'Microsoft.Web/serverfarms@2024-11-01' = if (empty(byoAseAppServicePlanRID)) {
  name: servicePlanName
  location: location
  tags: tags
  sku: {
    name: 'I1v2'
    tier: 'IsolatedV2'
    size: 'I1v2'
    family: 'Iv2'
    capacity: 1
  }
  kind: runtime == 'node' || runtime == 'python' || runtime == 'java' ? 'linux' : 'windows' // Linux Web app OR Windows Web app
  properties: {
    reserved: runtime == 'node' || runtime == 'python' // Set to true for Linux runtimes, otherwise Windows (dotnet, java)
    hostingEnvironmentProfile: byoASEv3 && !empty(byoAseFullResourceId)? {
      id: byoAseFullResourceId
    } : null
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

// Reference existing ASE App Service Plan if provided
resource existingAppServicePlan 'Microsoft.Web/serverfarms@2024-11-01' existing = if (!empty(byoAseAppServicePlanRID) && byoASEv3) {
  name: last(split(byoAseAppServicePlanRID, '/'))
  scope: resourceGroup(split(byoAseAppServicePlanRID, '/')[2], split(byoAseAppServicePlanRID, '/')[4])
}

// Create Web App
resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: name
  location: location
  tags: tags
  kind: runtime == 'node' || runtime == 'python' || runtime == 'java'? 'app,linux' : 'app' // Linux Web app OR Windows Web app
  identity: identity
  properties: {
    serverFarmId: !empty(byoAseAppServicePlanRID) && byoASEv3? existingAppServicePlan.id : appServicePlan.id
    httpsOnly: true
    hostingEnvironmentProfile: !empty(byoAseFullResourceId) && byoASEv3 ? {
      id: byoAseFullResourceId
    } : null
    virtualNetworkSubnetId: enablePublicAccessWithPerimeter || byoASEv3 ? any(null) : integrationSubnet.id
    publicNetworkAccess: byoASEv3 ? 'Disabled' : (enablePublicAccessWithPerimeter || enablePublicGenAIAccess ? 'Enabled' : 'Disabled')
    siteConfig: {
      alwaysOn: alwaysOn
      cors: {
        allowedOrigins: allowedOrigins
      }
      ipSecurityRestrictions: enablePublicAccessWithPerimeter || byoASEv3? [] : concat(formattedIpRules, [denyAllRule])
      // Set the appropriate runtime stack
      linuxFxVersion: runtime == 'python' ? 'PYTHON|${runtimeVersion}' : runtime == 'node' ? 'NODE|${runtimeVersion}' : runtime == 'java' ? 'JAVA|${runtimeVersion}-java${runtimeVersion}' : ''
      netFrameworkVersion: runtime == 'dotnet' ? runtimeVersion : null
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
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if(createPrivateEndpoint && !byoASEv3) {
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
    name: (createPrivateEndpoint && !byoASEv3)? privateEndpoint.name: ''
    type: 'azurewebapps'
    id:(createPrivateEndpoint && !byoASEv3)? webApp.id: ''
  }
]

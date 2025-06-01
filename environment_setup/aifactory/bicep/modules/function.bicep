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
param createPrivateEndpoint bool = true
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
param runtime string = 'python'  // Options: 'node', 'dotnet', 'java', 'python'
param pythonVersion string = '3.11' // Used if runtime is 'python'
param subnetIntegrationName string
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

// Use provided name or create one based on Function name
var servicePlanName = !empty(appServicePlanName) ? appServicePlanName : '${name}-plan'

// Get references to resources
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = {
  name: storageAccountName
}

// Get subnet reference for VNet integration
resource integrationSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  name: '${vnetName}/${subnetIntegrationName}'
  scope: resourceGroup(vnetResourceGroupName)
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
    reserved: runtime == 'node' || runtime == 'python' // Set to true for Linux runtimes, otherwuise Windows (dotnet, java)
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


// Create Function App
resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: name
  location: location
  tags: tags
  kind: runtime == 'node' || runtime == 'python' || runtime == 'java'? 'functionapp,linux' : 'functionapp'
  identity: identity
  properties: {
    //serverFarmId: byoACEv3? byoAceAppServicePlanRID: appServicePlan.id
    serverFarmId: appServicePlan.id
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
      linuxFxVersion: runtime == 'python' ? 'PYTHON|${pythonVersion}' : runtime == 'node' ? 'NODE|18-lts' : runtime == 'java' ? 'JAVA|17' : ''
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
      ], 
      // Only add content settings for non-Python runtimes
      runtime != 'python' ? [
        {
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: toLower(name)
        }
      ] : [],
      // Add Python-specific app settings
      runtime == 'python' ? [
        {
          name: 'ENABLE_ORYX_BUILD'
          value: 'true'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ] : [],
      [
        {
          name: 'WEBSITE_VNET_ROUTE_ALL'
          value: '1'
        }
      ],
      appSettings, 
      !empty(applicationInsightsName) ? [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ] : [])
    }
    hostNameSslStates: hostNameSslStates
    redundancyMode: redundancyMode
  }
}

// Create private endpoint
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if(createPrivateEndpoint && !byoACEv3) {
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
    name: (createPrivateEndpoint && !byoACEv3)? privateEndpoint.name : ''
    type: 'azurewebapps'
    id: (createPrivateEndpoint && !byoACEv3)? functionApp.id : ''
  }
]

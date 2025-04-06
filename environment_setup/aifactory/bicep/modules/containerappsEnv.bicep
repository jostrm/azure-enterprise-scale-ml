metadata description = 'Creates an Azure Container Apps environment.'
param name string
param location string
param tags object

@description('Name of the Application Insights resource')
param applicationInsightsName string = ''

@description('Specifies if Dapr is enabled')
param daprEnabled bool = false

@description('Name of the Log Analytics workspace')
param logAnalyticsWorkspaceName string
param logAnalyticsWorkspaceRG string
param vnetName string
param vnetResourceGroupName string
param subnetNamePend string = ''
param subnetAcaDedicatedName string
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetAcaDedicatedName
  parent: vnet
}

//  Provided subnet must have a size of at least /23 or larger.
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
    daprAIInstrumentationKey: daprEnabled && !empty(applicationInsightsName) ? applicationInsights.properties.InstrumentationKey : ''
    daprAIConnectionString: daprEnabled && !empty(applicationInsightsName) ? applicationInsights.properties.ConnectionString : ''
    vnetConfiguration: {
      infrastructureSubnetId: subnet.id
      internal: true //enablePublicAccessWithPerimeter? false:true
    }

  }
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: logAnalyticsWorkspaceName
  scope: resourceGroup(logAnalyticsWorkspaceRG)
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = if (daprEnabled && !empty(applicationInsightsName)) {
  name: applicationInsightsName
}

output defaultDomain string = containerAppsEnvironment.properties.defaultDomain
output id string = containerAppsEnvironment.id
output name string = containerAppsEnvironment.name

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
param wlProfileDedicatedName string = 'D4'
param wlProfileGPUConsumptionName string = 'Consumption-GPU-NC24-A100'
param wlMinCountServerless int = 0
param wlMinCountDedicated int = 1
param wlMaxCount int = 5

// TODO: Expose these parameters to the user
param wlProfileDedicatedGPUName string = 'Dedicated-GPU-NC24-A100'
param wlMinCountDedicatedGPU int = 1
param wlMaxCountDedicatedGPU int = 5

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetAcaDedicatedName
  parent: vnet
}
resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

//  Provided subnet must have a size of at least /23 or larger.
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
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
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
      {
        name: wlProfileDedicatedName
        workloadProfileType: wlProfileDedicatedName
        minimumCount: wlMinCountDedicated
        maximumCount: wlMaxCount
      }
      
    ]

    vnetConfiguration: {
      infrastructureSubnetId: enablePublicAccessWithPerimeter ? null : subnet.id
      internal: enablePublicAccessWithPerimeter? false:true
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

resource pendAca 'Microsoft.Network/privateEndpoints@2022-01-01' = if(enablePublicAccessWithPerimeter==false) {
  name: 'pend-acaenv-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-aca-${name}'
        properties: {
          privateLinkServiceId: containerAppsEnvironment.id
          groupIds: [
            'managedEnvironments'
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

output defaultDomain string = containerAppsEnvironment.properties.defaultDomain
output id string = containerAppsEnvironment.id
output name string = containerAppsEnvironment.name
output dnsConfig array = [
  {
    name: !enablePublicAccessWithPerimeter? pendAca.name: ''
    type: 'azurecontainerapps'
    id:!enablePublicAccessWithPerimeter? pendAca.id: ''
  }
]


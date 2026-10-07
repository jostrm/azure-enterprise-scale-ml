// Private Link for a VNet-injected Azure Databricks workspace (classic compute plane).
// - databricks_ui_api in the workspace VNet serves both front-end (UI/REST) and back-end
//   (secure cluster connectivity relay) traffic. Without it, a workspace with
//   publicNetworkAccess 'Disabled' and requiredNsgRules 'NoAzureDatabricksRules' is unreachable
//   and its clusters cannot reach the control plane.
// - browser_authentication carries the regional SSO callback (one per region per private DNS zone).
// Deploys against an existing workspace, so it also repairs workspaces created without endpoints.
// Docs: https://learn.microsoft.com/azure/databricks/security/network/classic/private-link-standard

@description('Existing Azure Databricks workspace name in this resource group.')
param workspaceName string

@description('Location of the private endpoints (same region as the workspace).')
param location string

param tags object = {}

@description('Subnet resource ID for the private endpoints, in the workspace VNet (or a VNet reachable from it).')
param subnetResourceId string

@description('Existing privatelink.azuredatabricks.net zone ID. Empty when central DNS policy (DeployIfNotExists) creates the zone groups.')
param privateDnsZoneResourceId string = ''

@description('Create the regional browser_authentication endpoint. Use exactly one per region per private DNS zone.')
param enableBrowserAuthentication bool = true

param privateEndpointName string = '${workspaceName}-pend'
param browserAuthenticationPrivateEndpointName string = '${workspaceName}-auth-pend'

resource workspace 'Microsoft.Databricks/workspaces@2024-05-01' existing = {
  name: workspaceName
}

resource uiApi 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetResourceId
    }
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: workspace.id
          groupIds: [
            'databricks_ui_api'
          ]
        }
      }
    ]
  }
}

resource uiApiDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!empty(privateDnsZoneResourceId)) {
  parent: uiApi
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'azuredatabricks'
        properties: {
          privateDnsZoneId: privateDnsZoneResourceId
        }
      }
    ]
  }
}

// Databricks serializes private endpoint connection updates per workspace, so create this one second.
resource browserAuthentication 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enableBrowserAuthentication) {
  name: browserAuthenticationPrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetResourceId
    }
    customNetworkInterfaceName: '${browserAuthenticationPrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: browserAuthenticationPrivateEndpointName
        properties: {
          privateLinkServiceId: workspace.id
          groupIds: [
            'browser_authentication'
          ]
        }
      }
    ]
  }
  dependsOn: [
    uiApi
    uiApiDns
  ]
}

resource browserAuthenticationDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (enableBrowserAuthentication && !empty(privateDnsZoneResourceId)) {
  parent: browserAuthentication
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'azuredatabricks'
        properties: {
          privateDnsZoneId: privateDnsZoneResourceId
        }
      }
    ]
  }
}

output uiApiPrivateEndpointId string = uiApi.id
output browserAuthenticationPrivateEndpointId string = enableBrowserAuthentication ? browserAuthentication.id : ''

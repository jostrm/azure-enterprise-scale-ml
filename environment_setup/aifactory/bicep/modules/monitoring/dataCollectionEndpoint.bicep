// ============================================================================
// Data Collection Endpoint (DCE) Module
// ============================================================================
// This module creates a Data Collection Endpoint for Azure Monitor Agent
// private link scenarios

@description('Name of the Data Collection Endpoint')
param dceName string

@description('Location for the DCE resource')
param location string

@description('Tags to apply to the DCE resource')
param tags object = {}

@description('Description of the Data Collection Endpoint')
param dceDescription string = 'Data Collection Endpoint for Azure Monitor Agent private link'

@description('Kind of the Data Collection Endpoint')
@allowed(['Linux', 'Windows'])
param kind string = 'Linux'

@description('Enable public network access')
param enablePublicNetworkAccess bool = false

// Create the Data Collection Endpoint
resource dataCollectionEndpoint 'Microsoft.Insights/dataCollectionEndpoints@2022-06-01' = {
  name: dceName
  location: location
  tags: tags
  kind: kind
  properties: {
    description: dceDescription
    networkAcls: {
      publicNetworkAccess: enablePublicNetworkAccess ? 'Enabled' : 'Disabled'
    }
  }
}

// Outputs
output dceId string = dataCollectionEndpoint.id
output dceName string = dataCollectionEndpoint.name
output dceResourceId string = dataCollectionEndpoint.id
output logsIngestionEndpoint string = dataCollectionEndpoint.properties.logsIngestion.endpoint
output metricsIngestionEndpoint string = dataCollectionEndpoint.properties.metricsIngestion.endpoint

// ============================================================================
// AI Factory - Cross-environment dashboard
// ============================================================================
// The project pipeline discovers the shared and project resources, merges them
// with the persisted inventory, and supplies the deterministic tile layout.

@description('Azure region where the dashboard resource is stored.')
param location string

@description('Stable Azure Portal dashboard resource name.')
param dashboardName string

@description('Dashboard title shown in Azure Portal.')
param dashboardTitle string = 'AI Factory'

@description('Complete Azure Portal dashboard parts generated from the reconciled inventory.')
param dashboardParts array

@description('Hub/shared and DEV/STAGE/PROD inventory persisted for the next incremental update.')
param aifactoryInventory object

@description('Tags applied to the dashboard resource.')
param tags object = {}

resource factoryDashboard 'Microsoft.Portal/dashboards@2020-09-01-preview' = {
  name: dashboardName
  location: location
  tags: union(tags, {
    'hidden-title': dashboardTitle
    'AI-Factory-Dashboard': 'true'
  })
  properties: {
    lenses: [
      {
        order: 0
        parts: dashboardParts
      }
    ]
    metadata: {
      aifactoryInventory: aifactoryInventory
      model: {
        timeRange: {
          value: {
            relative: {
              duration: 30
              timeUnit: 2
            }
          }
          type: 'MsPortalFx.Composition.Configuration.ValueTypes.TimeRange'
        }
        filterLocale: {
          value: 'en-us'
        }
        filters: {
          value: {
            MsPortalFx_TimeRange: {
              model: {
                format: 'utc'
                granularity: 'auto'
                relative: '30d'
              }
              displayCache: {
                name: 'UTC Time'
                value: 'Past 30 days'
              }
              filteredPartIds: []
            }
          }
        }
      }
    }
  }
}

output dashboardId string = factoryDashboard.id
output dashboardName string = factoryDashboard.name
output dashboardUrl string = 'https://portal.azure.com/#@${tenant().tenantId}/dashboard/arm${factoryDashboard.id}'

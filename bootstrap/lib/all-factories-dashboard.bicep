targetScope = 'resourceGroup'

@description('Dashboard storage location in the reviewed reusable connectivity hub, never a factory common RG.')
param location string = resourceGroup().location

@minLength(1)
@maxLength(100)
@description('Explicitly reviewed subscription UUIDs. This selection is not derived from the current account or from factory naming.')
param selectedSubscriptionIds array

@description('Reviewed source fingerprint recorded by the retained hub deployment helper.')
param sourcePayloadSha256 string

var introduction = '''
# All AI Factories

Open **Azure Cost Analysis** below for current billing data (subject to billing ingestion delay). Choose **Actual cost**, **This month**, and group by **Resource group**. For a full-month forecast, filter the exact resource groups, remove grouping, then enable **Forecast** where supported. Forecast does not support grouping. Read the actual amount, full-month forecast and billing currency from that view; unavailable forecasts are not zero.

**Dev / Stage / Prod:** Azure updates resource-group cost data dynamically within each selected subscription. It does not infer logical factories or normalize environment names; legacy Azure names may use `test` for Stage. Explicitly filter the relevant resource groups before interpreting a factory/environment total.

**Limits:** a subscription total is **not a factories-only total**. Hub/connectivity, bootstrap, unowned and managed resource-group charges remain separate unless explicitly attributed. Do not sum overlapping scopes, mix currencies or treat these links as a combined factories forecast. Arbitrary selected subscriptions are not a single Cost Management scope.

This native dashboard uses supported Markdown parts and Cost Analysis drillthrough. It cannot run custom server code, call a local API, or reproduce the shared Python service's attribution. Factory/environment combined numerical totals require that service's supported client, or a separately reviewed Azure billing/management-group view with equivalent scope and filters. No financial numbers are embedded here.
'''

var subscriptionParts = [for (subscriptionId, index) in selectedSubscriptionIds: {
  position: {
    x: (index % 2) * 12
    y: 7 + (index / 2) * 3
    colSpan: 12
    rowSpan: 3
  }
  metadata: {
    type: 'Extension/HubsExtension/PartType/MarkdownPart'
    inputs: []
    settings: {
      content: {
        settings: {
          title: 'Selected subscription'
          subtitle: subscriptionId
          content: '[Open Cost Analysis — ${subscriptionId}](https://portal.azure.com/@${tenant().tenantId}/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/${uriComponent('/subscriptions/${subscriptionId}')})\n\nGroup actual costs by **Resource group** and filter before reading factory or environment amounts. For forecast, keep the filters but remove grouping. Requires cost read access to this subscription. This view includes non-factory charges by default.'
          markdownSource: 1
        }
      }
    }
  }
}]

var dashboardTags = {
    'hidden-title': 'All AI Factories'
    'aifactory.dashboard': 'all-ai-factories-v1'
    'aifactory.scope': 'connectivity-hub'
}

var dashboardProperties = {
    lenses: [
      {
        order: 0
        parts: concat([
          {
            position: {
              x: 0
              y: 0
              colSpan: 24
              rowSpan: 7
            }
            metadata: {
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              inputs: []
              settings: {
                content: {
                  settings: {
                    title: 'All AI Factories'
                    subtitle: 'Native Azure Cost Management — explicit selected subscriptions'
                    content: introduction
                    markdownSource: 1
                  }
                }
              }
            }
          }
        ], subscriptionParts)
      }
    ]
    metadata: {
      allAiFactories: {
        schemaVersion: 1
        hubResourceGroupId: toLower(resourceGroup().id)
        selectedSubscriptionIds: selectedSubscriptionIds
        sourcePayloadSha256: sourcePayloadSha256
        presentation: 'native-cost-analysis-drillthrough'
        numericAggregationSupported: false
      }
  }
}

resource dashboard 'Microsoft.Portal/dashboards@2020-09-01-preview' = {
  name: 'all-ai-factories'
  location: location
  tags: dashboardTags
  properties: dashboardProperties
}

output dashboardId string = dashboard.id
output dashboardUrl string = 'https://portal.azure.com/#@${tenant().tenantId}/dashboard/arm${dashboard.id}'
output desiredDashboard object = {
  location: location
  tags: dashboardTags
  properties: dashboardProperties
}

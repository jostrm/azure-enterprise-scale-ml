// =============================================================================
// logicApp.throttle.bicep
// Consumption Logic App that, when triggered (by an Action Group from a budget
// or token-metric alert), cuts network access to every Azure AI Foundry /
// Cognitive Services account in the target scope:
//   - PATCH publicNetworkAccess=Disabled + networkAcls.defaultAction=Deny
//   - Reject every APPROVED private endpoint connection
// Uses the Logic App system-assigned managed identity to call ARM REST.
// =============================================================================

@description('Location for the Logic App.')
param location string = resourceGroup().location

@description('Name of the Logic App.')
param logicAppName string

@description('The ARM resource id of the scope to enumerate Cognitive Services accounts in. Either a subscription id path or a resource group id path. Example: /subscriptions/xxxx or /subscriptions/xxxx/resourceGroups/my-rg')
param scopeResourceId string

@description('API version used for Microsoft.CognitiveServices/accounts REST calls.')
param cognitiveApiVersion string = '2025-06-01'

@description('Optional. Log Analytics workspace resource id (the workspace behind your Application Insights) to send Logic App run logs/metrics to. Leave empty to skip diagnostics.')
param logAnalyticsWorkspaceResourceId string = ''

@description('Tags applied to the Logic App.')
param tags object = {}

// Use environment() so this works across Azure clouds (Public, Gov, China).
var mgmtRaw = environment().resourceManager
var mgmtLen = length(mgmtRaw)
var managementBase = endsWith(mgmtRaw, '/') ? substring(mgmtRaw, 0, max(0, mgmtLen - 1)) : mgmtRaw
var listAccountsUri = '${managementBase}${scopeResourceId}/providers/Microsoft.CognitiveServices/accounts?api-version=${cognitiveApiVersion}'

resource logicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: logicAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      parameters: {}
      triggers: {
        // Called by the Action Group (common alert schema) or manually.
        manual: {
          type: 'Request'
          kind: 'Http'
          inputs: {
            schema: {}
          }
        }
      }
      actions: {
        List_cognitive_accounts: {
          type: 'Http'
          inputs: {
            method: 'GET'
            uri: listAccountsUri
            authentication: {
              type: 'ManagedServiceIdentity'
              audience: managementBase
            }
          }
          runAfter: {}
        }
        For_each_account: {
          type: 'Foreach'
          foreach: '@body(\'List_cognitive_accounts\')?[\'value\']'
          runAfter: {
            List_cognitive_accounts: [ 'Succeeded' ]
          }
          actions: {
            Block_public_access: {
              type: 'Http'
              inputs: {
                method: 'PATCH'
                uri: '${managementBase}@{items(\'For_each_account\')?[\'id\']}?api-version=${cognitiveApiVersion}'
                authentication: {
                  type: 'ManagedServiceIdentity'
                  audience: managementBase
                }
                body: {
                  properties: {
                    publicNetworkAccess: 'Disabled'
                    networkAcls: {
                      defaultAction: 'Deny'
                    }
                  }
                }
              }
              runAfter: {}
            }
            List_pe_connections: {
              type: 'Http'
              inputs: {
                method: 'GET'
                uri: '${managementBase}@{items(\'For_each_account\')?[\'id\']}/privateEndpointConnections?api-version=${cognitiveApiVersion}'
                authentication: {
                  type: 'ManagedServiceIdentity'
                  audience: managementBase
                }
              }
              runAfter: {
                Block_public_access: [ 'Succeeded' ]
              }
            }
            For_each_pe_connection: {
              type: 'Foreach'
              foreach: '@body(\'List_pe_connections\')?[\'value\']'
              runAfter: {
                List_pe_connections: [ 'Succeeded' ]
              }
              actions: {
                If_approved_reject: {
                  type: 'If'
                  expression: {
                    equals: [
                      '@items(\'For_each_pe_connection\')?[\'properties\']?[\'privateLinkServiceConnectionState\']?[\'status\']'
                      'Approved'
                    ]
                  }
                  actions: {
                    Reject_pe_connection: {
                      type: 'Http'
                      inputs: {
                        method: 'PUT'
                        uri: '${managementBase}@{items(\'For_each_pe_connection\')?[\'id\']}?api-version=${cognitiveApiVersion}'
                        authentication: {
                          type: 'ManagedServiceIdentity'
                          audience: managementBase
                        }
                        body: {
                          properties: {
                            privateLinkServiceConnectionState: {
                              status: 'Rejected'
                              description: 'Throttled by esml aimodel-throttling (budget/token cap exceeded)'
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
      outputs: {}
    }
  }
}

// Optional: send Logic App workflow run logs + metrics to the Log Analytics
// workspace behind your Application Insights (pre-req) for observability.
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceResourceId)) {
  name: 'throttle-logicapp-diag'
  scope: logicApp
  properties: {
    workspaceId: logAnalyticsWorkspaceResourceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

@description('Principal id of the Logic App system-assigned managed identity (grant it Cognitive Services Contributor on the scope).')
output principalId string = logicApp.identity.principalId

@description('Resource id of the Logic App.')
output logicAppId string = logicApp.id

@description('Name of the Logic App.')
output logicAppName string = logicApp.name

@description('Resource id of the manual trigger (for the Action Group logicAppReceiver).')
output triggerResourceId string = '${logicApp.id}/triggers/manual'

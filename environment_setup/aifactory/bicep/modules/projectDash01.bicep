// ============================================================================
// AI Factory - Project Dashboard (projectDash01.bicep)
// ============================================================================
// This module creates a shared Azure dashboard for the AI Factory project
// providing quick access to resources and services in the project resource group

// ============================================================================
// PARAMETERS
// ============================================================================

@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

@description('Random salt for unique naming')
param aifactorySalt10char string
param randomValue string

@description('AI Factory suffix for resource groups')
param aifactorySuffixRG string

@description('Common resource group name prefix')
param commonRGNamePrefix string = ''

@description('User Admins OID list')
param technicalAdminsObjectID string = ''

@description('User Admins EMAIL list')
param technicalAdminsEmail string = ''

@description('Common resource group name')
param commonResourceGroupName string

@description('Subscription ID for dev/test/prod')
param subscriptionIdDevTestProd string

@description('GenAI subnet ID')
param genaiSubnetId string

@description('AKS subnet ID')
param aksSubnetId string

@description('ACA subnet ID')
param acaSubnetId string

@description('Project prefix for naming')
param projectPrefix string = 'esml-'

@description('Project suffix for naming')
param projectSuffix string = '-rg'

@description('Azure location')
param location string

@description('Resource tags')
param tags object = {}

// ============================================================================
// MODULE: NAMING CONVENTION
// ============================================================================

module namingConvention './common/CmnAIfactoryNaming.bicep' = {
  name: 'projectDash-naming-${uniqueString(resourceGroup().id)}'
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue: randomValue
    aifactorySalt10char: aifactorySalt10char
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroupName
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    technicalAdminsEmail: technicalAdminsEmail
    technicalAdminsObjectID: technicalAdminsObjectID
    acaSubnetId: acaSubnetId
    aksSubnetId: aksSubnetId
    genaiSubnetId: genaiSubnetId
  }
}

// Get naming convention outputs
var namingOutputs = namingConvention.outputs.namingConvention

// ============================================================================
// VARIABLES
// ============================================================================

// Construct target resource group name (same as in 01-foundation.bicep)
var projectName = 'prj${projectNumber}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Dashboard name using static calculation
var dashboardName = 'dash-prj${projectNumber}-${env}-${locationSuffix}'

// Resource group resource ID for pinning
var resourceGroupResourceId = '/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}'

// AI Foundry Hub URL construction
var aiFoundryUrl = 'https://ai.azure.com/build/overview?tid=${tenant().tenantId}&wsid=/subscriptions/${subscriptionIdDevTestProd}/resourcegroups/${targetResourceGroup}/providers/Microsoft.MachineLearningServices/workspaces/${namingOutputs.aifV1HubName}'

// ============================================================================
// DASHBOARD RESOURCE
// ============================================================================

// Microsoft.Portal/dashboards@2025-04-01-preview
// 
resource projectDashboard 'Microsoft.Portal/dashboards@2020-09-01-preview' = {
  name: dashboardName
  location: location
  tags: tags
  properties: {
    lenses: [
      {
        order: 0
        parts: [
          // Header Markdown (4x3)
          {
            position: {
              x: 0
              y: 0
              colSpan: 4
              rowSpan: 3
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '# Project Dashboard\n\n**Project:** ${namingOutputs.projectName} - ${env}\n\n**Environment:** ${toUpper(env)}\n\n**Location:** ${locationSuffix}'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Resource Group Tile (2x2)
          {
            position: {
              x: 0
              y: 3
              colSpan: 2
              rowSpan: 2
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '## 📁 Resource Group\n\n[Open Resource Group](https://portal.azure.com/#@${tenant().tenantId}/resource${resourceGroupResourceId})\n\n**Name:** ${targetResourceGroup}\n\n**Location:** ${location}'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Cost Analysis Markdown Tile (2x2) - Using markdown due to API limitations
          {
            position: {
              x: 2
              y: 3
              colSpan: 2
              rowSpan: 2
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '## 💰 Cost Analysis\n\n[Open Cost Analysis](https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/costanalysis/scope/${replace(resourceGroupResourceId, '/', '%2F')})\n\nView spending trends and optimize costs for this project.'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Service Shortcuts Row Header (4x1)
          {
            position: {
              x: 0
              y: 5
              colSpan: 4
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '### 🔗 Quick Access to Services'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Azure OpenAI Service Link (1x1)
          {
            position: {
              x: 0
              y: 6
              colSpan: 1
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '🧠 [Azure OpenAI](https://portal.azure.com/#@${tenant().tenantId}/resource/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}/providers/Microsoft.CognitiveServices/accounts/${namingOutputs.aoaiName}/overview)'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // AI Search Service Link (1x1)
          {
            position: {
              x: 1
              y: 6
              colSpan: 1
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '🔍 [AI Search](https://portal.azure.com/#@${tenant().tenantId}/resource/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Search/searchServices/${namingOutputs.safeNameAISearch}/overview)'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Key Vault Service Link (1x1)
          {
            position: {
              x: 2
              y: 6
              colSpan: 1
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '🔐 [Key Vault](https://portal.azure.com/#@${tenant().tenantId}/resource/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}/providers/Microsoft.KeyVault/vaults/${namingOutputs.keyvaultName}/overview)'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Storage Account Service Link (1x1)
          {
            position: {
              x: 3
              y: 6
              colSpan: 1
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '💾 [Storage](https://portal.azure.com/#@${tenant().tenantId}/resource/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}/providers/Microsoft.Storage/storageAccounts/${namingOutputs.storageAccount1001Name}/overview)'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // AI Foundry Hub Shortcut (4x1 Markdown)
          {
            position: {
              x: 0
              y: 7
              colSpan: 4
              rowSpan: 1
            }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '<img width=\'24\' src=\'https://ai.azure.com/assets/aistudio-af17733a.svg\'/> <a href=\'${aiFoundryUrl}\' target=\'_blank\'>AI Foundry (${namingOutputs.aifV1HubName})</a>'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
        ]
      }
    ]
    metadata: {
      model: {
        timeRange: {
          value: {
            relative: {
              duration: 24
              timeUnit: 1
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
                relative: '24h'
              }
              displayCache: {
                name: 'UTC Time'
                value: 'Past 24 hours'
              }
              filteredPartIds: []
            }
          }
        }
      }
    }
  }
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Dashboard resource ID')
output dashboardId string = projectDashboard.id

@description('Dashboard name')
output dashboardName string = dashboardName

@description('Dashboard URL')
output dashboardUrl string = 'https://portal.azure.com/#@${tenant().tenantId}/dashboard/arm${projectDashboard.id}'

@description('AI Foundry URL')
output aiFoundryUrl string = aiFoundryUrl

@description('Project name from naming convention')
output projectName string = namingOutputs.projectName

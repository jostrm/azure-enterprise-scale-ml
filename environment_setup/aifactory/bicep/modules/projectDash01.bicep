// ============================================================================
// AI Factory - Project Dashboard (projectDash01.bicep)
// ============================================================================
// Creates a rich Azure Portal dashboard for an AI Factory GenAI project with:
//   - Full-width H1 banner (project number, environment, region)
//   - Resource Group resources list tile      (left half)
//   - Cost Analysis tile                       (right half — to the right of the RG)
//   - 4 small 1x1 quick-access shortcut tiles  (AI Foundry project, Storage, Key Vault, AI Search)
//
// Layout (12-column grid):
//   Row 0-1:  [ Banner H1 — Project {N} · {ENV} · {REGION} ]                    (colSpan 12, rowSpan 2)
//   Row 2-9:  [ Resources (RG) ][ Cost Analysis ]                                (6 + 6)
//   Row 10:   [Foundry][Storage][KeyVault][AISearch]                             (1 + 1 + 1 + 1)

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

@description('Whether AI Foundry was added (addAIFoundry=true) - affects V2 account naming')
param addAIFoundry bool = false

@description('Resource tags')
param tags object = {}

// ── Project metadata (shown in banner — defaults to placeholder "-") ─────────
@description('Team members (comma-separated names) — banner placeholder')
param projectTeam string = '-'

@description('Project owner name — banner placeholder')
param projectOwner string = '-'

@description('Monthly budget in $ — banner placeholder')
param projectBudget string = 'TBA'

@description('Use case description — banner placeholder')
param projectUseCase string = 'TBA'

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

var namingOutputs = namingConvention.outputs.namingConvention

// ============================================================================
// VARIABLES
// ============================================================================

var projectLabel = 'prj${projectNumber}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectLabel, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

var dashboardName = 'dash-prj${projectNumber}-${env}-${locationSuffix}'
var dashboardTitle  = 'Project${projectNumber} - ${toUpper(env)} (GenAI)'

// Resource IDs — constructed from naming convention (no existing references needed)
var rgResourceId           = '/subscriptions/${subscriptionIdDevTestProd}/resourceGroups/${targetResourceGroup}'
var aifV2AccountName       = addAIFoundry ? namingOutputs.aifV2NameAdd : namingOutputs.aifV2Name
var aifV2ProjectName       = addAIFoundry ? namingOutputs.aifV2PrjNameAdd : namingOutputs.aifV2PrjName
var foundryAccountResId    = '${rgResourceId}/providers/Microsoft.CognitiveServices/accounts/${aifV2AccountName}'
var keyvaultResId          = '${rgResourceId}/providers/Microsoft.KeyVault/vaults/${namingOutputs.keyvaultName}'
var storage2001ResId       = '${rgResourceId}/providers/Microsoft.Storage/storageAccounts/${namingOutputs.storageAccount2001Name}'
var aiSearchResId          = '${rgResourceId}/providers/Microsoft.Search/searchServices/${namingOutputs.safeNameAISearch}'

// Portal deep links
var aiFoundryProjectUrl    = 'https://ai.azure.com/build/overview?tid=${tenant().tenantId}&wsid=${foundryAccountResId}/projects/${aifV2ProjectName}'
var costAnalysisUrl        = 'https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/costanalysis/scope/${replace(rgResourceId, '/', '%2F')}'
var rgPortalUrl            = 'https://portal.azure.com/#@${tenant().tenantId}/resource${rgResourceId}'

// ============================================================================
// DASHBOARD RESOURCE
// ============================================================================

resource projectDashboard 'Microsoft.Portal/dashboards@2020-09-01-preview' = {
  name: dashboardName
  location: location
  tags: union(tags, { 'hidden-title': dashboardTitle })
  properties: {
    lenses: [
      {
        order: 0
        parts: [
          // ── ROW 0-1: Full-width H1 banner (project · env · region) ────────────
          {
            position: { x: 0, y: 0, colSpan: 12, rowSpan: 2 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '# Project ${projectNumber} - ${toUpper(env)} (GenAI)\n\n**Team:** ${projectTeam}\n\n**Owner:** ${projectOwner}\n\n**Budget:** ${projectBudget} $/mon\n\n**Use case:** ${projectUseCase}\n\n[🗂️ Resource Group](${rgPortalUrl}) \u{2003}|\u{2003} [🤖 AI Foundry](${aiFoundryProjectUrl}) \u{2003}|\u{2003} [💰 Cost Analysis](${costAnalysisUrl})'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }

          // ── ROW 2-9: Resources list — project resource group (left half) ──────
          {
            position: { x: 0, y: 2, colSpan: 6, rowSpan: 8 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: rgResourceId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'ResourceGroup'
              }
            }
          }

          // ── ROW 2-9: Cost Analysis tile (right half — to the right of the RG) ─
          // Note: CostAnalysisPinnedChartPart is deprecated; we use a rich Markdown
          // tile with direct cost-management links instead so the dashboard always
          // deploys cleanly across tenants.
          {
            position: { x: 6, y: 2, colSpan: 6, rowSpan: 8 }
            metadata: {
              inputs: []
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '## 💰 Cost Analysis\n\nDetailed cost breakdown and trends for **${targetResourceGroup}**.\n\n**Quick Links:**\n- [📊 Open Cost Analysis](${costAnalysisUrl})\n- [🔔 Cost Alerts](https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/costanalysis/scope/${replace(rgResourceId, '/', '%2F')}/alerts)\n- [💵 Budgets](https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/budgets/scope/${replace(rgResourceId, '/', '%2F')})\n- [🧠 Azure Advisor — Cost Recommendations](https://portal.azure.com/#blade/Microsoft_Azure_Expert/AdvisorMenuBlade/Cost)\n\n---\n\n### 💡 Optimization Tips\n- Review **Azure Advisor** for right-sizing recommendations\n- Set **budget alerts** to monitor monthly spend\n- Identify and stop **idle compute / storage**\n- Use the **AzqrCostOptimizeAgent** skill for a full audit'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }

          // ── ROW 10: 1x1 shortcut — AI Foundry V2 project ─────────────────────
          {
            position: { x: 0, y: 10, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: foundryAccountResId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.CognitiveServices/accounts'
              }
            }
          }

          // ── ROW 10: 1x1 shortcut — Storage Account 2001 ──────────────────────
          {
            position: { x: 1, y: 10, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: storage2001ResId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.Storage/storageAccounts'
              }
            }
          }

          // ── ROW 10: 1x1 shortcut — Key Vault ─────────────────────────────────
          {
            position: { x: 2, y: 10, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: keyvaultResId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.KeyVault/vaults'
              }
            }
          }

          // ── ROW 10: 1x1 shortcut — AI Search ─────────────────────────────────
          {
            position: { x: 3, y: 10, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: aiSearchResId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.Search/searchServices'
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
output aiFoundryUrl string = aiFoundryProjectUrl

@description('Project name from naming convention')
output projectName string = namingOutputs.projectName

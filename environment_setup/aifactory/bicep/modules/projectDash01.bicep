// ============================================================================
// AI Factory - Project Dashboard (projectDash01.bicep)
// ============================================================================
// Creates a rich Azure Portal dashboard for an AI Factory GenAI project with:
//   - Full-width title banner (project number, env, admin contact, shortcuts)
//   - Resource Group resources list tile  (left half)
//   - Accumulated cost chart tile         (right half)
//   - 4 quick-access resource tiles       (AI Foundry V2, Key Vault, Storage 2001, AI Search)
//
// Layout (12-column grid):
//   Row 0-1:  [  Title banner — Project{N} - {ENV} (GenAI)  ] (12 cols)
//   Row 2-9:  [ Resources (RG) ][  Cost Analysis chart       ] (6+6 cols)
//   Row 10-11:[ AI Foundry V2  ][ Key Vault ][ SA-2001 ][ AI Search ] (3+3+3+3)

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

          // ── ROW 0-1: Full-width title banner ─────────────────────────────────
          {
            position: { x: 0, y: 0, colSpan: 12, rowSpan: 2 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '# ${dashboardTitle}\n**RG:** [${targetResourceGroup}](${rgPortalUrl})\u2003|\u2003**Admin:** ${technicalAdminsEmail}\u2003|\u2003**Scale set:** ${aifactorySuffixRG}\u2003|\u2003[🤖 AI Foundry](${aiFoundryProjectUrl})\u2003|\u2003[💰 Cost Analysis](${costAnalysisUrl})'
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
              #disable-next-line BCP036
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'ResourceGroup'
              }
            }
          }

          // ── ROW 2-9: Accumulated cost analysis chart (right half) ─────────────
          {
            position: { x: 6, y: 2, colSpan: 6, rowSpan: 8 }
            metadata: {
              inputs: [
                { name: 'scope', isOptional: false, value: rgResourceId }
                { name: 'dateRange', isOptional: true, value: 'MonthToDate' }
                { name: 'granularity', isOptional: true, value: 'Daily' }
                { name: 'chartType', isOptional: true, value: 'StackedColumn' }
              ]
              #disable-next-line BCP036
              type: 'Extension/Microsoft_Azure_CostManagement/PartType/CostAnalysisPinnedChartPart'
              settings: {}
            }
          }

          // ── ROW 10-11: AI Foundry V2 account shortcut ────────────────────────
          {
            position: { x: 0, y: 10, colSpan: 3, rowSpan: 2 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: foundryAccountResId }
              ]
              #disable-next-line BCP036
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.CognitiveServices/accounts'
              }
            }
          }

          // ── ROW 10-11: Key Vault shortcut ─────────────────────────────────────
          {
            position: { x: 3, y: 10, colSpan: 3, rowSpan: 2 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: keyvaultResId }
              ]
              #disable-next-line BCP036
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.KeyVault/vaults'
              }
            }
          }

          // ── ROW 10-11: Storage Account 2001 shortcut ──────────────────────────
          {
            position: { x: 6, y: 10, colSpan: 3, rowSpan: 2 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: storage2001ResId }
              ]
              #disable-next-line BCP036
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.Storage/storageAccounts'
              }
            }
          }

          // ── ROW 10-11: AI Search shortcut ─────────────────────────────────────
          {
            position: { x: 9, y: 10, colSpan: 3, rowSpan: 2 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: aiSearchResId }
              ]
              #disable-next-line BCP036
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

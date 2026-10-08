// ============================================================================
// AI Factory - Project Dashboard (projectDash01.bicep)
// ============================================================================
// Creates a rich Azure Portal dashboard for an AI Factory GenAI project with:
//   - Full-width H1 banner (project number, environment, region)
//   - Resource Group resources list tile      (left half)
//   - Cost Analysis tile                       (right half — to the right of the RG)
//   - Two rows of resource shortcuts, with optional ML/data services
//   - Native daily consumption cost charts and compact report navigation
//
// Layout (12-column grid):
//   Row 0-1:  [ Banner H1 — Project {N} · {ENV} · {REGION} ]                    (colSpan 12, rowSpan 2)
//   Row 2-5:  [ Resources (RG) ][ Accumulated Cost Analysis ]                    (6 + 6)
//   Row 6:    [Foundry][Storage][KeyVault][AISearch][AppInsights][Cost links]    (5 + 7)
//   Row 7:    [Azure ML][Databricks][Data Factory][Logs][Monitoring links]
//   Row 8-11: [ Daily consumption cost ][ Daily cost by service ]               (6 + 6)
//   Row 12-19: Optional Foundry metrics (30-day Sum), then compact report cards,
//              service configuration and optional agent monitoring.

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

@description('Service configuration used to build the dashboard inventory.')
param enableAIFoundry bool = false
param enableAIFoundryHub bool = false
param addAIFoundryHub bool = false
param enableAFoundryCaphost bool = false
param enableAISearch bool = false
param addAISearch bool = false
param enableCosmosDB bool = false
param enableAzureOpenAI bool = false
param enableAIServices bool = false
param enableAzureAIVision bool = false
param enableAzureSpeech bool = false
param enableAIDocIntelligence bool = false
param enableContentSafety bool = false
param enableBing bool = false
param enableBingCustomSearch bool = false
param enableAzureMachineLearning bool = false
param addAzureMachineLearning bool = false
param enableAKS bool = false
param enableAksForAzureML bool = false
param enableDatafactory bool = false
param enableDatabricks bool = false
param enableContainerApps bool = false
param enableFunction bool = false
param enableWebApp bool = false
param enableLogicApps bool = false
param enableEventHubs bool = false
param enableBotService bool = false
param enablePostgreSQL bool = false
param enableRedisCache bool = false
param enableSQLDatabase bool = false
param enableElasticsearch bool = false
param allowPublicAccessWhenBehindVnet bool = false
param enablePublicGenAIAccess bool = false
param enablePublicAccessWithPerimeter bool = false
param cmk bool = false
param useCommonACR bool = true
param acrSku string = 'Premium'
param cosmosKind string = 'GlobalDocumentDB'
param aksSkuName string = 'Base'
param aksSkuTier string = 'Standard'
param skuAISearchDev string = 'standard'
param skuAISearchStageProd string = 'standard'
param skuAIServicesDev string = 'S0'
param skuAIServicesStageProd string = 'S0'
param skuOpenAIDev string = 'S0'
param skuOpenAIStageProd string = 'S0'
param skuContentSafetyDev string = 'S0'
param skuContentSafetyStageProd string = 'S0'
param skuVisionDev string = 'S1'
param skuVisionStageProd string = 'S1'
param skuSpeechDev string = 'S0'
param skuSpeechStageProd string = 'S0'
param skuDocIntelligenceDev string = 'S0'
param skuDocIntelligenceStageProd string = 'S0'
param skuPostgreSQLDev string = 'Standard_B1ms'
param skuPostgreSQLStageProd string = 'Standard_B1ms'
param skuRedisDev string = 'Standard'
param skuRedisStageProd string = 'Standard'
param skuSQLDatabaseDev string = 'S0'
param skuSQLDatabaseStageProd string = 'S0'
param skuElasticDev string = 'ess-consumption-2024_Monthly'
param skuElasticStageProd string = 'ess-consumption-2024_Monthly'
param skuWebAppDev string = 'P1v3'
param skuWebAppStageProd string = 'P1v3'
param skuFunctionDev string = 'EP1'
param skuFunctionStageProd string = 'EP1'

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

@description('Add the Azure-native My Project Usage & Cost workbook using existing telemetry only. No workspace, ingestion or roles are created.')
param enableMyProjectDashboard bool = true
@description('Override the existing project Application Insights ARM ID if it differs from naming outputs.')
param myProjectApplicationInsightsResourceId string = ''
@description('Override the existing common Log Analytics workspace ARM ID if it differs from naming outputs.')
param myProjectLogAnalyticsResourceId string = ''
@description('Optional exact canonical telemetry factory ID (opaque, may include paths/colons). Empty requires user selection; never inferred from RG naming.')
param myProjectFactoryId string = ''
@description('Optional exact canonical telemetry scale set ID. Empty requires user selection; no All scope.')
param myProjectScaleSetId string = ''
@description('Fixed telemetry environment. Deployment test maps to stage by default; override only to match actual instrumentation.')
param myProjectTelemetryEnvironment string = env == 'test' ? 'stage' : env
@description('Default workbook IANA time zone; local calendar boundaries are DST-aware.')
param myProjectTimeZone string = 'Europe/Berlin'
@description('Reviewed completeness keys: questions, devices, feedback, cart, bookings, cases, stateBaseline, metering, billing. All default false.')
param myProjectCoverage object = {}
@minValue(30)
@maxValue(90)
@description('Bounded baseline history in local dates ending at selected end. State coverage remains false unless a full baseline is reviewed.')
param myProjectStateHistoryDays int = 90

@description('Optional deployed shared agent workbook ARM ID supplied by phase 10. Empty adds no navigation tile and creates no agent workbook.')
param agentMonitoringWorkbookResourceId string = ''

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
    addAzureMachineLearning: addAzureMachineLearning
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
var foundryProjectResId    = '${foundryAccountResId}/projects/${aifV2ProjectName}'
var keyvaultResId          = '${rgResourceId}/providers/Microsoft.KeyVault/vaults/${namingOutputs.keyvaultName}'
var storage2001ResId       = '${rgResourceId}/providers/Microsoft.Storage/storageAccounts/${namingOutputs.storageAccount2001Name}'
var aiSearchResId          = '${rgResourceId}/providers/Microsoft.Search/searchServices/${namingOutputs.safeNameAISearch}'
var amlResId               = '${rgResourceId}/providers/Microsoft.MachineLearningServices/workspaces/${namingOutputs.amlName}'
// Keep the phase-07 Databricks name; it does not include the random AML salt.
var databricksName         = 'dbx-${projectNumber}-${locationSuffix}-${env}-${namingOutputs.uniqueInAIFenv}${resourceSuffix}'
var databricksResId        = '${rgResourceId}/providers/Microsoft.Databricks/workspaces/${databricksName}'
var dataFactoryResId       = '${rgResourceId}/providers/Microsoft.DataFactory/factories/${namingOutputs.dataFactoryName}'
var isDev = env == 'dev'
var privateNetworking = !(allowPublicAccessWhenBehindVnet && enablePublicGenAIAccess && enablePublicAccessWithPerimeter)
var foundryWithPrivateCaphost = (enableAIFoundry || addAIFoundry) && enableAFoundryCaphost && privateNetworking
var needsContainerRegistry = enableAIFoundry || addAIFoundry || enableAzureMachineLearning || addAzureMachineLearning || enableContainerApps
var aiSearchSku = isDev ? skuAISearchDev : skuAISearchStageProd
var aiServicesSku = isDev ? skuAIServicesDev : skuAIServicesStageProd
var openAiSku = isDev ? skuOpenAIDev : skuOpenAIStageProd
var contentSafetySku = isDev ? skuContentSafetyDev : skuContentSafetyStageProd
var visionSku = isDev ? skuVisionDev : skuVisionStageProd
var speechSku = isDev ? skuSpeechDev : skuSpeechStageProd
var docIntelligenceSku = isDev ? skuDocIntelligenceDev : skuDocIntelligenceStageProd
var postgreSqlSku = isDev ? skuPostgreSQLDev : skuPostgreSQLStageProd
var redisSku = isDev ? skuRedisDev : skuRedisStageProd
var sqlDatabaseSku = isDev ? skuSQLDatabaseDev : skuSQLDatabaseStageProd
var elasticSku = isDev ? skuElasticDev : skuElasticStageProd
var webAppSku = isDev ? skuWebAppDev : skuWebAppStageProd
var functionSku = isDev ? skuFunctionDev : skuFunctionStageProd
var enabledByUserServices = concat(
  (enableAIFoundry || addAIFoundry) ? ['AI Foundry | SKU: Standard | Purpose: AI agent and application creation.'] : [],
  (enableAIFoundryHub || addAIFoundryHub) ? ['AI Foundry Hub v1 | SKU: Standard | Purpose: legacy AI Foundry workspace hub.'] : [],
  ((enableAISearch || addAISearch) && !foundryWithPrivateCaphost) ? ['AI Search | SKU: ${aiSearchSku} | Purpose: search, retrieval, and grounding.'] : [],
  (enableCosmosDB && !foundryWithPrivateCaphost) ? ['Cosmos DB | SKU: ${cosmosKind} | Purpose: application data and agent threads.'] : [],
  enableAzureOpenAI ? ['Azure OpenAI | SKU: ${openAiSku} | Purpose: generative AI model deployments.'] : [],
  enableAIServices ? ['Azure AI Services | SKU: ${aiServicesSku} | Purpose: multi-service AI APIs.'] : [],
  enableAzureAIVision ? ['Azure AI Vision | SKU: ${visionSku} | Purpose: image analysis and OCR.'] : [],
  enableAzureSpeech ? ['Azure AI Speech | SKU: ${speechSku} | Purpose: speech recognition and synthesis.'] : [],
  enableAIDocIntelligence ? ['Document Intelligence | SKU: ${docIntelligenceSku} | Purpose: document extraction and analysis.'] : [],
  enableContentSafety ? ['Azure AI Content Safety | SKU: ${contentSafetySku} | Purpose: harmful-content detection.'] : [],
  enableBing ? ['Bing Search | SKU: G2 | Purpose: web search grounding.'] : [],
  enableBingCustomSearch ? ['Bing Custom Search | SKU: G2 | Purpose: domain-specific web search.'] : [],
  (enableAzureMachineLearning || addAzureMachineLearning) ? ['Azure Machine Learning | SKU: - | Purpose: machine learning experimentation, training, and MLOps.'] : [],
  (enableAKS || enableAksForAzureML) ? ['Azure Kubernetes Service | SKU: ${aksSkuName} ${aksSkuTier} | Purpose: managed Kubernetes and Azure ML inference compute.'] : [],
  enableDatafactory ? ['Azure Data Factory | SKU: - | Purpose: data ingestion and orchestration.'] : [],
  enableDatabricks ? ['Azure Databricks | SKU: - | Purpose: data engineering and analytics.'] : [],
  enableContainerApps ? ['Azure Container Apps | SKU: Consumption | Purpose: containerized application hosting.'] : [],
  enableFunction ? ['Azure Functions | SKU: ${functionSku} | Purpose: event-driven serverless workloads.'] : [],
  enableWebApp ? ['Azure App Service | SKU: ${webAppSku} | Purpose: web application hosting.'] : [],
  enableLogicApps ? ['Azure Logic Apps | SKU: Standard | Purpose: workflow automation and integration.'] : [],
  enableEventHubs ? ['Azure Event Hubs | SKU: Standard | Purpose: event ingestion and streaming.'] : [],
  enableBotService ? ['Azure Bot Service | SKU: - | Purpose: conversational bot channels.'] : [],
  enablePostgreSQL ? ['Azure Database for PostgreSQL | SKU: ${postgreSqlSku} | Purpose: relational data, vectors, and GIS.'] : [],
  enableRedisCache ? ['Azure Cache for Redis | SKU: ${redisSku} | Purpose: low-latency cache and session state.'] : [],
  enableSQLDatabase ? ['Azure SQL Database | SKU: ${sqlDatabaseSku} | Purpose: relational application data.'] : [],
  enableElasticsearch ? ['Elastic Cloud | SKU: ${elasticSku} | Purpose: search and observability workloads.'] : []
)
var mandatoryServices = concat(
  [
    'Storage Account | SKU: Standard_LRS | Purpose: required artifact, data, and service storage.'
    'Key Vault | SKU: Standard | Purpose: required secret, key, and certificate storage.'
    'Application Insights | SKU: pay-as-you-go | Purpose: required application telemetry and monitoring.'
  ],
  privateNetworking ? ['Private Endpoints | SKU: - | Purpose: private connectivity for enabled Azure PaaS services.'] : [],
  foundryWithPrivateCaphost ? ['AI Search | SKU: ${aiSearchSku} | Purpose: required by private Foundry capability hosts for Foundry IQ.'] : [],
  foundryWithPrivateCaphost ? ['Cosmos DB | SKU: ${cosmosKind} | Purpose: required by private Foundry capability hosts for agent threads and state.'] : [],
  (needsContainerRegistry && (privateNetworking || cmk)) ? ['${useCommonACR ? 'Shared ' : ''}Container Registry | SKU: ${acrSku} | Purpose: required by Foundry, Azure ML, and Container Apps; Premium supports private endpoints and CMK.'] : []
)
var enabledByUserMarkdown = empty(enabledByUserServices) ? '- No optional services are enabled.' : '- ${join(enabledByUserServices, '\n- ')}'
var mandatoryServicesMarkdown = '- ${join(mandatoryServices, '\n- ')}'

// Portal deep links
var aiFoundryProjectUrl    = 'https://ai.azure.com/build/overview?tid=${tenant().tenantId}&wsid=${foundryAccountResId}/projects/${aifV2ProjectName}'
var costAnalysisUrl        = 'https://portal.azure.com/@${tenant().tenantId}/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/${uriComponent(rgResourceId)}'
var rgPortalUrl            = 'https://portal.azure.com/#@${tenant().tenantId}/resource${rgResourceId}'

// Same native pin schema as deploy-aifactory-dashboard.py::cost_part.
var nativeCostAnalysisPart = {
  position: { x: 6, y: 2, colSpan: 6, rowSpan: 4 }
  metadata: {
    deepLink: '#@${tenant().tenantId}/resource${rgResourceId}/costanalysis'
    inputs: [
      { name: 'scope', value: rgResourceId }
      { name: 'scopeName', value: targetResourceGroup }
      {
        name: 'view'
        isOptional: true
        value: {
          accumulated: 'true'
          chart: 'Area'
          currency: null
          dateRange: 'ThisMonth'
          displayName: 'AccumulatedCosts'
          kpis: [
            {
              enabled: true
              extendedProperties: { name: 'COST_NAVIGATOR.BUDGET_OPTIONS.NONE' }
              id: 'COST_NAVIGATOR.BUDGET_OPTIONS.NONE'
              type: 'Budget'
            }
            { enabled: true, type: 'Forecast' }
          ]
          pivots: [
            { name: 'ServiceName', type: 'Dimension' }
            { name: 'ResourceLocation', type: 'Dimension' }
            { name: 'ResourceId', type: 'Dimension' }
          ]
          query: {
            dataSet: {
              aggregation: {
                totalCost: { function: 'Sum', name: 'Cost' }
                totalCostUSD: { function: 'Sum', name: 'CostUSD' }
              }
              granularity: 'Daily'
              sorting: [{ direction: 'ascending', name: 'UsageDate' }]
            }
            timeframe: 'None'
            type: 'ActualCost'
          }
          scope: substring(rgResourceId, 1)
        }
      }
      { name: 'externalState', isOptional: true }
    ]
    type: 'Extension/Microsoft_Azure_CostManagement/PartType/CostAnalysisPinPart'
  }
}

var consumptionViews = [
  { title: 'Daily consumption cost', grouping: [] }
  { title: 'Daily cost by service', grouping: [{ name: 'ServiceName', type: 'Dimension' }] }
]
var consumptionCostParts = [for (view, index) in consumptionViews: {
  position: { x: index * 6, y: 8, colSpan: 6, rowSpan: 4 }
  metadata: {
    deepLink: nativeCostAnalysisPart.metadata.deepLink
    inputs: [
      { name: 'scope', value: rgResourceId }
      { name: 'scopeName', value: targetResourceGroup }
      {
        name: 'view'
        isOptional: true
        value: union(nativeCostAnalysisPart.metadata.inputs[2].value, {
          accumulated: 'false'
          chart: 'StackedColumn'
          displayName: view.title
          kpis: []
          query: union(nativeCostAnalysisPart.metadata.inputs[2].value.query, {
            dataSet: union(nativeCostAnalysisPart.metadata.inputs[2].value.query.dataSet, {
              grouping: view.grouping
            })
          })
        })
      }
      { name: 'externalState', isOptional: true }
    ]
    type: 'Extension/Microsoft_Azure_CostManagement/PartType/CostAnalysisPinPart'
  }
}]

var mlDataShortcutParts = concat(
  (enableAzureMachineLearning || addAzureMachineLearning) ? [{
    position: { x: 0, y: 7, colSpan: 1, rowSpan: 1 }
    metadata: {
      inputs: [{ name: 'id', isOptional: false, value: amlResId }]
      type: 'Extension/HubsExtension/PartType/ResourcePart'
      asset: { idInputName: 'id', type: 'Microsoft.MachineLearningServices/workspaces' }
    }
  }] : [],
  enableDatabricks ? [{
    position: { x: 1, y: 7, colSpan: 1, rowSpan: 1 }
    metadata: {
      inputs: [{ name: 'id', isOptional: false, value: databricksResId }]
      type: 'Extension/HubsExtension/PartType/ResourcePart'
      asset: { idInputName: 'id', type: 'Microsoft.Databricks/workspaces' }
    }
  }] : [],
  enableDatafactory ? [{
    position: { x: 2, y: 7, colSpan: 1, rowSpan: 1 }
    metadata: {
      inputs: [{ name: 'id', isOptional: false, value: dataFactoryResId }]
      type: 'Extension/HubsExtension/PartType/ResourcePart'
      asset: { idInputName: 'id', type: 'Microsoft.DataFactory/factories' }
    }
  }] : []
)

var foundryMetricsEnabled = enableAIFoundry || addAIFoundry
var foundryMetricsHeight = foundryMetricsEnabled ? 8 : 0
module foundryMetricTiles './foundryMetricTiles.bicep' = {
  name: 'foundry-metric-tiles-${uniqueString(resourceGroup().id)}'
  params: {
    enabled: foundryMetricsEnabled
    accountResourceId: foundryAccountResId
    projectResourceId: foundryProjectResId
  }
}
var foundryMetricNoticeParts = foundryMetricsEnabled ? [{
  position: { x: 0, y: 12, colSpan: 12, rowSpan: 2 }
  metadata: {
    inputs: []
    type: 'Extension/HubsExtension/PartType/MarkdownPart'
    settings: {
      content: {
        settings: {
          content: '## Foundry consumption - last 30 days, Sum\n\nAccount: **${aifV2AccountName}** | Agent project: **${aifV2ProjectName}** | [Account metrics](https://portal.azure.com/#@${tenant().tenantId}/resource${foundryAccountResId}/metrics) | [Project metrics](https://portal.azure.com/#@${tenant().tenantId}/resource${foundryProjectResId}/metrics)\n\nMissing/unsupported metrics are unavailable, not zero. Account totals may cover other Foundry projects. Total Calls / Blocked Calls / RateLimit exclude OpenAI; RateLimit sums limit values, not throttled requests. Estimated USD is not billed cost. Safety detections include annotate-only events; series overlap and must not be added.'
          title: ''
          subtitle: ''
          markdownSource: 1
          markdownUri: null
        }
      }
    }
  }
}] : []

var projectInsightsId = empty(myProjectApplicationInsightsResourceId)
  ? '${rgResourceId}/providers/Microsoft.Insights/components/${namingOutputs.applicationInsightName}'
  : myProjectApplicationInsightsResourceId
var projectWorkspaceId = empty(myProjectLogAnalyticsResourceId)
  ? resourceId(subscriptionIdDevTestProd, commonResourceGroupName, 'Microsoft.OperationalInsights/workspaces', namingOutputs.laWorkspaceName)
  : myProjectLogAnalyticsResourceId

module myProjectWorkbook './myProjectWorkbook.bicep' = if (enableMyProjectDashboard) {
  name: 'my-project-workbook-${uniqueString(resourceGroup().id, projectNumber, env)}'
  params: {
    location: location
    projectNumber: projectNumber
    env: env
    telemetryEnvironment: myProjectTelemetryEnvironment
    applicationInsightsResourceId: projectInsightsId
    logAnalyticsResourceId: projectWorkspaceId
    projectResourceGroupId: rgResourceId
    factoryId: myProjectFactoryId
    scaleSetId: myProjectScaleSetId
    timeZone: myProjectTimeZone
    coverage: myProjectCoverage
    stateHistoryDays: myProjectStateHistoryDays
    tags: tags
  }
}
var myProjectEntryParts = enableMyProjectDashboard ? [
  {
    position: { x: 0, y: 12 + foundryMetricsHeight, colSpan: 6, rowSpan: 2 }
    metadata: {
      inputs: []
      type: 'Extension/HubsExtension/PartType/MarkdownPart'
      settings: {
        content: {
          settings: {
            content: '## Usage & outcomes\n\n[Open My Project ${projectNumber}](${myProjectWorkbook!.outputs.url} "Usage, feedback, business outcomes and attributed costs")\n\nConversations, feedback and Retail / Booking / Support outcomes. Select factory, scale set, dates and store. Coverage required; missing data is unavailable, not zero. Allocated / estimated costs are separate from billing.'
            title: ''
            subtitle: ''
            markdownSource: 1
            markdownUri: null
          }
        }
      }
    }
  }
  {
    position: { x: 6, y: 12 + foundryMetricsHeight, colSpan: 6, rowSpan: 2 }
    metadata: {
      inputs: []
      type: 'Extension/HubsExtension/PartType/MarkdownPart'
      settings: {
        content: {
          settings: {
            content: '## Model consumption\n\n[Open native model-token report](${myProjectWorkbook!.outputs.tokensUrl} "Input, output and cached tokens by model deployment")\n\nFoundry / OpenAI in this project RG. Metrics and request logs remain separate. Missing series are unavailable, not zero. Input includes cached tokens; never add both. Token counts are not billed costs.'
            title: ''
            subtitle: ''
            markdownSource: 1
            markdownUri: null
          }
        }
      }
    }
  }
] : []

var agentMonitoringEntryParts = empty(agentMonitoringWorkbookResourceId) ? [] : [
  {
    position: { x: 0, y: 19 + foundryMetricsHeight, colSpan: 12, rowSpan: 2 }
    metadata: {
      inputs: []
      type: 'Extension/HubsExtension/PartType/MarkdownPart'
      settings: {
        content: {
          settings: {
            content: '## Agent value, usage, cost and trust\n\n[Open the shared agent evidence workbook](https://portal.azure.com/#@${tenant().tenantId}/resource${agentMonitoringWorkbookResourceId})\n\nSelect the exact factory, scale set, project and environment. All means authorized collected observations in the workspace, not automatic tenant discovery. Modeled benefit, quality-qualified outcomes and verified realized value are distinct. Billing and token estimates are never added together. A saved workbook does not create telemetry or prove collection coverage.'
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
        parts: concat([
          // ── ROW 0-1: Full-width H1 banner (project · env · region) ────────────
          {
            position: { x: 0, y: 0, colSpan: 12, rowSpan: 2 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '# Project ${projectNumber} - ${toUpper(env)} (GenAI)\n\n**Owner:** ${projectOwner} | **Team:** ${projectTeam} | **Budget:** ${projectBudget} $/mon\n\n**Use case:** ${projectUseCase} | [Resource Group](${rgPortalUrl}) | [AI Foundry](${aiFoundryProjectUrl}) | [Cost Analysis](${costAnalysisUrl})'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }

          // ── ROW 2-5: Project resource group and accumulated cost ─────────────
          {
            position: { x: 0, y: 2, colSpan: 6, rowSpan: 4 }
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

          nativeCostAnalysisPart

          // ── ROW 6: Existing 1x1 resource shortcuts ──────────────────────────
          {
            position: { x: 0, y: 6, colSpan: 1, rowSpan: 1 }
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

          // Storage Account 2001
          {
            position: { x: 1, y: 6, colSpan: 1, rowSpan: 1 }
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

          // Key Vault
          {
            position: { x: 2, y: 6, colSpan: 1, rowSpan: 1 }
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

          // AI Search
          {
            position: { x: 3, y: 6, colSpan: 1, rowSpan: 1 }
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
          {
            position: { x: 4, y: 6, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [
                { name: 'id', isOptional: false, value: projectInsightsId }
              ]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: {
                idInputName: 'id'
                type: 'Microsoft.Insights/components'
              }
            }
          }
          {
            position: { x: 5, y: 6, colSpan: 7, rowSpan: 1 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '**Consumption cost:** Azure Cost Management | ActualCost | This month. Forecast is a prediction, not a charge.\n\n[📊 Open Cost Analysis](${costAnalysisUrl}) | [Budgets](https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/budgets/scope/${replace(rgResourceId, '/', '%2F')})'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          {
            position: { x: 3, y: 7, colSpan: 1, rowSpan: 1 }
            metadata: {
              inputs: [{ name: 'id', isOptional: false, value: projectWorkspaceId }]
              #disable-next-line BCP088
              type: 'Extension/HubsExtension/PartType/ResourcePart'
              #disable-next-line BCP037
              asset: { idInputName: 'id', type: 'Microsoft.OperationalInsights/workspaces' }
            }
          }
          {
            position: { x: 4, y: 7, colSpan: 8, rowSpan: 1 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '**Monitor & optimize**\n\n[Application logs](https://portal.azure.com/#@${tenant().tenantId}/resource${projectInsightsId}/logs) | [Metrics](https://portal.azure.com/#@${tenant().tenantId}/resource${projectInsightsId}/metrics) | [Cost alerts](https://portal.azure.com/#@${tenant().tenantId}/blade/Microsoft_Azure_CostManagement/Menu/costanalysis/scope/${replace(rgResourceId, '/', '%2F')}/alerts) | [Advisor](https://portal.azure.com/#blade/Microsoft_Azure_Expert/AdvisorMenuBlade/Cost)'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }
          // Configuration follows the optional Foundry metrics and report cards.
          {
            position: { x: 0, y: 14 + foundryMetricsHeight, colSpan: 12, rowSpan: 5 }
            metadata: {
              inputs: []
              type: 'Extension/HubsExtension/PartType/MarkdownPart'
              settings: {
                content: {
                  settings: {
                    content: '## Service Configuration\n\n### Enabled by user\n${enabledByUserMarkdown}\n\n### Enabled since mandatory, due to Azure compatibility\n${mandatoryServicesMarkdown}'
                    title: ''
                    subtitle: ''
                    markdownSource: 1
                    markdownUri: null
                  }
                }
              }
            }
          }

        ], mlDataShortcutParts, consumptionCostParts, foundryMetricNoticeParts, foundryMetricTiles.outputs.parts, myProjectEntryParts, agentMonitoringEntryParts)
      }
    ]
    metadata: {
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

@description('Empty when My Project is disabled.')
output myProjectWorkbookId string = enableMyProjectDashboard ? myProjectWorkbook!.outputs.id : ''
output myProjectWorkbookName string = enableMyProjectDashboard ? myProjectWorkbook!.outputs.name : ''
output myProjectWorkbookUrl string = enableMyProjectDashboard ? myProjectWorkbook!.outputs.url : ''
output myProjectSourceIds object = enableMyProjectDashboard ? myProjectWorkbook!.outputs.sourceIds : {}

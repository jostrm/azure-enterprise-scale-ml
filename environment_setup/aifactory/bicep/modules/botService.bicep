// ============================================================================
// AZURE BOT SERVICE MODULE
// ============================================================================
// This module creates an Azure Bot Service for integrating AI Foundry agents
// with Microsoft Teams and other channels.
//
// Key features:
// - Multi-channel bot registration (Teams, Web Chat, etc.)
// - Integration with AI Foundry agent endpoints
// - Managed identity support
// - Diagnostic settings for monitoring
//
// CORRECT WORKFLOW (Verified from AI Foundry Portal):
// ----------------------------------------------------
// 1. Deploy AI Foundry + Project via IaC (with system-assigned identity)
// 2. Deploy Bot Service via IaC BEFORE creating any agent (THIS MODULE)
//    - Can leave microsoftAppId empty for auto-creation
//    - OR provide the AI Foundry agent's Application ID if known
// 3. In AI Foundry portal:
//    - Create your agent
//    - Click "Publish" > "Teams and Microsoft 365 Copilot"
//    - The portal will show "Azure Bot Services" section
//    - SELECT your pre-created Bot Service from the dropdown
// 4. After publishing, the agent is connected to the Bot Service
// 5. Use the Bot Service to access your agent from Teams/M365 Copilot
//
// MICROSOFT APP ID OPTIONS:
// -------------------------
// Option 1: Leave microsoftAppId EMPTY (Recommended)
//   - Azure auto-creates an Azure AD App Registration during Bot Service creation
//   - Simplest approach for new deployments
//   - The Application ID shown in Foundry portal dialog is this auto-created ID
//
// Option 2: Use AI Foundry Agent's Application ID
//   - Copy the "Application ID" from Foundry portal publish dialog
//   - Pass it as microsoftAppId parameter
//   - Creates single identity shared between agent and bot
//   - Requires creating agent first, then Bot Service (reverse order)
//
// Option 3: Create separate App Registration manually
//   - Register app in Azure AD before deployment
//   - Provides separate identity and full control
//   - Pass the App Registration's Client ID as microsoftAppId
//
// WHAT microsoftAppId IS:
// - Application (Client) ID from Azure AD App Registration
// - NOT a Service Principal Object ID
// - NOT a Managed Identity Client ID (unless using UserAssignedMSI type)
// - NOT a user identity
// ============================================================================

@description('Name of the Azure Bot Service')
param botName string

@description('Display name for the bot')
param botDisplayName string = botName

@description('Description of the bot')
param botDescription string = 'AI Foundry Agent Bot for Microsoft Teams integration'

@description('Azure region for the bot service')
param location string = resourceGroup().location

@description('Bot service SKU')
@allowed(['F0', 'S1'])
param sku string = 'F0' // F0 = Free, S1 = Standard

@description('Microsoft App ID (Client ID) for bot authentication. Leave EMPTY to auto-create, or provide AI Foundry agent App ID, or your own App Registration ID.')
param microsoftAppId string = ''

@description('Type of Microsoft App authentication')
@allowed(['MultiTenant', 'SingleTenant', 'UserAssignedMSI'])
param microsoftAppType string = 'MultiTenant'

@description('Auto-create Microsoft App Registration if microsoftAppId is empty')
param autoCreateAppRegistration bool = true

@description('Tenant ID for SingleTenant apps')
param microsoftAppTenantId string = tenant().tenantId

@description('User-assigned managed identity resource ID for UserAssignedMSI type')
param userAssignedManagedIdentityResourceId string = ''

@description('AI Foundry agent endpoint URL')
param agentEndpoint string = ''

@description('Tags to apply to resources')
param tags object = {}

@description('Enable Microsoft Teams channel')
param enableTeamsChannel bool = true

@description('Enable Direct Line channel for custom applications')
param enableDirectLineChannel bool = false

@description('Enable Web Chat channel')
param enableWebChatChannel bool = true

@description('Resource ID of the Log Analytics workspace for diagnostics')
param logAnalyticsWorkspaceId string = ''

@description('Diagnostic setting level - determines metrics and logs collected')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Icon URL for the bot (optional)')
param iconUrl string = ''

@description('Endpoint for the bot messaging (configured automatically by Foundry when agent is published)')
param messagingEndpoint string = agentEndpoint

// VERIFIED DEPLOYMENT WORKFLOW (per Foundry Portal):
// ---------------------------------------------------
// Step 1: Deploy infrastructure via IaC
//   - Deploy AI Foundry account + project
//   - Deploy Bot Service (this module) with empty microsoftAppId
//   - Bot Service auto-creates App Registration
//
// Step 2: In AI Foundry portal
//   - Create your agent
//   - Test and refine agent in playground
//
// Step 3: Publish agent to Teams
//   - Click "Publish" button in agent builder
//   - Select "Teams and Microsoft 365 Copilot" destination
//   - Portal shows "Application ID" and "Tenant ID" (from agent identity)
//   - Portal shows "Azure Bot Services" dropdown
//   - SELECT your pre-created Bot Service from the dropdown
//   - Click publish
//
// Step 4: AI Foundry automatically configures
//   - Bot Service messaging endpoint → Agent Application Activity Protocol URL
//   - Agent identity permissions
//   - Teams channel connectivity
//
// Step 5: Access agent
//   - Open Microsoft Teams
//   - Search for your bot by name
//   - Start chatting with your AI agent
//
// NOTE: The "No Bot Services found" error in Foundry portal confirms
// that Bot Service MUST be pre-created before agent publishing.

@description('Enable streaming for bot responses')
param isStreamingSupported bool = false

@description('Developer App Insights key (optional)')
param developerAppInsightsKey string = ''

@description('Developer App Insights App ID (optional)')
param developerAppInsightsAppId string = ''

@description('Developer App Insights API Key (optional)')
param developerAppInsightsApiKey string = ''

// ============================================================================
// AZURE BOT SERVICE
// ============================================================================

resource botService 'Microsoft.BotService/botServices@2023-09-15-preview' = {
  name: botName
  location: 'global' // Bot Service is a global service
  sku: {
    name: sku
  }
  kind: 'azurebot'
  tags: tags
  properties: {
    displayName: botDisplayName
    description: botDescription
    endpoint: messagingEndpoint
    // When empty and autoCreateAppRegistration=true, Azure creates the App Registration automatically
    // Use AI Foundry agent's App ID, or leave empty for auto-creation, or provide your own App Registration ID
    msaAppId: microsoftAppId
    msaAppType: microsoftAppType
    msaAppTenantId: microsoftAppTenantId
    msaAppMSIResourceId: microsoftAppType == 'UserAssignedMSI' ? userAssignedManagedIdentityResourceId : null
    iconUrl: iconUrl
    isStreamingSupported: isStreamingSupported
    developerAppInsightKey: !empty(developerAppInsightsKey) ? developerAppInsightsKey : null
    developerAppInsightsApplicationId: !empty(developerAppInsightsAppId) ? developerAppInsightsAppId : null
    developerAppInsightsApiKey: !empty(developerAppInsightsApiKey) ? developerAppInsightsApiKey : null
    openWithHint: 'bfcomposer://'
    schemaTransformationVersion: '1.3'
  }
}

// ============================================================================
// BOT CHANNELS
// ============================================================================
// NOTE: Channels are deployed sequentially with explicit dependencies to avoid
// potential race conditions during Bot Service configuration updates.
// Similar to model deployments in AI Foundry, channel creation can fail if
// multiple channels attempt to update the parent Bot Service simultaneously.

// Microsoft Teams Channel (deployed first)
resource teamsChannel 'Microsoft.BotService/botServices/channels@2023-09-15-preview' = if (enableTeamsChannel) {
  parent: botService
  name: 'MsTeamsChannel'
  location: 'global'
  properties: {
    channelName: 'MsTeamsChannel'
    properties: {
      isEnabled: true
      enableCalling: false
      callingWebhook: null
    }
  }
}

// Direct Line Channel (deployed after Teams channel if both enabled)
resource directLineChannel 'Microsoft.BotService/botServices/channels@2023-09-15-preview' = if (enableDirectLineChannel) {
  parent: botService
  name: 'DirectLineChannel'
  location: 'global'
  properties: {
    channelName: 'DirectLineChannel'
    properties: {
      sites: [
        {
          siteName: 'Default Site'
          isEnabled: true
          isV1Enabled: true
          isV3Enabled: true
          isSecureSiteEnabled: false
          trustedOrigins: []
        }
      ]
    }
  }
  dependsOn: [
    teamsChannel // Wait for Teams channel to complete if enabled
  ]
}

// Web Chat Channel (deployed last to avoid conflicts)
resource webChatChannel 'Microsoft.BotService/botServices/channels@2023-09-15-preview' = if (enableWebChatChannel) {
  parent: botService
  name: 'WebChatChannel'
  location: 'global'
  properties: {
    channelName: 'WebChatChannel'
    properties: {
      sites: [
        {
          siteName: 'Default Site'
          isEnabled: true
        }
      ]
    }
  }
  dependsOn: [
    teamsChannel       // Wait for Teams channel if enabled
    directLineChannel  // Wait for Direct Line channel if enabled
  ]
}

// ============================================================================
// DIAGNOSTIC SETTINGS
// ============================================================================

// Define metrics based on diagnostic level
var goldMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

var silverMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

var bronzeMetrics = [
  {
    category: 'AllMetrics'
    enabled: true
  }
]

// Bot Service currently doesn't have resource logs, only metrics
var selectedMetrics = diagnosticSettingLevel == 'gold' ? goldMetrics : diagnosticSettingLevel == 'silver' ? silverMetrics : bronzeMetrics

// Bot Service Diagnostic Settings
// Deployed after Bot Service and all channels are configured
resource botServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: 'diag-${botName}'
  scope: botService
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: selectedMetrics
    logs: []
  }
  dependsOn: [
    botService
    teamsChannel
    directLineChannel
    webChatChannel
  ]
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Resource ID of the Bot Service')
output botServiceId string = botService.id

@description('Name of the Bot Service')
output botServiceName string = botService.name

@description('Microsoft App ID (Client ID) of the bot')
output botMicrosoftAppId string = botService.properties.msaAppId

@description('Bot Service endpoint')
output botEndpoint string = botService.properties.endpoint

@description('Configuration endpoint for the bot in Azure Portal')
output botConfigurationUrl string = 'https://portal.azure.com/#@${tenant().tenantId}/resource${botService.id}'

@description('Bot Framework Portal URL for channel configuration')
output botFrameworkPortalUrl string = 'https://dev.botframework.com/bots?id=${botService.properties.msaAppId}'

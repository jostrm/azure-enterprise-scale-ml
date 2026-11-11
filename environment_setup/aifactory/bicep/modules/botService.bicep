// Standalone Azure Bot registration for a separately hosted messaging endpoint.
// ARM does not create an Entra app registration when microsoftAppId is empty.
// This module can create a UAMI, but that identity does not link a Foundry agent.
// Native Foundry uses the agent's own identity and Activity endpoint; prepare it
// with scripts/prepare-foundry-publishing.py after the agent exists.
// A Bot's Microsoft App ID is immutable. Never rebind an existing registration.

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
param sku string = 'S1' // Default to Standard to match Foundry-aligned deployment

@description('Application client ID for SingleTenant, or the client ID of an explicitly supplied UAMI. Empty only when this module creates the UAMI.')
param microsoftAppId string = ''

@description('Type of Microsoft App authentication. MultiTenant creation is deprecated; neither type guarantees Foundry portal discovery.')
@allowed(['SingleTenant', 'UserAssignedMSI'])
param microsoftAppType string = 'SingleTenant'

@description('Tenant ID for SingleTenant apps')
param microsoftAppTenantId string = tenant().tenantId

@description('User-assigned managed identity resource ID. Auto-created if empty and microsoftAppType is UserAssignedMSI.')
param userAssignedManagedIdentityResourceId string = ''

@description('Explicit messaging endpoint. Empty reserves a bot registration without claiming a deployed handler or Foundry link.')
param agentEndpoint string

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

@description('Endpoint for the hosted bot messaging handler')
param messagingEndpoint string = agentEndpoint

@description('Enable streaming for bot responses')
param isStreamingSupported bool = false

@description('Developer App Insights key (optional)')
param developerAppInsightsKey string = ''

@description('Developer App Insights App ID (optional)')
param developerAppInsightsAppId string = ''

@description('Developer App Insights API Key (optional)')
param developerAppInsightsApiKey string = ''

// ============================================================================
// MANAGED IDENTITY (for UserAssignedMSI authentication type)
// ============================================================================

resource botManagedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (microsoftAppType == 'UserAssignedMSI' && empty(userAssignedManagedIdentityResourceId)) {
  name: '${botName}-identity'
  location: location
  tags: tags
}

// Determine which identity to use
var identityResourceId = microsoftAppType == 'UserAssignedMSI' ? (empty(userAssignedManagedIdentityResourceId) ? botManagedIdentity!.id : userAssignedManagedIdentityResourceId) : ''
var appId = microsoftAppType == 'UserAssignedMSI' ? (empty(userAssignedManagedIdentityResourceId) ? botManagedIdentity!.properties.clientId : microsoftAppId) : microsoftAppId

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
    msaAppId: appId
    msaAppType: microsoftAppType
    msaAppTenantId: microsoftAppTenantId
    msaAppMSIResourceId: identityResourceId != '' ? identityResourceId : null
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

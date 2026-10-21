targetScope = 'subscription'

@description('Existing API Management service name. The service must have a system-assigned managed identity.')
param apimServiceName string

@description('Resource group containing the existing API Management service.')
param apimResourceGroupName string

@description('Subscription containing the existing API Management service.')
param apimSubscriptionId string = subscription().subscriptionId

@description('APIM API identifier created for the pooled Azure OpenAI endpoint.')
param apiId string = 'azure-openai-gpt55'

@description('Public APIM API path. Clients call /<apiPath>/... .')
param apiPath string = 'openai'

@description('APIM backend pool name.')
param backendPoolName string = 'aoai-gpt55-pool'

@minValue(1)
@description('Aggregate TPM admitted by APIM. Set to 80-90% of the total TPM of all backend deployments.')
param aggregateTokensPerMinute int

@minValue(1)
@description('TPM allowed to one APIM subscription. This is a fair-use allocation, not the fleet total.')
param callerTokensPerMinute int = 10000

@minValue(1)
@maxValue(50)
@description('Retries after a backend 429. Two retries are normally sufficient when the pool contains many healthy deployments.')
param retryCount int = 2

@description('Assign Cognitive Services OpenAI User to the APIM managed identity on every backend resource.')
param assignOpenAIUserRole bool = false

@description('Object ID of APIM system-assigned managed identity. Required only when assignOpenAIUserRole is true.')
param apimManagedIdentityPrincipalId string = ''

@minLength(1)
@description('Azure OpenAI backends. Each object requires name, endpoint, resourceId, and weight; priority is optional and defaults to 1. All production backends should use priority 1 and expose identically named deployments.')
param azureOpenAIBackends array

@minValue(0)
@description('Requests per minute allowed from one client IP address. 0 turns the limit off.')
param clientIpRequestsPerMinute int = 0

@minValue(0)
@description('LLM tokens per minute allowed from one client IP address. 0 turns the limit off.')
param clientIpTokensPerMinute int = 0

@minValue(0)
@description('LLM tokens per minute for one Microsoft Entra user (validated oid). Requires entraTenantId. 0 turns the limit off.')
param userTokensPerMinute int = 0

@description('Microsoft Entra tenant whose access tokens callers must present. Empty keeps subscription-key-only access.')
param entraTenantId string = ''

@description('Client application IDs accepted by the Entra token validation.')
param entraClientApplicationIds array = []

@description('Audiences accepted by the Entra token validation.')
param entraAudiences array = []

@description('Emit LLM token metrics to Application Insights. Requires applicationInsightsLoggerName.')
param emitTokenMetrics bool = false

@description('Existing APIM Application Insights logger name used for token metrics.')
param applicationInsightsLoggerName string = ''

@description('Serve semantically similar prompts from an external Redis cache with RediSearch. Off by default because the cache is a separate paid resource.')
param enableSemanticCache bool = false

@description('Similarity threshold from 0.0 to 1.0. Lower values require closer matches.')
param semanticCacheScoreThreshold string = '0.05'

@minValue(1)
@description('Seconds a cached completion is kept.')
param semanticCacheDurationSeconds int = 120

@description('Embeddings deployment URL used for semantic matching.')
param embeddingsBackendUrl string = ''

@secure()
@description('Connection string of the external Redis with RediSearch that APIM uses as its cache.')
param semanticCacheConnectionString string = ''

@description('Existing MCP servers to expose through this APIM. Each object requires mcpServerName, displayName and mcpServerBaseUrl; the other apim-mcp-server.bicep parameters are optional.')
param mcpServers array = []

module apimConfiguration 'apim-configuration.bicep' = {
  name: 'apim-aoai-pool-${uniqueString(apimSubscriptionId, apimResourceGroupName, apimServiceName)}'
  scope: resourceGroup(apimSubscriptionId, apimResourceGroupName)
  params: {
    apimServiceName: apimServiceName
    apiId: apiId
    apiPath: apiPath
    backendPoolName: backendPoolName
    aggregateTokensPerMinute: aggregateTokensPerMinute
    callerTokensPerMinute: callerTokensPerMinute
    retryCount: retryCount
    azureOpenAIBackends: azureOpenAIBackends
    clientIpRequestsPerMinute: clientIpRequestsPerMinute
    clientIpTokensPerMinute: clientIpTokensPerMinute
    userTokensPerMinute: userTokensPerMinute
    entraTenantId: entraTenantId
    entraClientApplicationIds: entraClientApplicationIds
    entraAudiences: entraAudiences
    emitTokenMetrics: emitTokenMetrics
    applicationInsightsLoggerName: applicationInsightsLoggerName
    enableSemanticCache: enableSemanticCache
    semanticCacheScoreThreshold: semanticCacheScoreThreshold
    semanticCacheDurationSeconds: semanticCacheDurationSeconds
    embeddingsBackendUrl: embeddingsBackendUrl
    semanticCacheConnectionString: semanticCacheConnectionString
  }
}

module apimMcpServers 'apim-mcp-server.bicep' = [for server in mcpServers: {
  name: 'apim-mcp-${uniqueString(apimSubscriptionId, apimResourceGroupName, apimServiceName, server.mcpServerName)}'
  scope: resourceGroup(apimSubscriptionId, apimResourceGroupName)
  params: {
    apimServiceName: apimServiceName
    mcpServerName: server.mcpServerName
    displayName: server.displayName
    mcpDescription: server.?mcpDescription ?? ''
    mcpServerBaseUrl: server.mcpServerBaseUrl
    mcpEndpointPath: server.?mcpEndpointPath ?? '/mcp'
    apiPath: server.?apiPath ?? server.mcpServerName
    mcpEntraAppId: server.?mcpEntraAppId ?? ''
    subscriptionRequired: server.?subscriptionRequired ?? true
    clientIpRequestsPerMinute: server.?clientIpRequestsPerMinute ?? 60
    userRequestsPerMinute: server.?userRequestsPerMinute ?? 0
    entraTenantId: server.?entraTenantId ?? entraTenantId
    entraClientApplicationIds: server.?entraClientApplicationIds ?? entraClientApplicationIds
    entraAudiences: server.?entraAudiences ?? entraAudiences
  }
  dependsOn: [
    apimConfiguration
  ]
}]

module apimOpenAIUserAssignments 'openai-role-assignment.bicep' = [for backend in azureOpenAIBackends: if (assignOpenAIUserRole && !empty(apimManagedIdentityPrincipalId)) {
  name: 'apim-aoai-user-${uniqueString(backend.resourceId, apimManagedIdentityPrincipalId)}'
  scope: resourceGroup(split(backend.resourceId, '/')[2], split(backend.resourceId, '/')[4])
  params: {
    azureOpenAIResourceName: last(split(backend.resourceId, '/'))
    apimManagedIdentityPrincipalId: apimManagedIdentityPrincipalId
  }
}]

output apimApiId string = apimConfiguration.outputs.apimApiId
output apimApiPath string = apimConfiguration.outputs.apimApiPath
output backendPoolResourceId string = apimConfiguration.outputs.backendPoolResourceId
output policyFeatures object = apimConfiguration.outputs.policyFeatures
output mcpGatewayUrls array = [for (server, index) in mcpServers: apimMcpServers[index].outputs.gatewayMcpUrl]
output requiredRoleDefinitionId string = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
output apimResourceId string = resourceId(apimSubscriptionId, apimResourceGroupName, 'Microsoft.ApiManagement/service', apimServiceName)

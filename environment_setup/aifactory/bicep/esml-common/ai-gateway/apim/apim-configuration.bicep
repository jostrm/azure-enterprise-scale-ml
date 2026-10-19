targetScope = 'resourceGroup'

import {
  clientLimitsXml
  entraValidationXml
  semanticCacheLookupXml
  semanticCacheStoreXml
  tokenMetricsXml
  userLimitsXml
} from 'apim-policy-fragments.bicep'

@description('Existing API Management service name. The service must have a system-assigned managed identity.')
param apimServiceName string

@description('APIM API identifier created for the pooled Azure OpenAI endpoint.')
param apiId string

@description('Public APIM API path. Clients call /<apiPath>/... .')
param apiPath string

@description('APIM backend pool name.')
param backendPoolName string

@minValue(1)
@description('Aggregate TPM admitted by APIM. Set to 80-90% of the total TPM of all backend deployments.')
param aggregateTokensPerMinute int

@minValue(1)
@description('TPM allowed to one APIM subscription. This is a fair-use allocation, not the fleet total.')
param callerTokensPerMinute int

@minValue(1)
@maxValue(50)
@description('Retries after a backend 429.')
param retryCount int

@minLength(1)
@description('Azure OpenAI backends. Each object requires name, endpoint, resourceId, and weight; priority is optional and defaults to 1.')
param azureOpenAIBackends array

@minValue(0)
@description('Requests per minute allowed from one client IP address. 0 turns the limit off.')
param clientIpRequestsPerMinute int = 0

@minValue(0)
@description('LLM tokens per minute allowed from one client IP address. 0 turns the limit off.')
param clientIpTokensPerMinute int = 0

@minValue(0)
@description('LLM tokens per minute allowed to one Microsoft Entra user, keyed on the validated oid claim. Requires entraTenantId. 0 turns the limit off.')
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

@description('Similarity threshold from 0.0 to 1.0. Lower values require closer matches; values above 0.2 risk wrong cached answers.')
param semanticCacheScoreThreshold string = '0.05'

@minValue(1)
@description('Seconds a cached completion is kept.')
param semanticCacheDurationSeconds int = 120

@description('Embeddings deployment URL used for semantic matching, for example https://<account>.openai.azure.com/openai/deployments/<embeddings>/embeddings.')
param embeddingsBackendUrl string = ''

@secure()
@description('Connection string of the external Redis with RediSearch that APIM uses as its cache.')
param semanticCacheConnectionString string = ''

var backendEndpoints = [for backend in azureOpenAIBackends: endsWith(backend.endpoint, '/') ? substring(backend.endpoint, 0, length(backend.endpoint) - 1) : backend.endpoint]
var embeddingsBackendName = '${backendPoolName}-embeddings'
var policyReplacements = [
  { token: '__BACKEND_POOL_NAME__', value: backendPoolName }
  { token: '__AGGREGATE_TPM__', value: string(aggregateTokensPerMinute) }
  { token: '__CALLER_TPM__', value: string(callerTokensPerMinute) }
  { token: '__RETRY_COUNT__', value: string(retryCount) }
  { token: '__ENTRA_VALIDATION__', value: entraValidationXml(entraTenantId, entraClientApplicationIds, entraAudiences) }
  { token: '__CLIENT_LIMITS__', value: clientLimitsXml(clientIpRequestsPerMinute, clientIpTokensPerMinute) }
  { token: '__USER_LIMITS__', value: userLimitsXml(entraTenantId, 0, userTokensPerMinute) }
  { token: '__TOKEN_METRICS__', value: tokenMetricsXml(emitTokenMetrics, applicationInsightsLoggerName, entraTenantId) }
  {
    token: '__SEMANTIC_CACHE_LOOKUP__'
    value: semanticCacheLookupXml(enableSemanticCache, embeddingsBackendName, semanticCacheScoreThreshold,
      !empty(embeddingsBackendUrl) && !empty(semanticCacheConnectionString), entraTenantId)
  }
  { token: '__SEMANTIC_CACHE_STORE__', value: semanticCacheStoreXml(enableSemanticCache, semanticCacheDurationSeconds) }
]
var policyXml = reduce(policyReplacements, loadTextContent('./policy.xml'), (xml, item) => replace(xml, item.token, item.value))

resource apimService 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimServiceName
}

resource openAIBackends 'Microsoft.ApiManagement/service/backends@2024-05-01' = [for (backend, index) in azureOpenAIBackends: {
  parent: apimService
  name: backend.name
  properties: {
    title: backend.name
    description: 'Azure OpenAI backend for ${backendPoolName}'
    protocol: 'http'
    url: '${backendEndpoints[index]}/openai'
    resourceId: backend.resourceId
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
    circuitBreaker: {
      rules: [
        {
          name: 'azure-openai-429'
          failureCondition: {
            count: 1
            interval: 'PT1M'
            statusCodeRanges: [
              {
                min: 429
                max: 429
              }
            ]
          }
          tripDuration: 'PT1M'
          acceptRetryAfter: true
        }
      ]
    }
  }
}]

resource backendPool 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apimService
  name: backendPoolName
  #disable-next-line BCP035
  properties: {
    title: backendPoolName
    description: 'Weighted, active-active Azure OpenAI pool with 429 circuit breakers.'
    type: 'Pool'
    pool: {
      services: [for (backend, index) in azureOpenAIBackends: {
        id: openAIBackends[index].id
        priority: backend.?priority ?? 1
        weight: backend.?weight ?? 1
      }]
    }
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apimService
  name: apiId
  properties: {
    displayName: 'Azure OpenAI GPT-5.5 pooled gateway'
    description: 'Azure OpenAI API routed through a weighted backend pool.'
    path: apiPath
    protocols: [
      'https'
    ]
    serviceUrl: 'https://unused.invalid'
    subscriptionRequired: true
  }
}

var operations = [
  {
    name: 'chat-completions'
    displayName: 'Chat completions'
    urlTemplate: '/deployments/{deployment}/chat/completions'
    templateParameters: [
      {
        name: 'deployment'
        type: 'string'
        required: true
      }
    ]
  }
  {
    name: 'responses'
    displayName: 'Responses'
    urlTemplate: '/responses'
    templateParameters: []
  }
  {
    name: 'v1-responses'
    displayName: 'Responses v1'
    urlTemplate: '/v1/responses'
    templateParameters: []
  }
]

resource apiOperations 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [for operation in operations: {
  parent: api
  name: operation.name
  properties: {
    displayName: operation.displayName
    method: 'POST'
    urlTemplate: operation.urlTemplate
    templateParameters: operation.templateParameters
    responses: []
  }
}]

resource semanticCache 'Microsoft.ApiManagement/service/caches@2024-05-01' = if (enableSemanticCache) {
  parent: apimService
  name: 'default'
  properties: {
    description: 'AI Factory semantic cache (external Redis with RediSearch)'
    connectionString: semanticCacheConnectionString
    useFromLocation: 'default'
  }
}

resource embeddingsBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = if (enableSemanticCache) {
  parent: apimService
  name: embeddingsBackendName
  properties: {
    title: embeddingsBackendName
    description: 'Embeddings deployment used by the semantic cache lookup.'
    protocol: 'http'
    url: embeddingsBackendUrl
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource tokenMetricDiagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = if (emitTokenMetrics) {
  parent: api
  name: 'applicationinsights'
  properties: {
    loggerId: resourceId('Microsoft.ApiManagement/service/loggers', apimServiceName, applicationInsightsLoggerName)
    metrics: true
    alwaysLog: 'allErrors'
    logClientIp: true
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
  }
}

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: policyXml
  }
  dependsOn: [
    backendPool
    apiOperations
    semanticCache
    embeddingsBackend
    tokenMetricDiagnostics
  ]
}

output apimApiId string = api.name
output apimApiPath string = apiPath
output backendPoolResourceId string = backendPool.id
output policyFeatures object = {
  clientIpThrottling: clientIpRequestsPerMinute > 0 || clientIpTokensPerMinute > 0
  userThrottling: userTokensPerMinute > 0
  entraValidation: !empty(entraTenantId)
  tokenMetrics: emitTokenMetrics
  semanticCache: enableSemanticCache
}

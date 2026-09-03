targetScope = 'resourceGroup'

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

var backendEndpoints = [for backend in azureOpenAIBackends: endsWith(backend.endpoint, '/') ? substring(backend.endpoint, 0, length(backend.endpoint) - 1) : backend.endpoint]
var policyXml = replace(
  replace(
    replace(
      replace(loadTextContent('./policy.xml'), '__BACKEND_POOL_NAME__', backendPoolName),
      '__AGGREGATE_TPM__',
      string(aggregateTokensPerMinute)
    ),
    '__CALLER_TPM__',
    string(callerTokensPerMinute)
  ),
  '__RETRY_COUNT__',
  string(retryCount)
)

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
  ]
}

output apimApiId string = api.name
output apimApiPath string = apiPath
output backendPoolResourceId string = backendPool.id

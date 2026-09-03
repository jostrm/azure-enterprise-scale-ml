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
  }
}

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
output requiredRoleDefinitionId string = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

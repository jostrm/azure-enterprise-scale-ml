# Azure OpenAI APIM Pool

This Bicep configures an existing API Management service as the Azure OpenAI traffic controller. It creates one backend entity and a 429-aware circuit breaker for each item in `azureOpenAIBackends`, then creates a weighted pool and an APIM API with token limits and retry routing.

## Prerequisites

- Use BasicV2, StandardV2, PremiumV2, or a classic Developer, Basic, Standard, or Premium APIM service; Consumption does not support backend circuit breakers. `StandardV2` is the production default for VNet-integrated Azure OpenAI backends. APIM cannot migrate between classic and v2 SKUs in place.
- Enable APIM's system-assigned managed identity.
- Every Azure OpenAI resource must be reachable from APIM and contain the same deployment names.
- Give the APIM identity `Cognitive Services OpenAI User` on each backend. Set `assignOpenAIUserRole: true` and provide `apimManagedIdentityPrincipalId` to have this deployment create the assignments. The deployment identity needs permission to assign roles in every backend subscription.

## Backend configuration

Supply the backends as JSON. `weight` must be proportional to each deployment's provisioned TPM; leave all `priority` values as `1` for active-active traffic.

```json
[
  {
    "name": "aoai-gpt55-01",
    "endpoint": "https://aoai-gpt55-01.openai.azure.com",
    "resourceId": "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/aoai-gpt55-01",
    "weight": 1,
    "priority": 1
  },
  {
    "name": "aoai-gpt55-02",
    "endpoint": "https://aoai-gpt55-02.openai.azure.com",
    "resourceId": "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/aoai-gpt55-02",
    "weight": 2,
    "priority": 1
  }
]
```

Set `aggregateTokensPerMinute` to 80-90% of the sum of all pool deployment TPM. For example, 20 deployments with 60,000 TPM each have 1,200,000 TPM total; an 85% guard is `1020000`. `callerTokensPerMinute` is a per-APIM-subscription allocation.

Each `429` immediately opens the affected backend's circuit. APIM accepts the Azure OpenAI `Retry-After` value, skips that backend, and retries the buffered request through the pool. Requests that are rejected by the APIM token guard return `429` before they reach any Azure OpenAI backend.

This API exposes these POST operations:

- `/openai/deployments/{deployment}/chat/completions`
- `/openai/responses`
- `/openai/v1/responses`

The `apiPath` parameter changes the `openai` prefix.

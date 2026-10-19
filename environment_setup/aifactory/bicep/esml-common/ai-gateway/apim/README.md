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

## AI gateway policy package

These optional policies give a classic or v2 APIM the features of the native AI Gateway SKU (`ai.gateway.azure.com`). They follow the [Azure-Samples/AI-Gateway](https://github.com/Azure-Samples/AI-Gateway) labs. Every feature is off by default, so an existing deployment keeps its current policy until you set a parameter. The fragments live once in `apim-policy-fragments.bicep` and are shared by the LLM API and by MCP servers. Combinations that would be unsafe fail when you compile.

| Feature | Parameters | Policy |
|---|---|---|
| Client IP throttling | `clientIpRequestsPerMinute`, `clientIpTokensPerMinute` | `rate-limit-by-key` and `llm-token-limit` keyed on `context.Request.IpAddress` |
| User throttling | `userTokensPerMinute` plus `entraTenantId` and `entraClientApplicationIds` or `entraAudiences` | `validate-azure-ad-token`, then `llm-token-limit` keyed on the validated `oid` claim. Unvalidated tokens and headers are never used, because a caller could forge them to dodge the limit. |
| Subscription throttling | `callerTokensPerMinute` (existing) | `llm-token-limit` keyed on the APIM subscription |
| Semantic cache | `enableSemanticCache`, `embeddingsBackendUrl`, `semanticCacheConnectionString`, `semanticCacheScoreThreshold` (default `0.05`), `semanticCacheDurationSeconds` | `llm-semantic-cache-lookup` and `-store`, partitioned per subscription (and per user with Entra validation) |
| Token metrics | `emitTokenMetrics`, `applicationInsightsLoggerName` | `llm-emit-token-metric` with API, subscription, client IP and user dimensions, plus API diagnostics with metrics |

- **Semantic cache:** needs an external Redis with the RediSearch module, such as Azure Managed Redis. That is a separate paid resource, so keep `enableSemanticCache` false until it exists. Lower `semanticCacheScoreThreshold` values require closer matches. Microsoft Learn warns that values above 0.2 can return the wrong cached answer.
- **Token metrics:** need an existing APIM Application Insights logger. Enable custom metrics with dimensions on that Application Insights resource.

## MCP servers

`apim-mcp-server.bicep` exposes an existing streamable-HTTP MCP server through APIM. It is the classic counterpart of a native AI Gateway SKU tool server, and it uses `Microsoft.ApiManagement/service/apis@2025-09-01-preview` with `type: 'mcp'`. `main.bicep` deploys one per item in `mcpServers`. Clients call `https://<gateway>/<apiPath>/mcp` with an APIM subscription key, an Entra token (when `entraTenantId` is set), or both. Calls are limited per client IP (default 60 per minute) and, with Entra validation, per user.

APIM calls the MCP with its system-assigned managed identity for `mcpEntraAppId`. The Enterprise Scale AI Factory MCP admits that identity only after two one-time steps; the deployment does neither:

1. An Entra admin assigns the MCP app registration's app role `AiFactory.Mcp.Read` to the APIM managed identity. Pipelines never write Microsoft Graph.
2. The APIM managed identity is added to the MCP container app's allowed callers, as the MCP & AI Gateway integration already does for the native gateway.

APIM must also resolve and reach the MCP host. For an internal Container Apps environment, link a private DNS zone for its default domain to the APIM VNet. Only inbound policies are used: reading the response body would buffer it and break MCP streaming.

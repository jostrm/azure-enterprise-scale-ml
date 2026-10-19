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

`apim-mcp-server.bicep` exposes an existing streamable-HTTP MCP server through APIM. It is the classic counterpart of a native AI Gateway SKU tool server. It is a plain HTTP API (`type: 'http'`) with `POST`, `GET` and `DELETE` operations on the MCP endpoint and an unbuffered `forward-request`, so the backend MCP answers every call and responses can stream. `main.bicep` deploys one per item in `mcpServers`.

It does not use an API of `type: 'mcp'`. On 2026-10-19 the resource provider in Sweden Central (newest api-version `2025-09-01-preview`) accepted only a dictionary of endpoints and stored no `transportType`. APIM then answered `initialize` itself (`serverInfo` "Azure API Management") and returned an empty `tools/list`, instead of passing the calls through. The API is declared at `2025-09-01-preview`, which converts an existing `type: 'mcp'` API with the same name in place. Older api-versions cannot see MCP-type APIs: GET and PUT answer "Api not found", and DELETE does nothing. Clients call `https://<gateway>/<apiPath>/mcp` with an APIM subscription key, an Entra token (when `entraTenantId` is set), or both. Calls are limited per client IP (default 60 per minute) and, with Entra validation, per user.

APIM calls the MCP with its system-assigned managed identity for `mcpEntraAppId`. The Enterprise Scale AI Factory MCP admits that identity only after two one-time steps; the deployment does neither:

1. An Entra admin assigns the MCP app registration's app role `AiFactory.Mcp.Read` to the APIM managed identity. Pipelines never write Microsoft Graph.
2. The APIM managed identity is added to the MCP container app's allowed callers, as the MCP & AI Gateway integration already does for the native gateway. For a pipeline-hosted MCP, list the APIM in `aifactoryMcpClassicApimResourceIds`, or set `addAIFactoryMCP2APIM` (below).

APIM must also resolve and reach the MCP host. The MCP step requires an approved private endpoint on the MCP's Container Apps environment; the pipelines create it with the environment and register it in the `privatelink.<region>.azurecontainerapps.io` zone, which must be linked to the APIM VNet. Only inbound policies (plus the unbuffered `forward-request`) are used: reading the response body would buffer it and break MCP streaming.

`clientSubscriptionName` (optional) creates one APIM subscription scoped to the MCP API only; empty (the default) creates none, so a caller can keep its own.

### Pipeline default: `addAIFactoryMCP2APIM`

With `addAIFactoryMCP2APIM: "true"` and `enableAIFactoryMCP: "true"` no manual step is left except the Entra app role:

1. The project pipeline (MCP step) adds the identity of the APIM named by `apimGatewaySubscriptionId`/`apimGatewayResourceGroup`/`apimGatewayServiceName` to the MCP callers and prints the app-role prerequisite.
2. The AI gateway pipeline step "Expose the AI Factory MCP on APIM" (after the OpenAI pool) runs `usecase_code/40-agent-factory/45-aifactory-mcp-gateway/deploy.py apim-parameters`, which reads the MCP app and the APIM (GET only), and deploys this module with API `enterprise-scale-ai-factory` and client subscription `aifactory-mcp-client`. It refuses, naming the next step, while the MCP does not exist or does not list the APIM identity, and it skips Stage/Prod because the MCP runs only in Dev.

See `usecase_code/40-agent-factory/45-aifactory-mcp-gateway/readme.md` for adopting an MCP app that was deployed outside the pipeline (`aifactoryMcpContainerAppResourceId`).

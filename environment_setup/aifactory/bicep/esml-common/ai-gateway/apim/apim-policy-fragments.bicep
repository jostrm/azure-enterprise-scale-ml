// Shared API Management policy fragments for the AI gateway policy package.
// apim-configuration.bicep (LLM API) and apim-mcp-server.bicep (MCP servers) compose these,
// so each throttling, caller-validation, metric and cache rule lives here only once.
// An empty string means the feature is off; unsafe combinations fail at compile time.

func userCounterKey() string => '@(context.Variables.GetValueOrDefault<Jwt>("entra-token")?.Claims.GetValueOrDefault("oid", "anonymous"))'

@export()
@description('validate-azure-ad-token for Microsoft Entra callers; empty when tenantId is empty. Stores the validated token in variable entra-token.')
func entraValidationXml(tenantId string, clientApplicationIds array, audiences array) string => empty(tenantId)
  ? ''
  : empty(clientApplicationIds) && empty(audiences)
      ? fail('entraTenantId requires entraClientApplicationIds or entraAudiences so only intended callers are accepted.')
      : '<validate-azure-ad-token tenant-id="${tenantId}" header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. A valid Microsoft Entra access token is required." output-token-variable-name="entra-token">${empty(clientApplicationIds) ? '' : '<client-application-ids>${join(map(clientApplicationIds, id => '<application-id>${id}</application-id>'), '')}</client-application-ids>'}${empty(audiences) ? '' : '<audiences>${join(map(audiences, audience => '<audience>${audience}</audience>'), '')}</audiences>'}</validate-azure-ad-token>'

@export()
@description('Per client IP limits: requests per minute (rate-limit-by-key) and LLM tokens per minute (llm-token-limit). 0 turns a limit off.')
func clientLimitsXml(requestsPerMinute int, tokensPerMinute int) string => '${requestsPerMinute > 0 ? '<rate-limit-by-key calls="${requestsPerMinute}" renewal-period="60" counter-key="@(context.Request.IpAddress)" retry-after-header-name="Retry-After" />' : ''}${tokensPerMinute > 0 ? '<llm-token-limit counter-key="@(context.Request.IpAddress)" tokens-per-minute="${tokensPerMinute}" estimate-prompt-tokens="true" retry-after-header-name="Retry-After" />' : ''}'

@export()
@description('Per user limits keyed on the validated Microsoft Entra object ID (oid). Never keyed on unvalidated headers or tokens, which callers could forge.')
func userLimitsXml(tenantId string, requestsPerMinute int, tokensPerMinute int) string => requestsPerMinute <= 0 && tokensPerMinute <= 0
  ? ''
  : empty(tenantId)
      ? fail('userTokensPerMinute requires entraTenantId (and so does userRequestsPerMinute): per-user limits count only validated Microsoft Entra callers.')
      : '${requestsPerMinute > 0 ? '<rate-limit-by-key calls="${requestsPerMinute}" renewal-period="60" counter-key="${userCounterKey()}" retry-after-header-name="Retry-After" />' : ''}${tokensPerMinute > 0 ? '<llm-token-limit counter-key="${userCounterKey()}" tokens-per-minute="${tokensPerMinute}" estimate-prompt-tokens="true" retry-after-header-name="Retry-After" />' : ''}'

@export()
@description('llm-emit-token-metric with API, subscription, client IP and (with Entra validation) user dimensions. Needs an Application Insights logger and API diagnostics with metrics.')
func tokenMetricsXml(enabled bool, loggerName string, tenantId string) string => !enabled
  ? ''
  : empty(loggerName)
      ? fail('emitTokenMetrics requires applicationInsightsLoggerName (an existing APIM Application Insights logger).')
      : '<llm-emit-token-metric namespace="aifactory-ai-gateway"><dimension name="API ID" /><dimension name="Subscription ID" /><dimension name="Client IP" value="@(context.Request.IpAddress)" />${empty(tenantId) ? '' : '<dimension name="User ID" value="${userCounterKey()}" />'}</llm-emit-token-metric>'

@export()
@description('llm-semantic-cache-lookup. Lower scoreThreshold values require closer matches (Microsoft Learn suggests starting at 0.05). Entries are partitioned per subscription and, with Entra validation, per user.')
func semanticCacheLookupXml(enabled bool, embeddingsBackendId string, scoreThreshold string, hasInputs bool, tenantId string) string => !enabled
  ? ''
  : !hasInputs
      ? fail('enableSemanticCache requires embeddingsBackendUrl and semanticCacheConnectionString (an external Redis with RediSearch).')
      : '<llm-semantic-cache-lookup score-threshold="${scoreThreshold}" embeddings-backend-id="${embeddingsBackendId}" embeddings-backend-auth="system-assigned" ignore-system-messages="true"><vary-by>@(context.Subscription.Id)</vary-by>${empty(tenantId) ? '' : '<vary-by>${userCounterKey()}</vary-by>'}</llm-semantic-cache-lookup>'

@export()
@description('llm-semantic-cache-store in the outbound section; empty when the cache is off.')
func semanticCacheStoreXml(enabled bool, durationSeconds int) string => enabled ? '<llm-semantic-cache-store duration="${durationSeconds}" />' : ''

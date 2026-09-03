# APIM Azure OpenAI Gateway

The supported APIM implementation is in `../../aifactory/bicep/esml-common/ai-gateway/apim`.

It configures an existing APIM service with an Azure OpenAI weighted backend pool, 429 circuit breakers that accept `Retry-After`, aggregate and per-caller token limits, managed-identity backend authentication, and buffered retries.
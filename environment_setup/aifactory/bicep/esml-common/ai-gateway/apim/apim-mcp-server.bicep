targetScope = 'resourceGroup'

// Exposes an existing streamable-HTTP MCP server (for example the Enterprise Scale AI Factory MCP)
// through a classic or v2 API Management service, the classic counterpart of a native
// AI Gateway SKU tool server. APIM calls the MCP with its system-assigned managed identity.
//
// The API is a plain HTTP reverse proxy of the MCP endpoint, so the backend MCP answers every
// JSON-RPC call (initialize, tools/list, tools/call). An API of type 'mcp' is not used: on
// 2026-10-19 the resource provider (newest api-version 2025-09-01-preview) stored the MCP
// properties without a transportType and APIM answered as its own tool-less MCP server instead of passing
// through. The API is declared at 2025-09-01-preview because older api-versions cannot see a
// type 'mcp' API ("Api not found"); this version converts an existing one in place.

import { clientLimitsXml, entraValidationXml, userLimitsXml } from 'apim-policy-fragments.bicep'

@description('Existing API Management service name (classic Developer, Basic, Standard, Premium or a v2 tier). The service needs a system-assigned managed identity.')
param apimServiceName string

@description('MCP server (API) identifier in APIM, for example enterprise-scale-ai-factory.')
param mcpServerName string

@description('Display name shown in the APIM MCP servers blade.')
param displayName string

@description('Description shown in the APIM MCP servers blade.')
param mcpDescription string = ''

@description('Base HTTPS URL of the existing MCP server, without the MCP endpoint path.')
param mcpServerBaseUrl string

@description('Path of the streamable-HTTP MCP endpoint on the MCP server.')
param mcpEndpointPath string = '/mcp'

@description('Gateway path; clients call https://<gateway>/<apiPath>/mcp.')
param apiPath string = mcpServerName

@description('Application ID (or application ID URI) the MCP accepts tokens for. APIM sends its managed identity token for it; empty sends no backend token.')
param mcpEntraAppId string = ''

@description('Require an APIM subscription key from MCP clients.')
param subscriptionRequired bool = true

@minValue(0)
@description('MCP requests per minute from one client IP address. 0 turns the limit off.')
param clientIpRequestsPerMinute int = 60

@minValue(0)
@description('MCP requests per minute for one Microsoft Entra user (validated oid). Requires entraTenantId. 0 turns the limit off.')
param userRequestsPerMinute int = 0

@description('Microsoft Entra tenant whose access tokens MCP clients must present. Empty keeps subscription-key-only access.')
param entraTenantId string = ''

@description('Client application IDs accepted by the Entra token validation.')
param entraClientApplicationIds array = []

@description('Audiences accepted by the Entra token validation.')
param entraAudiences array = []

func requireHttpsBaseUrl(url string) string => startsWith(toLower(url), 'https://') && !endsWith(url, '/') && length(split(url, '/')) == 3
  ? url
  : fail('mcpServerBaseUrl must be an https:// origin without a path or trailing slash; put the endpoint path in mcpEndpointPath.')

// Only inbound policies: reading the response body would buffer it and break MCP streaming.
var backendAuthXml = empty(mcpEntraAppId) ? '' : '<authentication-managed-identity resource="${mcpEntraAppId}" />'
// The backend section streams the response instead of buffering it (MCP may answer as text/event-stream).
var policyXml = '<policies><inbound><base />${entraValidationXml(entraTenantId, entraClientApplicationIds, entraAudiences)}${clientLimitsXml(clientIpRequestsPerMinute, 0)}${userLimitsXml(entraTenantId, userRequestsPerMinute, 0)}${backendAuthXml}</inbound><backend><forward-request buffer-response="false" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'

// Streamable HTTP: POST carries JSON-RPC, GET opens the optional server stream, DELETE ends a session.
var mcpMethods = [
  'POST'
  'GET'
  'DELETE'
]

resource apimService 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimServiceName
}

resource mcpApi 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apimService
  name: mcpServerName
  properties: {
    displayName: displayName
    description: mcpDescription
    type: 'http'
    path: apiPath
    protocols: [
      'https'
    ]
    serviceUrl: requireHttpsBaseUrl(mcpServerBaseUrl)
    subscriptionRequired: subscriptionRequired
  }
}

resource mcpOperations 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [for method in mcpMethods: {
  parent: mcpApi
  name: 'mcp-${toLower(method)}'
  properties: {
    displayName: 'MCP ${method}'
    method: method
    urlTemplate: mcpEndpointPath
  }
}]

resource mcpPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: mcpApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: policyXml
  }
}

output mcpApiResourceId string = mcpApi.id
output gatewayMcpUrl string = '${apimService.properties.gatewayUrl}/${apiPath}${mcpEndpointPath}'
output managedIdentityPrincipalId string = apimService.identity.principalId

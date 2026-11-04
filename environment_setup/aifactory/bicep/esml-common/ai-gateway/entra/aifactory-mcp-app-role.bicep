// Admin-run only: assigns the AI Factory MCP app role (AiFactory.Mcp.Read) to one caller identity,
// for example the Foundry project, the native AI Gateway or a classic APIM managed identity.
//
// No pipeline deploys this file: pipelines never write Microsoft Graph. The MCP step
// (usecase_code/40-agent-factory/45-aifactory-mcp-gateway/deploy.py) prints the exact
// `az deployment group create` command for each caller. An Entra admin runs it once per new caller,
// signed in with Graph permissions AppRoleAssignment.ReadWrite.All and Application.Read.All.
// The resource group only hosts the deployment record; the assignment itself lives in Entra ID.
// Requires Bicep CLI 0.36.1 or later.
extension 'br:mcr.microsoft.com/bicep/extensions/microsoftgraph/v1.0:1.0.0'

@description('Client ID (appId) of the MCP API app registration, the aifactoryMcpEntraAppId variable.')
param mcpEntraAppId string

@description('Object (principal) ID of the managed identity that calls the MCP.')
param callerPrincipalId string

@description('Value of the app role to assign; it must be an enabled app role of the MCP app registration.')
param appRoleValue string = 'AiFactory.Mcp.Read'

resource mcpServicePrincipal 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: mcpEntraAppId
}

// Resolve the role by value so the template works for any MCP app registration.
var appRoleIds = map(filter(mcpServicePrincipal.appRoles, role => role.value == appRoleValue && role.isEnabled), role => role.id)

resource appRoleAssignment 'Microsoft.Graph/appRoleAssignedTo@v1.0' = {
  // Fails the deployment (index out of range) when the app registration has no such enabled role.
  appRoleId: appRoleIds[0]
  principalId: callerPrincipalId
  resourceId: mcpServicePrincipal.id
}

output appRoleAssignmentId string = appRoleAssignment.id
output mcpServicePrincipalId string = mcpServicePrincipal.id

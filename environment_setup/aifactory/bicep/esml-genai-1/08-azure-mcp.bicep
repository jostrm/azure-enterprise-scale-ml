targetScope = 'subscription'

metadata description = 'Deploys an isolated private Azure MCP server into an existing project resource group. Does not alter project networking or Foundry.'

import {
  inventoryTool
  requireInfrastructureSubnetId
  requirePrivateEndpointSubnetId
  requirePinnedAzureMcpImage
  requirePrivateDnsZoneResourceId
} from '../modules/azureMcpServer.bicep'

@description('Resource region, defaulting to the subscription deployment location. Must match the existing subnets.')
@minLength(1)
param location string = deployment().location

@description('Existing project resource group name in the deployment subscription; the sole Reader assignment is scoped here.')
@minLength(1)
@maxLength(90)
param projectResourceGroup string

@description('Container app name: lowercase letters, numbers and hyphens; start with a letter and end with an alphanumeric character.')
@minLength(2)
@maxLength(32)
param name string

@description('Full resource ID of an existing unused ACA subnet delegated to Microsoft.App/environments, at least /27; not a Foundry subnet.')
param infrastructureSubnetId string

@description('Full resource ID of a separate existing nondelegated private-endpoint subnet, such as the project genai PE subnet.')
param privateEndpointSubnetId string

@description('Tenant ID of the existing Entra API application.')
@minLength(36)
@maxLength(36)
param tenantId string

@description('Existing Entra API application client ID for incoming bearer-token validation; not the outgoing managed identity.')
@minLength(36)
@maxLength(36)
param entraApiApplicationClientId string

@description('Required reviewed mcr.microsoft.com/azure-sdk/azure-mcp@sha256:<64 lowercase hex characters>; no image tag or default.')
param containerImage string

@description('Exact nonempty inventory allowlist; initially only group_resource_list. No broad namespaces.')
@minLength(1)
@maxLength(1)
param allowedTools inventoryTool[]

@description('Full resource ID of the existing regional ACA private-link DNS zone, possibly in the hub subscription. The zone and its VNet links remain unchanged.')
param privateDnsZoneResourceId string

@description('True leaves the PE DNS zone group entirely to central hub policy; false explicitly associates the supplied existing zone.')
param centralDnsZoneByPolicyInHub bool

param tags object = {}

// Validate all independent references before submitting the resource-group deployment.
// fail() is supported by Bicep 0.44.1 without enabling experimental assertions.
module azureMcp '../modules/azureMcpServer.bicep' = {
  name: '${name}-azure-mcp'
  scope: resourceGroup(projectResourceGroup)
  params: {
    location: location
    name: name
    infrastructureSubnetId: requireInfrastructureSubnetId(infrastructureSubnetId)
    privateEndpointSubnetId: requirePrivateEndpointSubnetId(privateEndpointSubnetId, infrastructureSubnetId)
    tenantId: tenantId
    entraApiApplicationClientId: entraApiApplicationClientId
    containerImage: requirePinnedAzureMcpImage(containerImage)
    allowedTools: allowedTools
    privateDnsZoneResourceId: requirePrivateDnsZoneResourceId(privateDnsZoneResourceId)
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    tags: tags
  }
}

output containerAppResourceId string = azureMcp.outputs.containerAppResourceId
output identityPrincipalId string = azureMcp.outputs.identityPrincipalId
output appIdentity object = azureMcp.outputs.appIdentity
output managedEnvironmentResourceId string = azureMcp.outputs.managedEnvironmentResourceId
output defaultDomain string = azureMcp.outputs.defaultDomain
output staticIp string = azureMcp.outputs.staticIp
output mcpUrl string = azureMcp.outputs.mcpUrl
output privateEndpointResourceId string = azureMcp.outputs.privateEndpointResourceId
output readerRoleAssignmentResourceId string = azureMcp.outputs.readerRoleAssignmentResourceId
output readerRoleDefinitionResourceId string = azureMcp.outputs.readerRoleDefinitionResourceId
output deploymentInputs object = azureMcp.outputs.deploymentInputs

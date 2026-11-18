targetScope = 'resourceGroup'

@minLength(3)
@maxLength(63)
param communicationServiceName string

@description('ACS data-at-rest geography; does not establish residency for Teams, voice or model processing.')
param dataLocation string = 'Europe'

@description('Existing Agent Chat runtime managed identity object/principal ID, not its client ID.')
@minLength(36)
@maxLength(36)
param runtimePrincipalId string

@description('Explicitly approved pilot-only resource-scoped Contributor. Broad resource control, NOT a token-only role. Defaults to no assignment.')
param grantTokenBrokerContributor bool = false

resource communication 'Microsoft.Communication/communicationServices@2026-03-18' = {
  name: communicationServiceName
  location: 'global'
  tags: {
    'managed-by': 'enterprise-scale-ai-factory-agent'
    'purpose': 'attended-teams-audio-pilot'
  }
  properties: {
    dataLocation: dataLocation
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource tokenBroker 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantTokenBrokerContributor) {
  name: guid(communication.id, runtimePrincipalId, 'attended-teams-token-broker')
  scope: communication
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
  }
}

output resourceId string = communication.id
output hostName string = communication.properties.hostName

// Replaces aif_ensure_private_dns_policy_assignment: assigns the Deploy-Private-DNS-Zones initiative
// (created by esml-util/28-Initiatives.bicep) to this subscription with a system identity that may
// write private DNS zone groups. Remediation scans are left to Azure Policy's own schedule.
targetScope = 'subscription'

param location string
param assignmentParameters object

var networkContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')

resource assignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'aifactory-central-private-dns'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'AI Factory - configure central private DNS zone groups'
    policyDefinitionId: subscriptionResourceId('Microsoft.Authorization/policySetDefinitions', 'Deploy-Private-DNS-Zones')
    enforcementMode: 'Default'
    parameters: assignmentParameters
  }
}

resource networkContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, assignment.id, networkContributor)
  properties: {
    roleDefinitionId: networkContributor
    principalId: assignment.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

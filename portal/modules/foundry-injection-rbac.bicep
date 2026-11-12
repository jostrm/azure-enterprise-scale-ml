// Replaces 69a-Grant-NetworkContributor-For-Injection: the Foundry account identity needs Network
// Contributor on the VNet and the agent (aca2) subnet before the account update binds the capability host.
targetScope = 'resourceGroup'

param accountResourceId string
param vnetName string
param agentSubnetId string

var networkContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')
var accountParts = split(accountResourceId, '/')

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: last(accountParts)
  scope: resourceGroup(accountParts[2], accountParts[4])
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource agentSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: last(split(agentSubnetId, '/'))
}

resource onVnet 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vnet.id, accountResourceId, networkContributor)
  scope: vnet
  properties: {
    roleDefinitionId: networkContributor
    principalId: account.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource onSubnet 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(agentSubnet.id, accountResourceId, networkContributor)
  scope: agentSubnet
  properties: {
    roleDefinitionId: networkContributor
    principalId: account.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

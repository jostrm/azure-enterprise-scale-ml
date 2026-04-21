@description('Name of the AI Foundry account (Microsoft.CognitiveServices/accounts)')
param accountName string

@description('Optional explicit name for the account-level capability host. If empty, derived from accountName.')
param capabilityHostName string = ''

var resolvedName = !empty(capabilityHostName) ? capabilityHostName : '${replace(accountName, '-', '')}caphost'

// AI Foundry account — must already exist
#disable-next-line BCP081
resource account 'Microsoft.CognitiveServices/accounts@2025-07-01-preview' existing = {
  name: accountName
}

// Account-level capability host — required before any project-level capability host.
// When disableAgentNetworkInjection=true the platform does NOT auto-provision this,
// so it must be created explicitly via Bicep.
#disable-next-line BCP081
resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-07-01-preview' = {
  name: resolvedName
  parent: account
  properties: {
    capabilityHostKind: 'Agents'
  }
}

output accountCapabilityHostName string = accountCapabilityHost.name

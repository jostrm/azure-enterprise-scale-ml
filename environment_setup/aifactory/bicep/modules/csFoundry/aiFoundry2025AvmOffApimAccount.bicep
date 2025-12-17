targetScope = 'resourceGroup'

@description('Location for all resources.')
param location string
param foundryV22AccountOnly bool = false
@description('Base name prefix for new AI Services resources when new resources are created.')
@minLength(3)
param aiServices string = 'aiservices'

@description('Optional override for the AI Services account name. When empty a unique name is generated.')
@minLength(2)
@maxLength(64)
param aiAccountName string
@description('Optional. List of allowed FQDN.')
param allowedFqdnList array?
@description('Optional. The API properties for special APIs.')
param apiProperties object?

import { customerManagedKeyType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'

// ============================================================================
// IMPORTANT CMK REQUIREMENT:
// The Key Vault specified in customerManagedKey.keyVaultResourceId MUST have 
// enableRbacAuthorization=true (RBAC model, not Access Policy model).
// 
// If you see "AccessPolicyNotConfiguredForKeyVault" errors despite having RBAC
// assignments, run this command to enable RBAC on the Key Vault:
//   az keyvault update --name <vault-name> --enable-rbac-authorization true
//
// The User-Assigned MI specified in customerManagedKey.userAssignedIdentityResourceId
// must have the "Key Vault Crypto Service Encryption User" role assigned.
// ============================================================================
@description('Optional. The customer managed key definition.')
param customerManagedKey customerManagedKeyType?

@description('Timestamp used to generate deterministic resource names (format yyyyMMddHHmmss).')
param deploymentTimestamp string = utcNow('yyyyMMddHHmmss')

@description('Name prefix for the default project.')
param firstProjectName string = 'project'

@description('Description for the default project.')
param projectDescription string = 'A project for the AI Foundry account with network secured deployed Agent'

@description('Display name for the default project.')
param displayName string = 'network secured agent project'

@description('Resource ID of the subnet used for private endpoints.')
param privateEndpointSubnetResourceId string

@description('Resource ID of the subnet used for agent network injection. Leave empty to skip injection.')
param agentSubnetResourceId string = ''

@description('Disable agent network injection even when an agent subnet is provided.')
param disableAgentNetworkInjection bool = false

@description('Existing AI Search service resource ID. Leave empty to create a new instance.')
param aiSearchResourceId string = ''

@description('Existing primary Storage account resource ID. Leave empty to create a new instance.')
param azureStorageAccountResourceId string = ''

@description('Existing secondary Storage account resource ID. Leave empty to create a new instance for capability host workloads.')
param azureStorageAccountResourceIdSecondary string = ''

@description('Existing Cosmos DB account resource ID. Leave empty to create a new instance.')
param azureCosmosDBAccountResourceId string = ''

@description('Existing API Management resource ID (for optional private endpoint).')
param apiManagementResourceId string = ''

@description('Object mapping Private DNS zone names to their resource group. Leave value empty to create the zone in the current resource group.')
param existingDnsZones object = {
  'privatelink.services.ai.azure.com': ''
  'privatelink.openai.azure.com': ''
  'privatelink.cognitiveservices.azure.com': ''
  'privatelink.search.windows.net': ''
  'privatelink.blob.${environment().suffixes.storage}': ''
  'privatelink.documents.azure.com': ''
  'privatelink.azure-api.net': ''
}

@description('Private DNS zones configuration emitted from the networking landing zone.')
param privateLinksDnsZones object = {}

@description('Allow public HTTP access while traffic flows through perimeter controls.')
param allowPublicAccessWhenBehindVnet bool = false

@description('Enable public access to AI Services endpoints.')
param enablePublicGenAIAccess bool = false

@description('IP addresses or CIDR ranges allowed through network ACLs when public access is enabled.')
param ipAllowList array = []

@description('Enable capability host configuration for the project.')
param enableCapabilityHost bool = true

@description('Name suffix for the capability host resource.')
param projectCapHost string = 'caphostproj'

@description('Array of user object IDs for Cognitive Services RBAC assignments.')
param userRoleObjectIds array = []

@description('Array of service principal IDs for Cognitive Services RBAC assignments.')
param servicePrincipalIds array = []

@description('Treat entries in userRoleObjectIds as Azure AD groups instead of users.')
param useAdGroups bool = false

@description('Optional list of additional model deployments to create. Expected shape matches Microsoft.CognitiveServices/accounts/deployments properties.')
param extraModelDeployments array = []

@description('Model name for the default deployment.')
param modelName string = 'gpt-4o'

@description('Model provider format for the default deployment.')
param modelFormat string = 'OpenAI'

@description('Model version for the default deployment.')
param modelVersion string = '2024-11-20'

@description('Model SKU for the default deployment.')
param modelSkuName string = 'GlobalStandard'

@description('Tokens per minute capacity for the default model deployment.')
param modelCapacity int = 30

@description('Enable Cosmos DB integration.')
param enableCosmosDb bool = true

@description('Enable AI Search integration.')
param enableAISearch bool = true

@description('Enable creation of a default project.')
param enableProject bool = true

@description('Bypass Private DNS zone linking when central DNS zones are managed in a hub.')
param centralDnsZoneByPolicyInHub bool = false

@description('Restrict outbound network access for the AI Services account.')
param restrictOutboundNetworkAccess bool = true

@description('Optional tags applied to newly created resources.')
param tags object = {}

@description('SKU tier for the AI Services account.')
@allowed([
  'S0'
  'S'
  'S1'
  'S2'
  'S3'
  'S4'
  'S5'
  'S6'
  'S7'
  'S8'
  'S9'
])
param aiAccountSku string = 'S0'

//var uniqueSuffix = substring(uniqueString('${resourceGroup().id}-${deploymentTimestamp}'), 0, 4)
//var fallbackAccountName = take(toLower('${aiServices}${uniqueSuffix}'), 63)
//var overrideAccountName = take(toLower(aiAccountName), 63)
//var accountName = length(overrideAccountName) >= 2 ? overrideAccountName : fallbackAccountName
var accountName = aiAccountName
var agentNetworkInjectionEnabled = !disableAgentNetworkInjection && !empty(agentSubnetResourceId)


var ipRules = [for ip in ipAllowList: {
  value: contains(ip, '/') ? toLower(ip) : '${toLower(ip)}/24'
}]
var networkAclVirtualNetworkRules = concat(
  !empty(privateEndpointSubnetResourceId) ? [
    {
      id: privateEndpointSubnetResourceId
      ignoreMissingVnetServiceEndpoint: true // allow listed VNet without requiring service endpoint
    }
  ] : [],
  agentNetworkInjectionEnabled ? [
    {
      id: agentSubnetResourceId
      ignoreMissingVnetServiceEndpoint: true
    }
  ] : []
)
var hasNetworkAcls = !empty(ipRules) || enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet || !empty(networkAclVirtualNetworkRules)
var networkAcls = hasNetworkAcls ? {
  defaultAction: enablePublicGenAIAccess && empty(ipRules) ? 'Allow' : 'Deny'
  virtualNetworkRules: networkAclVirtualNetworkRules
  ipRules: ipRules
  bypass:'AzureServices'
} : null
var publicNetworkAccess = (enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet) ? 'Enabled' : 'Disabled'

resource cMKKeyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = if (!empty(customerManagedKey.?keyVaultResourceId)) {
  name: last(split(customerManagedKey.?keyVaultResourceId!, '/'))
  scope: resourceGroup(
    split(customerManagedKey.?keyVaultResourceId!, '/')[2],
    split(customerManagedKey.?keyVaultResourceId!, '/')[4]
  )

}
resource cMKKey 'Microsoft.KeyVault/vaults/keys@2024-11-01' existing = if (!empty(customerManagedKey.?keyVaultResourceId) && !empty(customerManagedKey.?keyName)) {
  name: '${cMKKeyVault.name}/${customerManagedKey.?keyName!}'
  scope: resourceGroup(
    split(customerManagedKey.?keyVaultResourceId!, '/')[2],
    split(customerManagedKey.?keyVaultResourceId!, '/')[4]
  )
}
resource cMKUserAssignedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2025-01-31-preview' existing = if (!empty(customerManagedKey.?userAssignedIdentityResourceId)) {
  name: last(split(customerManagedKey.?userAssignedIdentityResourceId!, '/'))
  scope: resourceGroup(
    split(customerManagedKey.?userAssignedIdentityResourceId!, '/')[2],
    split(customerManagedKey.?userAssignedIdentityResourceId!, '/')[4]
  )
}

// Remove trailing slash from Key Vault URI for AI Services encryption
#disable-next-line BCP318
var cmkKeyVaultUriRaw = !empty(customerManagedKey) ? cMKKeyVault!.properties.vaultUri : ''
var cmkKeyVaultUri = !empty(cmkKeyVaultUriRaw) && length(cmkKeyVaultUriRaw) > 1 && endsWith(cmkKeyVaultUriRaw, '/') 
  ? substring(cmkKeyVaultUriRaw, 0, max(0, length(cmkKeyVaultUriRaw) - 1)) 
  : cmkKeyVaultUriRaw

#disable-next-line BCP036
resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = if(foundryV22AccountOnly){
  name: accountName
  kind: 'AIServices'
  location: location
  tags: tags
  sku: {
    name: aiAccountSku
  }
  identity: !empty(customerManagedKey) ? {
    // When using CMK, need both System-Assigned (for general operations) and User-Assigned (for CMK access)
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${customerManagedKey!.userAssignedIdentityResourceId}': {}
    }
  } : {
    type: 'SystemAssigned'
  }
  properties: {
    allowedFqdnList: allowedFqdnList
    apiProperties: apiProperties
    allowProjectManagement: true
    customSubDomainName: accountName
    networkAcls: networkAcls
    publicNetworkAccess: publicNetworkAccess
    disableLocalAuth: false
    #disable-next-line BCP036
    networkInjections: agentNetworkInjectionEnabled ? [
      {
        scenario: 'agent'
        subnetArmId: agentSubnetResourceId
        useMicrosoftManagedNetwork: false
      }
    ] : null
    restrictOutboundNetworkAccess: restrictOutboundNetworkAccess
    dynamicThrottlingEnabled: false
    encryption: !empty(customerManagedKey)
      ? {
          keySource: 'Microsoft.KeyVault'
          keyVaultProperties: {
            #disable-next-line BCP318
            identityClientId: !empty(customerManagedKey) && !empty(cMKUserAssignedIdentity) ? cMKUserAssignedIdentity.properties.clientId : null
            #disable-next-line BCP318
            keyName: !empty(customerManagedKey) ? customerManagedKey!.keyName : ''
            #disable-next-line BCP318
            keyVaultUri: cmkKeyVaultUri
            keyVersion: (!empty(customerManagedKey) && !empty(customerManagedKey.?keyVersion ?? ''))
              ? customerManagedKey!.keyVersion
              : (!empty(customerManagedKey) ? last(split(cMKKey!.properties.keyUriWithVersion, '/')) : '')
          }
        }
      : null
  }
}

#disable-next-line BCP318
var aiAccountId = foundryV22AccountOnly ? aiAccount.id : ''
#disable-next-line BCP318
var aiAccountEndpoint = foundryV22AccountOnly ? aiAccount.properties.endpoint : ''
#disable-next-line BCP318
var aiAccountPrincipalId = foundryV22AccountOnly? aiAccount.identity.principalId: ''

// ============== CMK RBAC ASSIGNMENTS ==============
// Assign Key Vault Crypto Service Encryption User role to AI Account System-Assigned MI
// This allows the AI Account to access the CMK for encryption at rest
module kvRbacForAiAccount '../kvRbacSingleAssignment.bicep' = if (foundryV22AccountOnly && !empty(customerManagedKey)) {
  name: take('kvRbac-ai-${accountName}', 64)
  scope: resourceGroup(
    split(customerManagedKey.?keyVaultResourceId!, '/')[2],
    split(customerManagedKey.?keyVaultResourceId!, '/')[4]
  )
  params: {
    keyVaultName: cMKKeyVault.name
    principalId: aiAccountPrincipalId
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6' // Key Vault Crypto Service Encryption User
    assignmentName: 'cmk-rbac-ai-${accountName}'
    principalType: 'ServicePrincipal'
  }
}

// Assign Key Vault Crypto Service Encryption User role to Cosmos DB global service principal
// This is required for Cosmos DB encryption when using CMK
// Cosmos DB global principal ID: a232010e-820c-4083-83bb-3ace5fc29d0b
module kvRbacForCosmosDb '../kvRbacSingleAssignment.bicep' = if (foundryV22AccountOnly && !empty(customerManagedKey) && enableCosmosDb) {
  name: take('kvRbac-cosmos-${accountName}', 64)
  scope: resourceGroup(
    split(customerManagedKey.?keyVaultResourceId!, '/')[2],
    split(customerManagedKey.?keyVaultResourceId!, '/')[4]
  )
  params: {
    keyVaultName: cMKKeyVault.name
    principalId: 'a232010e-820c-4083-83bb-3ace5fc29d0b' // Cosmos DB global service principal
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6' // Key Vault Crypto Service Encryption User
    assignmentName: 'cmk-rbac-cosmos-${accountName}'
    principalType: 'ServicePrincipal'
  }
}

@description('The name of the cognitive services account.')
output aiAccountName string = accountName

@description('The resource ID of the cognitive services account.')
output aiAccountId string = aiAccountId

@description('The service endpoint of the cognitive services account.')
output aiAccountEndpoint string = aiAccountEndpoint

@description('The principal ID of the system assigned identity.')
output aiAccountPrincipalId string = aiAccountPrincipalId

targetScope = 'resourceGroup'

@description('Location for all resources.')
param location string
param foundryV22AccountOnly bool = false

@description('Optional override for the AI Services account name. When empty a unique name is generated.')
param aiAccountName string = ''
@description('Optional. List of allowed FQDN.')
param allowedFqdnList array?

@description('Optional. The API properties for special APIs.')
param apiProperties object?
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

@description('Object mapping private DNS zone names to either a full resource ID (preferred) or a legacy resource group name in the current subscription. Leave value empty to deploy a new zone alongside this module.')
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

@description('Subscription ID for the central private DNS zones.')
param privDnsSubscription string = ''

@description('Resource group name for the central private DNS zones.')
param privDnsResourceGroupName string = ''

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
param useAdGroups bool = true

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

@description('Enable Customer-Managed Key (CMK) encryption for the AI Account.')
param cmk bool = false

@description('CMK Key name in the Key Vault.')
param cmkKeyName string = ''

@description('CMK Key version in the Key Vault.')
param cmkKeyVersion string = ''

@description('CMK Key Vault resource ID.')
param cmkKeyVaultResourceId string = ''

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

var uniqueSuffix = substring(uniqueString('${resourceGroup().id}-${deploymentTimestamp}'), 0, 4)


var storagePassedIn = !empty(azureStorageAccountResourceId)
var storageParts = storagePassedIn ? split(azureStorageAccountResourceId, '/') : split('', '/')
var storageSubscriptionId = storagePassedIn ? storageParts[2] : subscription().subscriptionId
var storageResourceGroupName = storagePassedIn ? storageParts[4] : resourceGroup().name
var storageAccountName = storagePassedIn ? last(storageParts) : take(replace(toLower('${aiAccountName}${uniqueSuffix}storage'), '-', ''), 24)

var storageSecondPassedIn = !empty(azureStorageAccountResourceIdSecondary)
var storageSecondParts = storageSecondPassedIn ? split(azureStorageAccountResourceIdSecondary, '/') : split('', '/')
var storageSecondSubscriptionId = storageSecondPassedIn ? storageSecondParts[2] : subscription().subscriptionId
var storageSecondResourceGroupName = storageSecondPassedIn ? storageSecondParts[4] : resourceGroup().name
var storageAccountNameSecondary = storageSecondPassedIn
  ? last(storageSecondParts)
  : take(replace(toLower('${aiAccountName}${uniqueSuffix}stor2'), '-', ''), 24)

var searchPassedIn = !empty(aiSearchResourceId)
var searchParts = searchPassedIn ? split(aiSearchResourceId, '/') : split('', '/')
var aiSearchSubscriptionId = searchPassedIn ? searchParts[2] : subscription().subscriptionId
var aiSearchServiceResourceGroupName = searchPassedIn ? searchParts[4] : resourceGroup().name
var aiSearchName = searchPassedIn ? last(searchParts) : take(replace(toLower('${aiAccountName}${uniqueSuffix}search'), '-', ''), 24)

var cosmosPassedIn = !empty(azureCosmosDBAccountResourceId)
var cosmosParts = cosmosPassedIn ? split(azureCosmosDBAccountResourceId, '/') : split('', '/')
var cosmosSubscriptionId = cosmosPassedIn ? cosmosParts[2] : subscription().subscriptionId
var cosmosResourceGroupName = cosmosPassedIn ? cosmosParts[4] : resourceGroup().name
var cosmosAccountName = cosmosPassedIn ? last(cosmosParts) : take(replace(toLower('${aiAccountName}${uniqueSuffix}cosmosdb'), '-', ''), 44)

var apiManagementProvided = !empty(apiManagementResourceId)
var apiManagementParts = apiManagementProvided ? split(apiManagementResourceId, '/') : split('', '/')
var apiManagementSubscriptionId = apiManagementProvided ? apiManagementParts[2] : ''
var apiManagementResourceGroupName = apiManagementProvided ? apiManagementParts[4] : ''
var apiManagementName = apiManagementProvided ? last(apiManagementParts) : ''

var privateEndpointSubnetSegments = split(privateEndpointSubnetResourceId, '/subnets/')
var virtualNetworkId = privateEndpointSubnetSegments[0]
var privateEndpointSubnetName = privateEndpointSubnetSegments[1]
var vnetSegments = split(virtualNetworkId, '/')
var virtualNetworkName = vnetSegments[length(vnetSegments) - 1]
var virtualNetworkResourceGroupName = vnetSegments[4]
var virtualNetworkSubscriptionId = vnetSegments[2]

var agentNetworkInjectionEnabled = !disableAgentNetworkInjection && !empty(agentSubnetResourceId)

var ipRules = [for ip in ipAllowList: {
  value: contains(ip, '/') ? toLower(ip) : '${toLower(ip)}/32'
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
var storageInCurrentRg = storageResourceGroupName == resourceGroup().name && storageSecondResourceGroupName == resourceGroup().name
var searchInCurrentRg = aiSearchServiceResourceGroupName == resourceGroup().name
var cosmosInCurrentRg = cosmosResourceGroupName == resourceGroup().name

var defaultDeploymentName = take('${modelName}-${uniqueSuffix}', 64)

#disable-next-line BCP036
resource aiAccountCreate 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = if(foundryV22AccountOnly){
  name: aiAccountName
  kind: 'AIServices'
  location: location
  tags: tags
  sku: {
    name: aiAccountSku
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowedFqdnList: allowedFqdnList
    apiProperties: apiProperties
    allowProjectManagement: enableProject
    //defaultProject: enableProject ? projectName : null
    customSubDomainName: aiAccountName
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
  }
}

// Reference to existing account when CMK is NOT enabled
// When CMK is enabled, aiAccountUpdateWithCMK will handle the account update
resource aiAccountExisting 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = if(!foundryV22AccountOnly && !cmk) {
  name: aiAccountName
}

// Key Vault reference for CMK
resource cMKKeyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = if (!foundryV22AccountOnly && cmk && !empty(cmkKeyVaultResourceId)) {
  name: last(split(cmkKeyVaultResourceId, '/'))
  scope: resourceGroup(
    split(cmkKeyVaultResourceId, '/')[2],
    split(cmkKeyVaultResourceId, '/')[4]
  )
}

// Key Vault Key reference for getting latest version if not specified
resource cMKKey 'Microsoft.KeyVault/vaults/keys@2024-11-01' existing = if (!foundryV22AccountOnly && cmk && !empty(cmkKeyVaultResourceId) && !empty(cmkKeyName)) {
  name: '${last(split(cmkKeyVaultResourceId, '/'))}/${cmkKeyName}'
  scope: resourceGroup(
    split(cmkKeyVaultResourceId, '/')[2],
    split(cmkKeyVaultResourceId, '/')[4]
  )
}

// Remove trailing slash from Key Vault URI
#disable-next-line BCP318
var cmkKeyVaultUriRaw = (!foundryV22AccountOnly && cmk && !empty(cmkKeyVaultResourceId)) ? cMKKeyVault.properties.vaultUri : ''
var cmkKeyVaultUri = !empty(cmkKeyVaultUriRaw) && length(cmkKeyVaultUriRaw) > 1 && endsWith(cmkKeyVaultUriRaw, '/') 
  ? substring(cmkKeyVaultUriRaw, 0, max(0, length(cmkKeyVaultUriRaw) - 1)) 
  : cmkKeyVaultUriRaw

// Use provided key version or get latest version from Key Vault
var cmkKeyVersionToUse = (!foundryV22AccountOnly && cmk && !empty(cmkKeyName)) 
  ? (empty(cmkKeyVersion) ? last(split(cMKKey!.properties.keyUriWithVersion, '/')) : cmkKeyVersion)
  : ''

// Second deployment: Update existing AI Account with CMK encryption
// This runs when foundryV22AccountOnly=false (after 3 minute RBAC propagation delay)
#disable-next-line BCP036
resource aiAccountUpdateWithCMK 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = if(!foundryV22AccountOnly && cmk) {
  name: aiAccountName
  kind: 'AIServices'
  location: location
  tags: tags
  sku: {
    name: aiAccountSku
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowedFqdnList: allowedFqdnList
    apiProperties: apiProperties
    allowProjectManagement: true
    customSubDomainName: aiAccountName
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
    // NOW configure encryption - RBAC has had 3 minutes to propagate
    encryption: {
      keySource: 'Microsoft.KeyVault'
      keyVaultProperties: {
        // System-Assigned MI is used automatically
        keyName: cmkKeyName
        keyVersion: cmkKeyVersionToUse
        keyVaultUri: cmkKeyVaultUri
      }
    }
  }
  // No dependsOn needed - updating existing account by name automatically
}

// Use the CMK-updated account if CMK is enabled, otherwise use the existing reference
var aiAccountResourceId = foundryV22AccountOnly ? aiAccountCreate.id : (cmk ? aiAccountUpdateWithCMK.id : aiAccountExisting.id)

resource aiAccountDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  name: '${aiAccountName}/${defaultDeploymentName}'
  properties: {
    model: {
      name: modelName
      format: modelFormat
      version: modelVersion
    }
  }
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  dependsOn: [
    // Wait for account to be ready based on deployment scenario
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
  ]
}

@batchSize(1)
resource aiAccountDeploymentsAdditional 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = [for (deployment, index) in extraModelDeployments: {
  name: '${aiAccountName}/${take(string(deployment.name ?? 'deployment${index}'), 64)}'
  properties: {
    model: deployment.model
    raiPolicyName: deployment.raiPolicyName
    versionUpgradeOption: deployment.versionUpgradeOption
  }
  sku: deployment.sku ?? {
    name: modelSkuName
    capacity: modelCapacity
  }
  dependsOn: [
    // Wait for account to be ready based on deployment scenario
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
    aiAccountDeployment
  ]
}]


module projectModule 'aiFoundry2025project.bicep' = if (enableProject) {
  name: take('aifoundry-project-${uniqueSuffix}', 64)
  params: {
    name: firstProjectName
    location: location
    cosmosDBname: enableCosmosDb ? cosmosAccountName : ''
    storageName: storageAccountName
    storageName2: storageAccountNameSecondary
    aiFoundryV2Name: aiAccountName
    aiSearchName: enableAISearch ? aiSearchName : ''
    enablePublicAccessWithPerimeter: allowPublicAccessWhenBehindVnet
    defaultProjectName: firstProjectName
    defaultProjectDisplayName: displayName
    defaultProjectDescription: projectDescription
  }
  dependsOn: [
    // When foundryV22AccountOnly=true: depends on aiAccountCreate (but project doesn't deploy)
    // When foundryV22AccountOnly=false with CMK: depends on aiAccountUpdateWithCMK
    // When foundryV22AccountOnly=false without CMK: depends on aiAccountExisting
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
  ]
}

#disable-next-line BCP318
var projectPrincipalId = enableProject ? projectModule.outputs.projectPrincipalId : ''
#disable-next-line BCP318
var projectWorkspaceRawId = enableProject ? string(projectModule.outputs.projectWorkspaceId) : ''
var projectWorkspaceGuid = enableProject && !empty(projectWorkspaceRawId)
  ? format('{0}-{1}-{2}-{3}-{4}', substring(projectWorkspaceRawId, 0, 8), substring(projectWorkspaceRawId, 8, 4), substring(projectWorkspaceRawId, 12, 4), substring(projectWorkspaceRawId, 16, 4), substring(projectWorkspaceRawId, 20, 12))
  : ''


var projectCapHostUnique = '${projectCapHost}-${uniqueSuffix}'

module capabilityHost 'aiFoundry2025caphost.bicep' = if (enableCapabilityHost && enableProject && enableAISearch && enableCosmosDb) {
  name: take('aifoundry-caphost-${uniqueSuffix}', 64)
  params: {
    #disable-next-line BCP318
    cosmosDBConnection: string(projectModule.outputs.cosmosDBConnection)
    #disable-next-line BCP318
    azureStorageConnection: string(projectModule.outputs.azureStorageConnection)
    #disable-next-line BCP318
    aiSearchConnection: string(projectModule.outputs.aiSearchConnection)
    #disable-next-line BCP318
    projectName: projectModule.outputs.projectName
    accountName: aiAccountName
    projectCapHostName: projectCapHostUnique
  }
  dependsOn: [
    projectModule
  ]
}

var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAIContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'
var openAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var storageFileDataSMBPrivilegedContributorRoleId = '0c867c2a-1d8c-454a-a3db-ab2ea1bdc8bb'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

module aiFoundryRbac 'aiFoundry2025rbac.bicep' = if (!empty(userRoleObjectIds) || !empty(servicePrincipalIds) || enableProject) {
  name: take('aifoundry-rbac-${uniqueSuffix}', 64)
  params: {
    userObjectIds: userRoleObjectIds
    servicePrincipalIds: servicePrincipalIds
    projectPrincipalId: projectPrincipalId
    cognitiveServicesAccountName: aiAccountName
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    useAdGroups: useAdGroups
  }
  dependsOn: [
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
    ...(enableProject ? [projectModule] : [])
  ]
}

module searchRbac 'rbacAISearchForAIFv2.bicep' = if (enableAISearch && searchInCurrentRg) {
  name: take('aifoundry-rbacsearch-${uniqueSuffix}', 64)
  params: {
    aiSearchName: aiSearchName
    aiFoundryAccountName: aiAccountName
    projectPrincipalId: projectPrincipalId
    searchServiceContributorRoleId: searchServiceContributorRoleId
    searchIndexDataReaderRoleId: searchIndexDataReaderRoleId
    searchIndexDataContributorRoleId: searchIndexDataContributorRoleId
  }
  dependsOn: [
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
    ...(enableProject ? [projectModule] : [])
  ]
}

module storageRbac 'rbacAIStorageAccountsForAIFv2.bicep' = if (storageInCurrentRg && enableProject) {
  name: take('aifoundry-rbacstorage-${uniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccountName
    storageAccountName2: storageAccountNameSecondary
    aiFoundryAccountName: aiAccountName
    projectPrincipalId: projectPrincipalId
    storageBlobDataContributorRoleId: storageBlobDataContributorRoleId
    storageFileDataPrivilegedContributorRoleId: storageFileDataPrivilegedContributorRoleId
    storageFileDataSMBPrivilegedContributorRoleId: storageFileDataSMBPrivilegedContributorRoleId
    storageQueueDataContributorRoleId: storageQueueDataContributorRoleId
  }
  dependsOn: [
    ...(foundryV22AccountOnly ? [aiAccountCreate] : (cmk ? [aiAccountUpdateWithCMK] : [aiAccountExisting]))
    ...(enableProject ? [projectModule] : [])
  ]
}

module caphostRbacPre 'aiFoundry2025caphostRbac1.bicep' = if (enableCapabilityHost && enableProject && enableCosmosDb && cosmosInCurrentRg) {
  name: take('aifoundry-rbaccap-pre-${uniqueSuffix}', 64)
  params: {
    cosmosAccountName: cosmosAccountName
    projectPrincipalId: projectPrincipalId
  }
  dependsOn: [
    projectModule
  ]
}

module caphostRbacPost 'aiFoundry2025caphostRbac2.bicep' = if (enableCapabilityHost && enableProject && enableCosmosDb && cosmosInCurrentRg && storageInCurrentRg) {
  name: take('aifoundry-rbaccap-post-${uniqueSuffix}', 64)
  params: {
    cosmosAccountName: cosmosAccountName
    projectPrincipalId: projectPrincipalId
    storageName: storageAccountName
    projectWorkspaceId: projectWorkspaceGuid
  }
  dependsOn: [
    capabilityHost
    caphostRbacPre
  ]
}

var aiAccountIdValue = aiAccountResourceId
var aiAccountEndpointValue = !foundryV22AccountOnly ? reference(aiAccountResourceId, '2025-04-01-preview', 'full').properties.endpoint : ''
var aiAccountPrincipalIdValue = !foundryV22AccountOnly ? reference(aiAccountResourceId, '2025-04-01-preview', 'full').identity.principalId : ''

var storageAccountSubscriptionId = storageSubscriptionId
var storageAccountResourceGroup = storageResourceGroupName
var storageAccountSecondarySubscriptionId = storageSecondSubscriptionId
var storageAccountSecondaryResourceGroup = storageSecondResourceGroupName
var cosmosAccountSubscriptionId = cosmosSubscriptionId
var cosmosAccountResourceGroup = cosmosResourceGroupName
var aiSearchSubscriptionEffective = aiSearchSubscriptionId
var aiSearchResourceGroupEffective = aiSearchServiceResourceGroupName

@description('The name of the cognitive services account.')
output aiAccountName string = !foundryV22AccountOnly? aiAccountName : ''

@description('The resource ID of the cognitive services account.')
output aiAccountId string =  !foundryV22AccountOnly? aiAccountIdValue : ''

@description('The service endpoint of the cognitive services account.')
output aiAccountEndpoint string = !foundryV22AccountOnly? aiAccountEndpointValue : ''

@description('The principal ID of the system assigned identity.')
output aiAccountPrincipalId string = !foundryV22AccountOnly? aiAccountPrincipalIdValue : ''

@description('Indicates whether the default project was deployed.')
output aiFoundryProjectDeployed bool = enableProject

@description('Debug: Shows if CMK update was attempted')
output cmkUpdateAttempted bool = !foundryV22AccountOnly && cmk

@description('Debug: CMK configuration parameters')
output cmkDebugInfo object = {
  cmkEnabled: cmk
  cmkKeyName: cmkKeyName
  cmkKeyVersionProvided: cmkKeyVersion
  cmkKeyVersionUsed: cmkKeyVersionToUse
  cmkKeyVaultResourceId: cmkKeyVaultResourceId
  foundryV22AccountOnly: foundryV22AccountOnly
  shouldUpdateWithCMK: !foundryV22AccountOnly && cmk
}

@description('The name of the AI Foundry project.')
#disable-next-line BCP318
output projectNameOutput string = enableProject ? string(projectModule.outputs.projectName) : ''

@description('The resource ID of the AI Foundry project.')
#disable-next-line BCP318
output projectId string = enableProject ? string(projectModule.outputs.projectId) : ''

@description('The principal ID of the AI Foundry project managed identity.')
output projectPrincipalId string = projectPrincipalId

@description('Formatted project workspace ID (GUID).')
output projectWorkspaceGuid string = projectWorkspaceGuid

@description('Primary storage account information.')
output storageAccount object = {
  name: storageAccountName
  subscriptionId: storageAccountSubscriptionId
  resourceGroup: storageAccountResourceGroup
}

@description('Secondary storage account information.')
output storageAccountSecondary object = {
  name: storageAccountNameSecondary
  subscriptionId: storageAccountSecondarySubscriptionId
  resourceGroup: storageAccountSecondaryResourceGroup
}

@description('Cosmos DB account information.')
output cosmosAccount object = enableCosmosDb ? {
  name: cosmosAccountName
  subscriptionId: cosmosAccountSubscriptionId
  resourceGroup: cosmosAccountResourceGroup
} : {
  name: ''
  subscriptionId: ''
  resourceGroup: ''
}

@description('AI Search service information.')
output aiSearchService object = enableAISearch ? {
  name: aiSearchName
  subscriptionId: aiSearchSubscriptionEffective
  resourceGroup: aiSearchResourceGroupEffective
} : {
  name: ''
  subscriptionId: ''
  resourceGroup: ''
}

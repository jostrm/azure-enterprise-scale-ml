targetScope = 'resourceGroup'

@description('Location for all resources.')
param location string

@description('Base name prefix for new AI Services resources when new resources are created.')
@minLength(3)
param aiServices string = 'aiservices'

@description('Optional override for the AI Services account name. When empty a unique name is generated.')
param aiAccountName string = ''

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

var uniqueSuffix = substring(uniqueString('${resourceGroup().id}-${deploymentTimestamp}'), 0, 4)
var baseAccountName = empty(aiAccountName) ? toLower('${aiServices}${uniqueSuffix}') : toLower(aiAccountName)
var accountName = take(baseAccountName, 63)
var projectName = toLower('${firstProjectName}${uniqueSuffix}')

var storagePassedIn = !empty(azureStorageAccountResourceId)
var storageParts = storagePassedIn ? split(azureStorageAccountResourceId, '/') : split('', '/')
var storageSubscriptionId = storagePassedIn ? storageParts[2] : subscription().subscriptionId
var storageResourceGroupName = storagePassedIn ? storageParts[4] : resourceGroup().name
var storageAccountName = storagePassedIn ? last(storageParts) : take(replace(toLower('${aiServices}${uniqueSuffix}storage'), '-', ''), 24)

var storageSecondPassedIn = !empty(azureStorageAccountResourceIdSecondary)
var storageSecondParts = storageSecondPassedIn ? split(azureStorageAccountResourceIdSecondary, '/') : split('', '/')
var storageSecondSubscriptionId = storageSecondPassedIn ? storageSecondParts[2] : subscription().subscriptionId
var storageSecondResourceGroupName = storageSecondPassedIn ? storageSecondParts[4] : resourceGroup().name
var storageAccountNameSecondary = storageSecondPassedIn
  ? last(storageSecondParts)
  : take(replace(toLower('${aiServices}${uniqueSuffix}stor2'), '-', ''), 24)

var searchPassedIn = !empty(aiSearchResourceId)
var searchParts = searchPassedIn ? split(aiSearchResourceId, '/') : split('', '/')
var aiSearchSubscriptionId = searchPassedIn ? searchParts[2] : subscription().subscriptionId
var aiSearchServiceResourceGroupName = searchPassedIn ? searchParts[4] : resourceGroup().name
var aiSearchName = searchPassedIn ? last(searchParts) : take(replace(toLower('${aiServices}${uniqueSuffix}search'), '-', ''), 24)

var cosmosPassedIn = !empty(azureCosmosDBAccountResourceId)
var cosmosParts = cosmosPassedIn ? split(azureCosmosDBAccountResourceId, '/') : split('', '/')
var cosmosSubscriptionId = cosmosPassedIn ? cosmosParts[2] : subscription().subscriptionId
var cosmosResourceGroupName = cosmosPassedIn ? cosmosParts[4] : resourceGroup().name
var cosmosAccountName = cosmosPassedIn ? last(cosmosParts) : take(replace(toLower('${aiServices}${uniqueSuffix}cosmosdb'), '-', ''), 44)

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
var hasNetworkAcls = !empty(ipRules) || enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet
var networkAcls = hasNetworkAcls ? {
  defaultAction: enablePublicGenAIAccess && empty(ipRules) ? 'Allow' : 'Deny'
  virtualNetworkRules: []
  ipRules: ipRules
} : null
var publicNetworkAccess = (enablePublicGenAIAccess || allowPublicAccessWhenBehindVnet) ? 'Enabled' : 'Disabled'

var aiServicesDnsZoneName = 'privatelink.services.ai.azure.com'
var openAiDnsZoneName = 'privatelink.openai.azure.com'
var cognitiveServicesDnsZoneName = 'privatelink.cognitiveservices.azure.com'
var searchDnsZoneName = 'privatelink.search.windows.net'
var storageDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
var cosmosDnsZoneName = 'privatelink.documents.azure.com'
var apiManagementDnsZoneName = 'privatelink.azure-api.net'

var dnsZoneNames = [
  aiServicesDnsZoneName
  openAiDnsZoneName
  cognitiveServicesDnsZoneName
  searchDnsZoneName
  storageDnsZoneName
  cosmosDnsZoneName
  apiManagementDnsZoneName
]

var servicesAiZoneFromLanding = contains(privateLinksDnsZones, 'servicesai') ? string(privateLinksDnsZones.servicesai.id) : ''
var openAiZoneFromLanding = contains(privateLinksDnsZones, 'openai') ? string(privateLinksDnsZones.openai.id) : ''
var cognitiveServicesZoneFromLanding = contains(privateLinksDnsZones, 'cognitiveservices') ? string(privateLinksDnsZones.cognitiveservices.id) : ''
var searchZoneFromLanding = contains(privateLinksDnsZones, 'searchService') ? string(privateLinksDnsZones.searchService.id) : ''
var storageZoneFromLanding = contains(privateLinksDnsZones, 'blob') ? string(privateLinksDnsZones.blob.id) : ''
var cosmosZoneFromLanding = contains(privateLinksDnsZones, 'cosmosdbnosql') ? string(privateLinksDnsZones.cosmosdbnosql.id) : ''
var apiManagementZoneFromLanding = contains(privateLinksDnsZones, 'azureApiManagement') ? string(privateLinksDnsZones.azureApiManagement.id) : ''

var aiServicesDnsZoneId = !empty(servicesAiZoneFromLanding)
  ? servicesAiZoneFromLanding
  : (empty(string(existingDnsZones[aiServicesDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', aiServicesDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[aiServicesDnsZoneName]), 'Microsoft.Network/privateDnsZones', aiServicesDnsZoneName))
var openAiDnsZoneId = !empty(openAiZoneFromLanding)
  ? openAiZoneFromLanding
  : (empty(string(existingDnsZones[openAiDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', openAiDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[openAiDnsZoneName]), 'Microsoft.Network/privateDnsZones', openAiDnsZoneName))
var cognitiveServicesDnsZoneId = !empty(cognitiveServicesZoneFromLanding)
  ? cognitiveServicesZoneFromLanding
  : (empty(string(existingDnsZones[cognitiveServicesDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', cognitiveServicesDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[cognitiveServicesDnsZoneName]), 'Microsoft.Network/privateDnsZones', cognitiveServicesDnsZoneName))

var searchDnsZoneId = !empty(searchZoneFromLanding)
  ? searchZoneFromLanding
  : (empty(string(existingDnsZones[searchDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', searchDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[searchDnsZoneName]), 'Microsoft.Network/privateDnsZones', searchDnsZoneName))
var storageDnsZoneId = !empty(storageZoneFromLanding)
  ? storageZoneFromLanding
  : (empty(string(existingDnsZones[storageDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', storageDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[storageDnsZoneName]), 'Microsoft.Network/privateDnsZones', storageDnsZoneName))
var cosmosDnsZoneId = !empty(cosmosZoneFromLanding)
  ? cosmosZoneFromLanding
  : (empty(string(existingDnsZones[cosmosDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', cosmosDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[cosmosDnsZoneName]), 'Microsoft.Network/privateDnsZones', cosmosDnsZoneName))
var apiManagementDnsZoneId = !empty(apiManagementZoneFromLanding)
  ? apiManagementZoneFromLanding
  : (empty(string(existingDnsZones[apiManagementDnsZoneName]))
      ? resourceId('Microsoft.Network/privateDnsZones', apiManagementDnsZoneName)
      : resourceId(subscription().subscriptionId, string(existingDnsZones[apiManagementDnsZoneName]), 'Microsoft.Network/privateDnsZones', apiManagementDnsZoneName))

var storageInCurrentRg = storageResourceGroupName == resourceGroup().name && storageSecondResourceGroupName == resourceGroup().name
var searchInCurrentRg = aiSearchServiceResourceGroupName == resourceGroup().name
var cosmosInCurrentRg = cosmosResourceGroupName == resourceGroup().name

var defaultDeploymentName = take('${modelName}-${uniqueSuffix}', 64)

resource storageAccountPrimary 'Microsoft.Storage/storageAccounts@2023-05-01' = if (!storagePassedIn) {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_ZRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

resource storageAccountSecondary 'Microsoft.Storage/storageAccounts@2023-05-01' = if (!storageSecondPassedIn) {
  name: storageAccountNameSecondary
  location: location
  tags: tags
  sku: {
    name: 'Standard_ZRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

resource aiSearchService 'Microsoft.Search/searchServices@2023-11-01' = if (enableAISearch && !searchPassedIn) {
  name: aiSearchName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'standard'
  }
  properties: {
    disableLocalAuth: false
    hostingMode: 'default'
    publicNetworkAccess: 'disabled'
    semanticSearch: 'disabled'
    networkRuleSet: {
      ipRules: []
    }
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
  }
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = if (enableCosmosDb && !cosmosPassedIn) {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    disableLocalAuth: true
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    enableFreeTier: false
    publicNetworkAccess: 'Disabled'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
  }
}

#disable-next-line BCP036
resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: accountName
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
    allowProjectManagement: enableProject
    defaultProject: enableProject ? projectName : null
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
  }
}

resource aiAccountDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  name: '${accountName}/${defaultDeploymentName}'
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
    aiAccount
  ]
}

resource aiAccountDeploymentsAdditional 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = [for (deployment, index) in extraModelDeployments: {
  name: '${accountName}/${take(string(deployment.name ?? 'deployment${index}'), 64)}'
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
    aiAccount
  ]
}]

resource aiServicesDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[aiServicesDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(servicesAiZoneFromLanding)) {
  name: aiServicesDnsZoneName
  location: 'global'
}

resource openAiDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[openAiDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(openAiZoneFromLanding)) {
  name: openAiDnsZoneName
  location: 'global'
}

resource cognitiveServicesDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[cognitiveServicesDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(cognitiveServicesZoneFromLanding)) {
  name: cognitiveServicesDnsZoneName
  location: 'global'
}

resource searchDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[searchDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(searchZoneFromLanding)) {
  name: searchDnsZoneName
  location: 'global'
}

resource storageDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[storageDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(storageZoneFromLanding)) {
  name: storageDnsZoneName
  location: 'global'
}

resource cosmosDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[cosmosDnsZoneName])) && !centralDnsZoneByPolicyInHub && empty(cosmosZoneFromLanding)) {
  name: cosmosDnsZoneName
  location: 'global'
}

resource apimDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (empty(string(existingDnsZones[apiManagementDnsZoneName])) && !centralDnsZoneByPolicyInHub && apiManagementProvided && empty(apiManagementZoneFromLanding)) {
  name: apiManagementDnsZoneName
  location: 'global'
}

resource aiServicesDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[aiServicesDnsZoneName])) && empty(servicesAiZoneFromLanding)) {
  name: '${aiServicesDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    aiServicesDnsZone
  ]
}

resource openAiDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[openAiDnsZoneName])) && empty(openAiZoneFromLanding)) {
  name: '${openAiDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    openAiDnsZone
  ]
}

resource cognitiveServicesDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[cognitiveServicesDnsZoneName])) && empty(cognitiveServicesZoneFromLanding)) {
  name: '${cognitiveServicesDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    cognitiveServicesDnsZone
  ]
}

resource searchDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[searchDnsZoneName])) && empty(searchZoneFromLanding)) {
  name: '${searchDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    searchDnsZone
  ]
}

resource storageDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[storageDnsZoneName])) && empty(storageZoneFromLanding)) {
  name: '${storageDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    storageDnsZone
  ]
}

resource cosmosDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && empty(string(existingDnsZones[cosmosDnsZoneName])) && empty(cosmosZoneFromLanding)) {
  name: '${cosmosDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    cosmosDnsZone
  ]
}

resource apimDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!centralDnsZoneByPolicyInHub && apiManagementProvided && empty(string(existingDnsZones[apiManagementDnsZoneName])) && empty(apiManagementZoneFromLanding)) {
  name: '${apiManagementDnsZoneName}/${virtualNetworkName}-link'
  properties: {
    virtualNetwork: {
      id: virtualNetworkId
    }
    registrationEnabled: false
  }
  dependsOn: [
    apimDnsZone
  ]
}

var aiAccountDnsConfigs = concat(
  !empty(aiServicesDnsZoneId) && !centralDnsZoneByPolicyInHub ? [
    {
      name: 'aiservices'
      properties: {
        privateDnsZoneId: aiServicesDnsZoneId
      }
    }
  ] : [],
  !empty(openAiDnsZoneId) && !centralDnsZoneByPolicyInHub ? [
    {
      name: 'openai'
      properties: {
        privateDnsZoneId: openAiDnsZoneId
      }
    }
  ] : [],
  !empty(cognitiveServicesDnsZoneId) && !centralDnsZoneByPolicyInHub ? [
    {
      name: 'cognitiveservices'
      properties: {
        privateDnsZoneId: cognitiveServicesDnsZoneId
      }
    }
  ] : []
)

resource privateEndpointAccount 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${take(accountName, 40)}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(accountName, 40)}-account'
        properties: {
          privateLinkServiceId: aiAccount.id
          groupIds: [
            'account'
          ]
        }
      }
    ]
  }
  dependsOn: [
    aiAccount
  ]
}

resource privateEndpointAccountDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && !empty(aiAccountDnsConfigs)) {
  name: '${privateEndpointAccount.name}/cognitiveservices-dns'
  properties: {
    privateDnsZoneConfigs: aiAccountDnsConfigs
  }
}

var storageAccountId = storagePassedIn ? azureStorageAccountResourceId : storageAccountPrimary.id
var storageAccountSecondaryId = storageSecondPassedIn ? azureStorageAccountResourceIdSecondary : storageAccountSecondary.id
var aiSearchResourceIdEffective = searchPassedIn ? aiSearchResourceId : (enableAISearch ? aiSearchService.id : '')
var cosmosResourceIdEffective = cosmosPassedIn ? azureCosmosDBAccountResourceId : (enableCosmosDb ? cosmosAccount.id : '')

resource privateEndpointStorage 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${take(storageAccountName, 40)}-blob-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(storageAccountName, 40)}-blob'
        properties: {
          privateLinkServiceId: storageAccountId
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
  dependsOn: [
    privateEndpointAccount
  ]
}

resource privateEndpointStorageDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub) {
  name: '${privateEndpointStorage.name}/blob-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: storageDnsZoneId
        }
      }
    ]
  }
}

resource privateEndpointStorageSecondary 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enableCapabilityHost) {
  name: '${take(storageAccountNameSecondary, 40)}-blob-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(storageAccountNameSecondary, 40)}-blob'
        properties: {
          privateLinkServiceId: storageAccountSecondaryId
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
  dependsOn: [
    privateEndpointStorage
  ]
}

resource privateEndpointStorageSecondaryDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && enableCapabilityHost) {
  name: '${privateEndpointStorageSecondary.name}/blob-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: storageDnsZoneId
        }
      }
    ]
  }
}

resource privateEndpointSearch 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enableAISearch) {
  name: '${take(aiSearchName, 40)}-search-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(aiSearchName, 40)}-search'
        properties: {
          privateLinkServiceId: aiSearchResourceIdEffective
          groupIds: [
            'searchService'
          ]
        }
      }
    ]
  }
  dependsOn: [
    privateEndpointStorage
  ]
}

resource privateEndpointSearchDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && enableAISearch) {
  name: '${privateEndpointSearch.name}/search-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'search'
        properties: {
          privateDnsZoneId: searchDnsZoneId
        }
      }
    ]
  }
}

resource privateEndpointCosmos 'Microsoft.Network/privateEndpoints@2024-05-01' = if (enableCosmosDb) {
  name: '${take(cosmosAccountName, 40)}-cosmos-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(cosmosAccountName, 40)}-cosmos'
        properties: {
          privateLinkServiceId: cosmosResourceIdEffective
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
  dependsOn: [
    privateEndpointStorage
  ]
}

resource privateEndpointCosmosDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && enableCosmosDb) {
  name: '${privateEndpointCosmos.name}/cosmos-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmos'
        properties: {
          privateDnsZoneId: cosmosDnsZoneId
        }
      }
    ]
  }
}

resource privateEndpointApiManagement 'Microsoft.Network/privateEndpoints@2024-05-01' = if (apiManagementProvided) {
  name: '${take(apiManagementName, 40)}-apim-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetResourceId
    }
    privateLinkServiceConnections: [
      {
        name: '${take(apiManagementName, 40)}-apim'
        properties: {
          privateLinkServiceId: apiManagementResourceId
          groupIds: [
            'Gateway'
          ]
        }
      }
    ]
  }
  dependsOn: [
    privateEndpointStorage
  ]
}

resource privateEndpointApiManagementDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub && apiManagementProvided) {
  name: '${privateEndpointApiManagement.name}/apim-dns'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'apim'
        properties: {
          privateDnsZoneId: apiManagementDnsZoneId
        }
      }
    ]
  }
}


module projectModule 'aiFoundry2025project.bicep' = if (enableProject) {
  name: take('aifoundry-project-${uniqueSuffix}', 64)
  params: {
    name: projectName
    location: location
    cosmosDBname: enableCosmosDb ? cosmosAccountName : ''
    storageName: storageAccountName
    storageName2: storageAccountNameSecondary
    aiFoundryV2Name: accountName
    aiSearchName: enableAISearch ? aiSearchName : ''
    enablePublicAccessWithPerimeter: allowPublicAccessWhenBehindVnet
    defaultProjectName: projectName
    defaultProjectDisplayName: displayName
    defaultProjectDescription: projectDescription
  }
  dependsOn: [
    aiAccount
    privateEndpointAccount
    privateEndpointStorage
    ...(!storagePassedIn ? [storageAccountPrimary] : [])
    ...(!storageSecondPassedIn ? [storageAccountSecondary] : [])
    ...((enableAISearch && !searchPassedIn) ? [aiSearchService] : [])
    ...((enableCosmosDb && !cosmosPassedIn) ? [cosmosAccount] : [])
    ...(enableAISearch ? [privateEndpointSearch] : [])
    ...(enableCosmosDb ? [privateEndpointCosmos] : [])
    ...(enableCapabilityHost ? [privateEndpointStorageSecondary] : [])
    ...(apiManagementProvided ? [privateEndpointApiManagement] : [])
  ]
}

#disable-next-line BCP318
var projectPrincipalId = enableProject ? projectModule.outputs.projectPrincipalId : ''
#disable-next-line BCP318
var projectWorkspaceRawId = enableProject ? string(projectModule.outputs.projectWorkspaceId) : ''
var projectWorkspaceGuid = enableProject && !empty(projectWorkspaceRawId)
  ? format('{0}-{1}-{2}-{3}-{4}', substring(projectWorkspaceRawId, 0, 8), substring(projectWorkspaceRawId, 8, 4), substring(projectWorkspaceRawId, 12, 4), substring(projectWorkspaceRawId, 16, 4), substring(projectWorkspaceRawId, 20, 12))
  : ''

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
    accountName: accountName
    projectCapHostName: projectCapHost
  }
  dependsOn: [
    projectModule
    privateEndpointAccount
    privateEndpointStorage
    ...(enableAISearch ? [privateEndpointSearch] : [])
    ...(enableCosmosDb ? [privateEndpointCosmos] : [])
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
var storageFileDataPrivilegedContributorRoleId = '69566ab7-960f-4753-8033-0f276bb0955b'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

module aiFoundryRbac 'aiFoundry2025rbac.bicep' = if (!empty(userRoleObjectIds) || !empty(servicePrincipalIds) || enableProject) {
  name: take('aifoundry-rbac-${uniqueSuffix}', 64)
  params: {
    userObjectIds: userRoleObjectIds
    servicePrincipalIds: servicePrincipalIds
    projectPrincipalId: projectPrincipalId
    cognitiveServicesAccountName: accountName
    cognitiveServicesContributorRoleId: cognitiveServicesContributorRoleId
    cognitiveServicesUserRoleId: cognitiveServicesUserRoleId
    openAIContributorRoleId: openAIContributorRoleId
    openAIUserRoleId: openAIUserRoleId
    useAdGroups: useAdGroups
  }
  dependsOn: [
    aiAccount
    ...(enableProject ? [projectModule] : [])
  ]
}

module searchRbac 'rbacAISearchForAIFv2.bicep' = if (enableAISearch && searchInCurrentRg) {
  name: take('aifoundry-rbacsearch-${uniqueSuffix}', 64)
  params: {
    aiSearchName: aiSearchName
    aiFoundryAccountName: accountName
    projectPrincipalId: projectPrincipalId
    searchServiceContributorRoleId: searchServiceContributorRoleId
    searchIndexDataReaderRoleId: searchIndexDataReaderRoleId
    searchIndexDataContributorRoleId: searchIndexDataContributorRoleId
  }
  dependsOn: [
    aiAccount
    ...(enableProject ? [projectModule] : [])
    ...((enableAISearch && !searchPassedIn) ? [aiSearchService] : [])
  ]
}

module storageRbac 'rbacAIStorageAccountsForAIFv2.bicep' = if (storageInCurrentRg && enableProject) {
  name: take('aifoundry-rbacstorage-${uniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccountName
    storageAccountName2: storageAccountNameSecondary
    aiFoundryAccountName: accountName
    projectPrincipalId: projectPrincipalId
    storageBlobDataContributorRoleId: storageBlobDataContributorRoleId
    storageFileDataPrivilegedContributorRoleId: storageFileDataPrivilegedContributorRoleId
    storageQueueDataContributorRoleId: storageQueueDataContributorRoleId
  }
  dependsOn: [
    aiAccount
    ...(!storagePassedIn ? [storageAccountPrimary] : [])
    ...(!storageSecondPassedIn ? [storageAccountSecondary] : [])
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
    ...((enableCosmosDb && !cosmosPassedIn) ? [cosmosAccount] : [])
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
    ...((enableCosmosDb && !cosmosPassedIn) ? [cosmosAccount] : [])
    ...(!storagePassedIn ? [storageAccountPrimary] : [])
  ]
}

var aiAccountId = aiAccount.id
var aiAccountEndpoint = aiAccount.properties.endpoint
var aiAccountPrincipalId = aiAccount.identity.principalId

var storageAccountSubscriptionId = storageSubscriptionId
var storageAccountResourceGroup = storageResourceGroupName
var storageAccountSecondarySubscriptionId = storageSecondSubscriptionId
var storageAccountSecondaryResourceGroup = storageSecondResourceGroupName
var cosmosAccountSubscriptionId = cosmosSubscriptionId
var cosmosAccountResourceGroup = cosmosResourceGroupName
var aiSearchSubscriptionEffective = aiSearchSubscriptionId
var aiSearchResourceGroupEffective = aiSearchServiceResourceGroupName

var dnsZoneValidation = [
  for zoneName in dnsZoneNames: {
    name: zoneName
    exists: !empty(string(existingDnsZones[zoneName]))
  }
]

@description('The name of the cognitive services account.')
output aiAccountName string = accountName

@description('The resource ID of the cognitive services account.')
output aiAccountId string = aiAccountId

@description('The service endpoint of the cognitive services account.')
output aiAccountEndpoint string = aiAccountEndpoint

@description('The principal ID of the system assigned identity.')
output aiAccountPrincipalId string = aiAccountPrincipalId

@description('Indicates whether the default project was deployed.')
output aiFoundryProjectDeployed bool = enableProject

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

@description('Validation summary for expected private DNS zones.')
output dnsZoneValidation array = dnsZoneValidation

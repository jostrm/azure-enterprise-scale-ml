/*
Private Endpoint and DNS Configuration Module
------------------------------------------
This module configures private network access for Azure services using:

1. Private Endpoints:
   - Creates network interfaces in the specified subnet
   - Establishes private connections to Azure services
   - Enables secure access without public internet exposure

2. Private DNS Zones:
   - Enables custom DNS resolution for private endpoints

3. DNS Zone Links:
   - Links private DNS zones to the VNet
   - Enables name resolution for resources in the VNet
   - Prevents DNS resolution conflicts

Security Benefits:
- Eliminates public internet exposure
- Enables secure access from within VNet
- Prevents data exfiltration through network
*/

// Resource names and identifiers
@description('Name of the AI Foundry account')
param aiAccountName string
@description('Name of the AI Search service')
param aiSearchName string
@description('Name of the storage account')
param storageName string
@description('Name of the Cosmos DB account')
param cosmosDBName string
@description('Name of the API Management service (optional)')
param apiManagementName string = ''
@description('Name of the Vnet')
param vnetName string
@description('Name of the Customer subnet')
param peSubnetName string
@description('Suffix for unique resource names')
param suffix string

@description('Resource Group name for existing Virtual Network (if different from current resource group)')
param vnetResourceGroupName string = resourceGroup().name

@description('Subscription ID for Virtual Network')
param vnetSubscriptionId string = subscription().subscriptionId

@description('Resource Group name for Storage Account')
param storageAccountResourceGroupName string = resourceGroup().name

@description('Subscription ID for Storage account')
param storageAccountSubscriptionId string = subscription().subscriptionId

@description('Subscription ID for AI Search service')
param aiSearchSubscriptionId string = subscription().subscriptionId

@description('Resource Group name for AI Search service')
param aiSearchResourceGroupName string = resourceGroup().name

@description('Subscription ID for Cosmos DB account')
param cosmosDBSubscriptionId string = subscription().subscriptionId

@description('Resource group name for Cosmos DB account')
param cosmosDBResourceGroupName string = resourceGroup().name

@description('Subscription ID for API Management service (optional)')
param apiManagementSubscriptionId string = subscription().subscriptionId

@description('Resource group name for API Management service (optional)')
param apiManagementResourceGroupName string = resourceGroup().name

@description('Map of DNS zone FQDNs to resource group names. If provided, reference existing DNS zones in this resource group instead of creating them.')
param existingDnsZones object = {
  'privatelink.services.ai.azure.com': ''
  'privatelink.openai.azure.com': ''
  'privatelink.cognitiveservices.azure.com': ''
  'privatelink.search.windows.net': ''
  'privatelink.blob.${environment().suffixes.storage}': ''
  'privatelink.documents.azure.com': ''
  'privatelink.azure-api.net': ''
}

// ---- Resource references ----
resource aiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiAccountName
  scope: resourceGroup()
}

resource aiSearch 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: aiSearchName
  scope: resourceGroup(aiSearchSubscriptionId, aiSearchResourceGroupName)
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName
  scope: resourceGroup(storageAccountSubscriptionId, storageAccountResourceGroupName)
}

resource cosmosDBAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosDBName
  scope: resourceGroup(cosmosDBSubscriptionId, cosmosDBResourceGroupName)
}

resource apiManagementService 'Microsoft.ApiManagement/service@2023-05-01-preview' existing = if (!empty(apiManagementName)) {
  name: apiManagementName
  scope: resourceGroup(apiManagementSubscriptionId, apiManagementResourceGroupName)
}

// Reference existing network resources
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetSubscriptionId, vnetResourceGroupName)
}
resource peSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: peSubnetName
}

/* -------------------------------------------- AI Foundry Account Private Endpoint -------------------------------------------- */

// Private endpoint for AI Services account
// - Creates network interface in customer hub subnet
// - Establishes private connection to AI Services account
resource aiAccountPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${aiAccountName}-private-endpoint'
  location: resourceGroup().location
  properties: {
    subnet: { id: peSubnet.id } // Deploy in customer hub subnet
    privateLinkServiceConnections: [
      {
        name: '${aiAccountName}-private-link-service-connection'
        properties: {
          privateLinkServiceId: aiAccount.id
          groupIds: [ 'account' ] // Target AI Services account
        }
      }
    ]
  }
}

/* -------------------------------------------- AI Search Private Endpoint -------------------------------------------- */

// Private endpoint for AI Search
// - Creates network interface in customer hub subnet
// - Establishes private connection to AI Search service
resource aiSearchPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${aiSearchName}-private-endpoint'
  location: resourceGroup().location
  properties: {
    subnet: { id: peSubnet.id } // Deploy in customer hub subnet
    privateLinkServiceConnections: [
      {
        name: '${aiSearchName}-private-link-service-connection'
        properties: {
          privateLinkServiceId: aiSearch.id
          groupIds: [ 'searchService' ] // Target search service
        }
      }
    ]
  }
  dependsOn: [
    aiAccountPrivateEndpoint
  ]
}

/* -------------------------------------------- Storage Private Endpoint -------------------------------------------- */

// Private endpoint for Storage Account
// - Creates network interface in customer hub subnet
// - Establishes private connection to blob storage
resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${storageName}-private-endpoint'
  location: resourceGroup().location
  properties: {
    subnet: { id: peSubnet.id } // Deploy in customer hub subnet
    privateLinkServiceConnections: [
      {
        name: '${storageName}-private-link-service-connection'
        properties: {
          privateLinkServiceId: storageAccount.id // Target blob storage
          groupIds: [ 'blob' ]
        }
      }
    ]
  }
  dependsOn: [
    aiSearchPrivateEndpoint
  ]
}

/*--------------------------------------------- Cosmos DB Private Endpoint -------------------------------------*/

resource cosmosDBPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${cosmosDBName}-private-endpoint'
  location: resourceGroup().location
  properties: {
    subnet: { id: peSubnet.id } // Deploy in customer hub subnet
    privateLinkServiceConnections: [
      {
        name: '${cosmosDBName}-private-link-service-connection'
        properties: {
          privateLinkServiceId: cosmosDBAccount.id // Target Cosmos DB account
          groupIds: [ 'Sql' ]
        }
      }
    ]
  }
  dependsOn: [
    storagePrivateEndpoint
  ]
}

/*--------------------------------------------- API Management Private Endpoint -------------------------------------*/

resource apiManagementPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (!empty(apiManagementName)) {
  name: '${apiManagementName}-private-endpoint'
  location: resourceGroup().location
  properties: {
    subnet: { id: peSubnet.id } // Deploy in customer hub subnet
    privateLinkServiceConnections: [
      {
        name: '${apiManagementName}-private-link-service-connection'
        properties: {
          privateLinkServiceId: apiManagementService.id // Target API Management service
          groupIds: [ 'Gateway' ] // Gateway endpoint for API calls
        }
      }
    ]
  }
  dependsOn: [
    cosmosDBPrivateEndpoint
  ]
}

/* -------------------------------------------- Private DNS Zones -------------------------------------------- */

// Format: 1) Private DNS Zone
//         2) Link Private DNS Zone to VNet
//         3) Create DNS Zone Group for Private Endpoint

// Private DNS Zone for AI Services (Account)
// 1) Enables custom DNS resolution for AI Services private endpoint

var aiServicesDnsZoneName = 'privatelink.services.ai.azure.com'
var openAiDnsZoneName = 'privatelink.openai.azure.com'
var cognitiveServicesDnsZoneName = 'privatelink.cognitiveservices.azure.com'
var aiSearchDnsZoneName = 'privatelink.search.windows.net'
var storageDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'
var cosmosDBDnsZoneName = 'privatelink.documents.azure.com'
var apiManagementDnsZoneName = 'privatelink.azure-api.net'
var aiServicesDnsZoneInput = contains(existingDnsZones, aiServicesDnsZoneName) ? string(existingDnsZones[aiServicesDnsZoneName]) : ''
var openAiDnsZoneInput = contains(existingDnsZones, openAiDnsZoneName) ? string(existingDnsZones[openAiDnsZoneName]) : ''
var cognitiveServicesDnsZoneInput = contains(existingDnsZones, cognitiveServicesDnsZoneName) ? string(existingDnsZones[cognitiveServicesDnsZoneName]) : ''
var aiSearchDnsZoneInput = contains(existingDnsZones, aiSearchDnsZoneName) ? string(existingDnsZones[aiSearchDnsZoneName]) : ''
var storageDnsZoneInput = contains(existingDnsZones, storageDnsZoneName) ? string(existingDnsZones[storageDnsZoneName]) : ''
var cosmosDBDnsZoneInput = contains(existingDnsZones, cosmosDBDnsZoneName) ? string(existingDnsZones[cosmosDBDnsZoneName]) : ''
var apiManagementDnsZoneInput = contains(existingDnsZones, apiManagementDnsZoneName) ? string(existingDnsZones[apiManagementDnsZoneName]) : ''

var aiServicesDnsZoneProvided = !empty(aiServicesDnsZoneInput)
var openAiDnsZoneProvided = !empty(openAiDnsZoneInput)
var cognitiveServicesDnsZoneProvided = !empty(cognitiveServicesDnsZoneInput)
var aiSearchDnsZoneProvided = !empty(aiSearchDnsZoneInput)
var storageDnsZoneProvided = !empty(storageDnsZoneInput)
var cosmosDBDnsZoneProvided = !empty(cosmosDBDnsZoneInput)
var apiManagementDnsZoneProvided = !empty(apiManagementDnsZoneInput)

var aiServicesDnsZoneExistingId = aiServicesDnsZoneProvided
  ? (startsWith(toLower(aiServicesDnsZoneInput), '/subscriptions/')
      ? aiServicesDnsZoneInput
      : resourceId(subscription().subscriptionId, aiServicesDnsZoneInput, 'Microsoft.Network/privateDnsZones', aiServicesDnsZoneName))
  : ''
var openAiDnsZoneExistingId = openAiDnsZoneProvided
  ? (startsWith(toLower(openAiDnsZoneInput), '/subscriptions/')
      ? openAiDnsZoneInput
      : resourceId(subscription().subscriptionId, openAiDnsZoneInput, 'Microsoft.Network/privateDnsZones', openAiDnsZoneName))
  : ''
var cognitiveServicesDnsZoneExistingId = cognitiveServicesDnsZoneProvided
  ? (startsWith(toLower(cognitiveServicesDnsZoneInput), '/subscriptions/')
      ? cognitiveServicesDnsZoneInput
      : resourceId(subscription().subscriptionId, cognitiveServicesDnsZoneInput, 'Microsoft.Network/privateDnsZones', cognitiveServicesDnsZoneName))
  : ''
var aiSearchDnsZoneExistingId = aiSearchDnsZoneProvided
  ? (startsWith(toLower(aiSearchDnsZoneInput), '/subscriptions/')
      ? aiSearchDnsZoneInput
      : resourceId(subscription().subscriptionId, aiSearchDnsZoneInput, 'Microsoft.Network/privateDnsZones', aiSearchDnsZoneName))
  : ''
var storageDnsZoneExistingId = storageDnsZoneProvided
  ? (startsWith(toLower(storageDnsZoneInput), '/subscriptions/')
      ? storageDnsZoneInput
      : resourceId(subscription().subscriptionId, storageDnsZoneInput, 'Microsoft.Network/privateDnsZones', storageDnsZoneName))
  : ''
var cosmosDBDnsZoneExistingId = cosmosDBDnsZoneProvided
  ? (startsWith(toLower(cosmosDBDnsZoneInput), '/subscriptions/')
      ? cosmosDBDnsZoneInput
      : resourceId(subscription().subscriptionId, cosmosDBDnsZoneInput, 'Microsoft.Network/privateDnsZones', cosmosDBDnsZoneName))
  : ''
var apiManagementDnsZoneExistingId = apiManagementDnsZoneProvided
  ? (startsWith(toLower(apiManagementDnsZoneInput), '/subscriptions/')
      ? apiManagementDnsZoneInput
      : resourceId(subscription().subscriptionId, apiManagementDnsZoneInput, 'Microsoft.Network/privateDnsZones', apiManagementDnsZoneName))
  : ''

// ---- DNS Zone Resources and References ----
resource aiServicesPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!aiServicesDnsZoneProvided) {
  name: aiServicesDnsZoneName
  location: 'global'
}
var aiServicesDnsZoneId = aiServicesDnsZoneProvided ? aiServicesDnsZoneExistingId : aiServicesPrivateDnsZone.id

resource openAiPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!openAiDnsZoneProvided) {
  name: openAiDnsZoneName
  location: 'global'
}
var openAiDnsZoneId = openAiDnsZoneProvided ? openAiDnsZoneExistingId : openAiPrivateDnsZone.id

resource cognitiveServicesPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!cognitiveServicesDnsZoneProvided) {
  name: cognitiveServicesDnsZoneName
  location: 'global'
}
var cognitiveServicesDnsZoneId = cognitiveServicesDnsZoneProvided ? cognitiveServicesDnsZoneExistingId : cognitiveServicesPrivateDnsZone.id

resource aiSearchPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!aiSearchDnsZoneProvided) {
  name: aiSearchDnsZoneName
  location: 'global'
}
var aiSearchDnsZoneId = aiSearchDnsZoneProvided ? aiSearchDnsZoneExistingId : aiSearchPrivateDnsZone.id

resource storagePrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!storageDnsZoneProvided) {
  name: storageDnsZoneName
  location: 'global'
}
var storageDnsZoneId = storageDnsZoneProvided ? storageDnsZoneExistingId : storagePrivateDnsZone.id

resource cosmosDBPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!cosmosDBDnsZoneProvided) {
  name: cosmosDBDnsZoneName
  location: 'global'
}
var cosmosDBDnsZoneId = cosmosDBDnsZoneProvided ? cosmosDBDnsZoneExistingId : cosmosDBPrivateDnsZone.id

resource apiManagementPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!apiManagementDnsZoneProvided && !empty(apiManagementName)) {
  name: apiManagementDnsZoneName
  location: 'global'
}
var apiManagementDnsZoneId = !empty(apiManagementName)
  ? (apiManagementDnsZoneProvided ? apiManagementDnsZoneExistingId : apiManagementPrivateDnsZone.id)
  : ''

// ---- DNS VNet Links ----
resource aiServicesLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!aiServicesDnsZoneProvided) {
  parent: aiServicesPrivateDnsZone
  location: 'global'
  name: 'aiServices-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource openAiLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!openAiDnsZoneProvided) {
  parent: openAiPrivateDnsZone
  location: 'global'
  name: 'aiServicesOpenAI-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource cognitiveServicesLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!cognitiveServicesDnsZoneProvided) {
  parent: cognitiveServicesPrivateDnsZone
  location: 'global'
  name: 'aiServicesCognitiveServices-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource aiSearchLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!aiSearchDnsZoneProvided) {
  parent: aiSearchPrivateDnsZone
  location: 'global'
  name: 'aiSearch-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource storageLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!storageDnsZoneProvided) {
  parent: storagePrivateDnsZone
  location: 'global'
  name: 'storage-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource cosmosDBLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!cosmosDBDnsZoneProvided) {
  parent: cosmosDBPrivateDnsZone
  location: 'global'
  name: 'cosmosDB-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource apiManagementLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!apiManagementDnsZoneProvided && !empty(apiManagementName)) {
  parent: apiManagementPrivateDnsZone
  location: 'global'
  name: 'apiManagement-${suffix}-link'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

// ---- DNS Zone Groups ----
resource aiServicesDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: aiAccountPrivateEndpoint
  name: '${aiAccountName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${aiAccountName}-dns-aiserv-config', properties: { privateDnsZoneId: aiServicesDnsZoneId } }
      { name: '${aiAccountName}-dns-openai-config', properties: { privateDnsZoneId: openAiDnsZoneId } }
      { name: '${aiAccountName}-dns-cogserv-config', properties: { privateDnsZoneId: cognitiveServicesDnsZoneId } }
    ]
  }
}
resource aiSearchDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: aiSearchPrivateEndpoint
  name: '${aiSearchName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${aiSearchName}-dns-config', properties: { privateDnsZoneId: aiSearchDnsZoneId } }
    ]
  }
}
resource storageDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: storagePrivateEndpoint
  name: '${storageName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${storageName}-dns-config', properties: { privateDnsZoneId: storageDnsZoneId } }
    ]
  }
}
resource cosmosDBDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: cosmosDBPrivateEndpoint
  name: '${cosmosDBName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${cosmosDBName}-dns-config', properties: { privateDnsZoneId: cosmosDBDnsZoneId } }
    ]
  }
}
resource apiManagementDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!empty(apiManagementName)) {
  parent: apiManagementPrivateEndpoint
  name: '${apiManagementName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${apiManagementName}-dns-config', properties: { privateDnsZoneId: apiManagementDnsZoneId } }
    ]
  }
}

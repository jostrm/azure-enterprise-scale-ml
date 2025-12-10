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
param centralDnsZoneByPolicyInHub bool = false
param createPrivateEndpointsAIFactoryWay bool = true
param tags object = {}
param targetSubscriptionId string
param targetResourceGroup string
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

@description('Full privateLinksDnsZones object emitted by CmnPrivateDnsZones; provides consistent names and resource IDs for all required private DNS zones.')
param privateLinksDnsZones object

@description('Subscription hosting private DNS zones when centrally managed.')
param privDnsSubscription string = subscription().subscriptionId

@description('Resource group hosting private DNS zones when centrally managed.')
param privDnsResourceGroupName string = resourceGroup().name

// ---- Resource references ----
resource aiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiAccountName
  scope: resourceGroup()
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
resource aiAccountPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if(!createPrivateEndpointsAIFactoryWay) {
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

resource pendCogServiceAIF 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpointsAIFactoryWay) {
  name: '${aiAccountName}-pend' //'${privateEndpointName}-2'
  location: resourceGroup().location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${aiAccountName}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${aiAccountName}-pend'
        properties: {
          groupIds: [
            'account'
          ]
          privateLinkServiceId: aiAccount.id
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    subnet: {
      id: peSubnet.id 
    }
  }
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
    aiAccountPrivateEndpoint
  ]
}

/* -------------------------------------------- Private DNS Zones -------------------------------------------- */

// Reference existing private DNS zones from the central DNS resource group
resource aiServicesDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: string(privateLinksDnsZones.servicesai.name)
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)
}

resource openAiDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: string(privateLinksDnsZones.openai.name)
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)
}

resource cognitiveServicesDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: string(privateLinksDnsZones.cognitiveservices.name)
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)
}

resource apiManagementDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = if (!empty(apiManagementName)) {
  name: string(privateLinksDnsZones.apim.name)
  scope: resourceGroup(privDnsSubscription, privDnsResourceGroupName)
}

// IDs sourced from existing resource references with correct subscription/resource group scope
var aiServicesDnsZoneId = aiServicesDnsZone.id
var openAiDnsZoneId = openAiDnsZone.id
var cognitiveServicesDnsZoneId = cognitiveServicesDnsZone.id
var apiManagementDnsZoneId = !empty(apiManagementName) ? apiManagementDnsZone.id : ''

/* ---- DNS Zone Groups ----
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
resource apiManagementDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!empty(apiManagementName)) {
  parent: apiManagementPrivateEndpoint
  name: '${apiManagementName}-dns-group'
  properties: {
    privateDnsZoneConfigs: [
      { name: '${apiManagementName}-dns-config', properties: { privateDnsZoneId: apiManagementDnsZoneId } }
    ]
  }
}
*/

resource privateEndpointDnsGroupAPIM 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub) {
  name: '${apiManagementPrivateEndpoint.name}DnsZone'
  parent: apiManagementPrivateEndpoint
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateLinksDnsZones.apim.name
        properties:{
          privateDnsZoneId: apiManagementDnsZoneId // privateLinksDnsZones.apim.id
        }
      }
    ]
  }
}

resource privateEndpointDnsGroupAIF 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (!centralDnsZoneByPolicyInHub) {
  name: '${pendCogServiceAIF.name}DnsZone'
  parent: pendCogServiceAIF
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateLinksDnsZones.openai.name
        properties:{
          privateDnsZoneId: openAiDnsZoneId // privateLinksDnsZones.openai.id
        }
      }
      {
        name: privateLinksDnsZones.cognitiveservices.name
        properties:{
          privateDnsZoneId: cognitiveServicesDnsZoneId //privateLinksDnsZones.cognitiveservices.id
        }
      }
      {
        name: privateLinksDnsZones.servicesai.name
        properties:{
          privateDnsZoneId: aiServicesDnsZoneId // privateLinksDnsZones.servicesai.id
        }
      }
    ]
  }
}


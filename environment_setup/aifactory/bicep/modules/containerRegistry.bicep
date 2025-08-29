@description('(Optional) Specifies the Azure container registry service tier name, defaults to premium because of the private endpoints association')
@allowed(['Premium', 'Standard', 'Basic']) 
param skuName string = 'Premium' // NB! Basic and Standard ACR SKUs don't support private endpoints.

@description('(Required) Specifies the name of the Azure container registry that will be deployed')
param containerRegistryName string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

@description('(Required) Specifies the tags that will be associated with azure container registry resources')
param tags object
param location string
param vnetName string
param vnetResourceGroupName string
param enablePublicAccessWithPerimeter bool = false
param allowPublicAccessWhenBehindVnet bool = false
param adminUserEnabled bool = false
param dedicatedDataPoint bool = true
param zoneRedundancy string = 'Disabled'
param ipRules array = []
param existingIpRules array = []

//var subnetRef = '${vnetId}/subnets/${subnetName}'
var policyOn = 'disabled' // 'enabled' // 'disabled' GET https:: IMAGE_QUARANTINED: The image is quarantined
var containerRegistryNameCleaned = replace(containerRegistryName, '-', '')

// Combine existing IP rules with new ones
var allIpRules = union(existingIpRules, ipRules)

// Normalize IP addresses: ensure single IPs have /32 suffix for proper deduplication
var normalizedIpRules = map(allIpRules, rule => {
  value: contains(rule.value, '/') ? rule.value : '${rule.value}/32'
  action: rule.action
})

// Remove duplicates by creating a unique set based on the normalized 'value' property
var uniqueIpRulesMap = reduce(normalizedIpRules, {}, (acc, rule) => union(acc, { '${rule.value}': rule }))
var uniqueIpRules = map(items(uniqueIpRulesMap), item => item.value)

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}

// 2023-11-01-preview needed for metadataSearch (prev: registries@2023-07-01, 2023-11-01-preview)
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2024-11-01-preview' = {
  name: containerRegistryNameCleaned
  tags: tags
  location: location
  sku: {
    name: skuName
  }
  properties: {
    adminUserEnabled: adminUserEnabled
    networkRuleSet: !enablePublicAccessWithPerimeter ? {
      defaultAction: 'Deny'
      ipRules: uniqueIpRules
    }:null
    dataEndpointEnabled: dedicatedDataPoint
    networkRuleBypassOptions:'AzureServices'
    policies: {
      quarantinePolicy: {
        status: policyOn
      }
      retentionPolicy: {
        status: policyOn
        days: 7
      }
      trustPolicy: {
        status: policyOn
        type: 'Notary'
      }
    }
    publicNetworkAccess: enablePublicAccessWithPerimeter || allowPublicAccessWhenBehindVnet?'Enabled': 'Disabled'
    zoneRedundancy: zoneRedundancy
  }
}

resource pendAcr 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    subnet: {
      id: subnet.id
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: containerRegistry.id
          groupIds: [
            'registry'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
       
      }
      
    ]
  }
}

output containerRegistryId string = containerRegistry.id
output containerRegistryName string = containerRegistry.name
output registryLoginServer string = containerRegistry.properties.loginServer
output dnsConfig array = [
  {
    name: pendAcr.name
    type: 'registry'
    id:containerRegistry.id
  }
]
